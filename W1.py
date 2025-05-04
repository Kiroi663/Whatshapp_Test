import os
import hmac
import hashlib
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
    # Configuration améliorée avec validation
    WEBHOOK_SECRET = ('claudelAI223').strip().encode('utf-8')
    MONGO_URI = offreBot.MONGO_URI
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    PORT = int(os.getenv('PORT', 10000))

    @classmethod
    def validate(cls):
        missing = [name for name, value in [
            ('WEBHOOK_SECRET', cls.WEBHOOK_SECRET),
            ('MONGO_URI', cls.MONGO_URI),
            ('WA_PHONE_ID', cls.WA_PHONE_ID),
            ('WA_ACCESS_TOKEN', cls.WA_ACCESS_TOKEN)
        ] if not value]
        
        if missing:
            raise ValueError(f'Paramètres manquants: {", ".join(missing)}')

def verify_signature(request):
    """Vérification robuste de la signature HMAC"""
    signature_header = request.headers.get('X-Hub-Signature-256', '')
    
    if not signature_header.startswith('sha256='):
        logger.error("Format de signature incorrect")
        return False
    
    received_signature = signature_header.split('=')[1]
    payload = request.get_data()
    
    # Génération de la signature attendue
    expected_signature = hmac.new(
        Config.WEBHOOK_SECRET,
        payload,
        digestmod=hashlib.sha256
    ).hexdigest()

    logger.debug(f"Signature reçue: {received_signature}")
    logger.debug(f"Signature générée: {expected_signature}")
    
    return hmac.compare_digest(received_signature, expected_signature)

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    """Validation initiale du webhook"""
    try:
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if mode == 'subscribe' and token == Config.WEBHOOK_SECRET.decode():
            logger.info("Validation du webhook réussie")
            return challenge, 200
            
    except Exception as e:
        logger.error(f"Erreur de validation: {str(e)}")
    
    logger.warning("Échec de la validation du webhook")
    return "Échec de vérification", 403

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Gestion des requêtes WhatsApp"""
    if not verify_signature(request):
        logger.warning("Accès non autorisé - Signature invalide")
        return jsonify(error="Accès refusé"), 403

    try:
        data = request.get_json()
        logger.debug(f"Données reçues: {data}")
        
        # Traitement basique des messages
        if 'entry' in data and 'changes' in data['entry'][0]['value']:
            return jsonify(status="Message reçu"), 200
            
        return jsonify(status="Format non supporté"), 400

    except Exception as e:
        logger.error(f"Erreur de traitement: {str(e)}", exc_info=True)
        return jsonify(error="Erreur interne"), 500

@app.route('/health')
def health_check():
    """Endpoint de santé avec vérification MongoDB"""
    try:
        client = MongoClient(
            Config.MONGO_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=2000
        )
        client.admin.command('ping')
        return jsonify(
            status="healthy",
            mongo="connecté",
            timestamp=datetime.utcnow().isoformat()
        ), 200
    except Exception as e:
        logger.error(f"Erreur MongoDB: {str(e)}")
        return jsonify(
            status="unhealthy",
            mongo="déconnecté",
            error=str(e)
        ), 500

if __name__ == '__main__':
    Config.validate()
    logger.info(f"Démarrage du serveur sur le port {Config.PORT}")
    serve(app, host='0.0.0.0', port=Config.PORT)
