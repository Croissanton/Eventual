import pymongo

from environs import Env
from bson import ObjectId
from flask import Flask, render_template, request, redirect, url_for, session
from authlib.integrations.flask_client import OAuth
from datetime import datetime

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
    client_id=env('GOOGLE_CLIENT_ID'),
    client_secret=env('GOOGLE_CLIENT_SECRET'),
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
geolocator = Nominatim(user_agent="EventualApp")

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

events = db.evento         # events = db['evento']

logs = db.log              # logs = db['log']

# Definicion de metodos para endpoints

@app.route('/', methods=['GET', 'POST'])
def home():
    events_list = []
    if request.method == 'POST':
        address = request.form.get('address')
        if address:
            location = geolocator.geocode(address)
            if location:
                lat = location.latitude
                lon = location.longitude
                # Query events within 0.2 degrees
                events_cursor = events.find({
                    'lat': {'$gte': lat - 0.2, '$lte': lat + 0.2},
                    'lon': {'$gte': lon - 0.2, '$lte': lon + 0.2}
                }).sort('timestamp', 1)
                events_list = list(events_cursor)
    return render_template('events.html', events=events_list)

@app.route('/login')
def login():
    return oauth.google.authorize_redirect(url_for('authorize', _external=True))

@app.route('/authorize')
def authorize():
    token = oauth.google.authorize_access_token()
    nonce = session.pop('nonce', None)
    user = oauth.google.parse_id_token(token, nonce=nonce)
    session['user'] = user
    
    # Log login information
    log_entry = {
        'timestamp': datetime.now(),
        'email': user['email'],
        'caducidad': datetime.fromtimestamp(token['expires_at']),
        'token': token['access_token']
    }
    logs.insert_one(log_entry)
    
    return redirect(url_for('home'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))
    
@app.route('/new', methods=['GET', 'POST'])
def newEvent():

    if request.method == 'GET':
        return render_template('new.html')
    else:
        # Geocoding the address
        location = geolocator.geocode(request.form['inputLocation'])
        if location:
            lat = location.latitude
            lon = location.longitude
        else:
            lat = None
            lon = None

        # Handling image upload
        image = request.files.get('image')
        if image:
            upload_result = cloudinary.uploader.upload(image)
            image_url = upload_result.get('secure_url')
        else:
            image_url = ''

        event = {
            'nombre': request.form['inputName'],
            # Option 1: Update format string to include 'T'
            'timestamp': datetime.strptime(request.form['inputTimestamp'], '%Y-%m-%dT%H:%M'),
            # Option 2: Use fromisoformat
            # 'timestamp': datetime.fromisoformat(request.form['inputTimestamp']),
            'lugar': request.form['inputLocation'],
            'lat': lat,
            'lon': lon,
            'organizador': session['user']['email'],
            'imagen': image_url
        }

        events.insert_one(event)
        return redirect(url_for('home'))

@app.route('/edit/<_id>', methods = ['GET', 'POST'])
def editEvent(_id):
    
    if request.method == 'GET' :
        event = events.find_one({'_id': ObjectId(_id)})
        return render_template('edit.html', event = event)
    else:
        # Ensure the user is the organizer
        event = events.find_one({'_id': ObjectId(_id)})
        if event['organizador'] != session['user']['email']:
            return "Unauthorized", 403
        
        # Geocoding the address
        location = geolocator.geocode(request.form['inputLocation'])
        if location:
            lat = location.latitude
            lon = location.longitude
        else:
            lat = event.get('lat')
            lon = event.get('lon')
        
        # Handling image upload
        image = request.files.get('image')
        if image:
            upload_result = cloudinary.uploader.upload(image)
            image_url = upload_result.get('secure_url')
        else:
            image_url = event.get('imagen', '')
        
        updated_event = {
            'nombre': request.form['inputName'],
            'timestamp': datetime.strptime(request.form['inputTimestamp'], '%Y-%m-%dT%H:%M'),
            'lugar': request.form['inputLocation'],
            'lat': lat,
            'lon': lon,
            'imagen': image_url
        }
        events.update_one({'_id': ObjectId(_id)}, {'$set': updated_event})
        return redirect(url_for('home'))

@app.route('/delete/<_id>', methods = ['GET'])
def deleteEvent(_id):
    event = events.find_one({'_id': ObjectId(_id)})
    #Ensure the user is the organizer
    if event['organizador'] != session['user']['email']:
        return "Unauthorized", 403
     # Delete should also delete the image from Cloudinary
    if event['imagen']:
        # Manually extract the public_id from the URL
        url_parts = event['imagen'].split('/')
        file_name = url_parts[-1]  # Get the last part of the URL (e.g., vgq9cclmrgayqkn16cyi.png)
        public_id = file_name.rsplit('.', 1)[0]  # Remove the file extension
        print("AQUI VA : " + public_id)  # Debugging
        # Delete from Cloudinary
        cloudinary.uploader.destroy(public_id)


    events.delete_one({'_id': ObjectId(_id)})
    return redirect(url_for('home'))

@app.route('/event/<_id>', methods=['GET'])
def event_details(_id):
    event = events.find_one({'_id': ObjectId(_id)})
    if event:
        return render_template('details.html', event=event)
    return "Event not found", 404

@app.route('/events', methods=['GET'])
def viewEvents():
    all_events = list(events.find().sort('timestamp', pymongo.DESCENDING))
    return render_template('events.html', events=all_events)

if __name__ == '__main__':
    # This is used when running locally only. When deploying to Google App Engine
    # or Heroku, a webserver process such as Gunicorn will serve the app. In App
    # Engine, this can be configured by adding an `entrypoint` to app.yaml.
    app.run(host='127.0.0.1', port=8000, debug=True)
    

    # ejecucion en local: python main.py
