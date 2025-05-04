import os
import hmac
import hashlib
import json
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
import logging
from waitress import serve
import offreBot

# Configuration du logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class Config:
    # Token pour la validation initiale (GET)
    VERIFY_TOKEN = ('claudelAI223')
    # App Secret pour la signature HMAC (POST)
    APP_SECRET = b'7c61b31a0530bc3cc28f632a9b3e32be'

    # Variables WhatsApp/Mongo
    MONGO_URI = offreBot.MONGO_URI
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    PORT = int(os.getenv('PORT', 10000))

    @classmethod
    def validate(cls):
        missing = []
        if not cls.MONGO_URI:
            missing.append('MONGODB_URI')
        if not cls.WA_PHONE_ID:
            missing.append('WHATSAPP_PHONE_ID')
        if not cls.WA_ACCESS_TOKEN:
            missing.append('WHATSAPP_ACCESS_TOKEN')
        if missing:
            raise ValueError(f"Missing configuration: {', '.join(missing)}")


def verify_signature(payload: bytes, signature_header: str) -> bool:
    """Vérifie la signature HMAC envoyée dans les en-têtes POST"""
    logger.debug(f"Verifying signature header: {signature_header}")
    if not signature_header:
        logger.error('No signature header provided')
        return False

    # Détecter SHA256 ou SHA1
    if signature_header.startswith('sha256='):
        algo = hashlib.sha256
        logger.debug('Using SHA256 for HMAC verification')
        received_sig = signature_header.split('=', 1)[1]
    elif signature_header.startswith('sha1='):
        algo = hashlib.sha1
        logger.debug('Using SHA1 for HMAC verification')
        received_sig = signature_header.split('=', 1)[1]
    else:
        logger.error('Invalid signature header format')
        return False

    expected_sig = hmac.new(Config.APP_SECRET, payload, digestmod=algo).hexdigest()
    valid = hmac.compare_digest(received_sig, expected_sig)
    if not valid:
        logger.debug(f'Received signature: {received_sig}')
        logger.debug(f'Expected signature: {expected_sig}')
    return valid

@app.route('/webhook', methods=['GET'])
def webhook_verify():
    """Validation initiale du webhook"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    logger.debug(f"Webhook verification attempt - mode: {mode}, received token: {token}")

    if mode == 'subscribe' and token == Config.VERIFY_TOKEN:
        logger.info('Webhook verified successfully')
        return challenge, 200

    logger.warning(f'Webhook verification failed - expected token: {Config.VERIFY_TOKEN}')
    return 'Verification failed', 403

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Gestion des requêtes entrantes"""
    # Lire le payload brut en premier
    payload = request.get_data()
    logger.debug(f"Raw payload bytes: {payload}")
    # Récupérer la signature (SHA-256 ou SHA-1)
    signature = request.headers.get('X-Hub-Signature-256') or request.headers.get('X-Hub-Signature')
    logger.debug(f"Header signature: {signature}")

    if not verify_signature(payload, signature):
        logger.warning('Unauthorized access - invalid HMAC signature')
        return jsonify(error='Access denied'), 403

    try:
        data = json.loads(payload)
        logger.info(f'Received payload JSON: {json.dumps(data)}')

        # TODO: traiter le message WhatsApp
        return jsonify(status='Message processed'), 200

    except Exception as e:
        logger.error('Error processing incoming message', exc_info=True)
        return jsonify(error='Server error'), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de vérification de santé"""
    try:
        client = MongoClient(
            Config.MONGO_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=2000
        )
        client.admin.command('ping')
        return jsonify(
            status='healthy',
            database='connected',
            timestamp=datetime.utcnow().isoformat()
        ), 200

    except Exception as e:
        logger.error(f'MongoDB health check failed: {e}')
        return jsonify(
            status='unhealthy',
            database='disconnected',
            error=str(e)
        ), 500

if __name__ == '__main__':
    Config.validate()
    logger.info(f'Starting server on port {Config.PORT}')
    serve(app, host='0.0.0.0', port=Config.PORT)
