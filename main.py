import pymongo

from environs import Env
from bson import ObjectId
from flask import Flask, render_template, request, redirect, url_for, session, flash
from authlib.integrations.flask_client import OAuth
from datetime import datetime
import folium

import cloudinary
from cloudinary import CloudinaryImage
import cloudinary.uploader
import cloudinary.api
from geopy.geocoders import Nominatim
from werkzeug.middleware.proxy_fix import ProxyFix


env = Env()
env.read_env()  # read .env file, if it exists

app = Flask(__name__)
app.secret_key = env('FLASK_SECRET_KEY')
oauth = OAuth(app)
oauth.init_app(app)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PREFERRED_URL_SCHEME='https'
)

# Configure your OAuth provider (e.g., Google)
oauth.register(
    name='google',
    client_id=env('GOOGLE_LOCAL_CLIENT_ID'),
    client_secret=env('GOOGLE_LOCAL_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid profile email'}
)

# Configure Cloudinary
cloudinary.config(
    cloud_name=env('CLOUDINARY_CLOUD_NAME'),
    api_key=env('CLOUDINARY_API_KEY'),
    api_secret=env('CLOUDINARY_API_SECRET')
)

# Initialize geocoder
geolocator = Nominatim(user_agent="LocationualApp")

uri = env('MONGO_URI')              # establecer la variable de entorno MONGO_URI con la URI de la base de datos
                                    # MongoDB local:
                                    #     MONGO_URI = mongodb://localhost:27017
                                    # MongoDB Atlas:
                                    #     MONGO_URI = mongodb+srv://<USER>:<PASS>@<CLUSTER>.mongodb.net/?retryWrites=true&w=majority
                                    # MongoDB en Docker
                                    #     MONGO_URI = mongodb://root:example@mongodb:27017

client = pymongo.MongoClient(uri)

db = client.ExamenFrontend   # db = client['misAnuncios']


users = db.usuario         # users = db['usuario']

locations = db.locationo         # locations = db['locationo']

logs = db.log              # logs = db['log']

visits = db.visita

# Definicion de metodos para endpoints

@app.route('/login')
def login():
    return oauth.google.authorize_redirect(url_for('authorize', _external=True))

@app.route('/authorize')
def authorize():
    token = oauth.google.authorize_access_token()
    nonce = session.pop('nonce', None)
    user = oauth.google.parse_id_token(token, nonce=nonce)
    session['user'] = user
    session['token'] = token
    
    return redirect(url_for('home'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))

# METODOS PARA FUNCIONALIDADES

@app.route('/', methods=['GET', 'POST'])
def home():
    if 'user' in session:
        email = session['user']['email']
        if request.method == 'POST':
            # Obtener el email ingresado para visualizar otro mapa
            search_email = request.form.get('email')
            if search_email == email:
                return redirect(url_for('home'))
            if search_email:
                email = search_email
                # Registrar la visita
                visit = {
                    'timestamp': datetime.now(),
                    'visited_email': email,
                    'visitor_email': session['user']['email'],
                    'token': session['token']['access_token']
                }
                visits.insert_one(visit)
        # Obtener ubicaciones del usuario
        user_locations = list(locations.find({'email': email}))
        # Crear mapa
        if user_locations:
            start_coords = (user_locations[0]['lat'], user_locations[0]['lon'])
        else:
            start_coords = (0, 0)
        mapa = folium.Map(location=start_coords, zoom_start=2)
        # Agregar marcadores
        for loc in user_locations:
            popup_content = f"<b>{loc['lugar']}</b>"
            if loc['imagen']:
                popup_content += f"<br><img src='{loc['imagen']}' width='100'>"
            folium.Marker(
                location=[loc['lat'], loc['lon']],
                popup=folium.Popup(popup_content, max_width=200)
            ).add_to(mapa)
        mapa_html = mapa._repr_html_()
        # Obtener visitas si es el propio usuario
        user_visits = []
        if email == session['user']['email']:
            user_visits = list(visits.find({'visited_email': email}).sort('timestamp', pymongo.DESCENDING))
        return render_template('map.html', mapa=mapa_html, user_visits=user_visits, email=email)
    else:
        return redirect(url_for('login'))

@app.route('/new', methods=['GET', 'POST'])
def newLocation():
    if 'user' not in session:
        return redirect(url_for('login'))
    if request.method == 'GET':
        return render_template('new.html')
    else:
        # Geocodificar la dirección
        location_name = request.form['inputLocation']
        location = geolocator.geocode(location_name)
        if location:
            lat = location.latitude
            lon = location.longitude
        else:
            flash('No se pudo obtener las coordenadas de la ubicación.')
            return redirect(url_for('newLocation'))
        # Manejar carga de imagen
        image = request.files.get('image')
        if image:
            upload_result = cloudinary.uploader.upload(image)
            image_url = upload_result.get('secure_url')
        else:
            image_url = ''
        new_location = {
            'email': session['user']['email'],
            'lugar': location_name,
            'lat': lat,
            'lon': lon,
            'imagen': image_url
        }
        locations.insert_one(new_location)
        return redirect(url_for('home'))


if __name__ == '__main__':
    # This is used when running locally only. When deploying to Google App Engine
    # or Heroku, a webserver process such as Gunicorn will serve the app. In App
    # Engine, this can be configured by adding an `entrypoint` to app.yaml.
    app.run(host='127.0.0.1', port=8000, debug=True)
    

    # ejecucion en local: python main.py


