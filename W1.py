import os
import hmac
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
import logging
from waitress import serve

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class Config:
    # Configuration dynamique avec variables d'environnement
    WEBHOOK_SECRET = ('claudelAI223').strip().encode('utf-8')
    MONGO_URI = offreBot.MONGO_URI
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    PORT = int(os.getenv('PORT', 10000))

    @classmethod
    def validate(cls):
        required = {
            'WHATSAPP_WEBHOOK_SECRET': cls.WEBHOOK_SECRET,
            'MONGODB_URI': cls.MONGO_URI,
            'WHATSAPP_PHONE_ID': cls.WA_PHONE_ID,
            'WHATSAPP_ACCESS_TOKEN': cls.WA_ACCESS_TOKEN
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f'Configuration manquante: {", ".join(missing)}')

def verify_signature(request):
    """Vérification améliorée de la signature avec gestion d'erreurs"""
    try:
        signature_header = request.headers.get('X-Hub-Signature-256', '')
        if not signature_header.startswith('sha256='):
            logger.error("Format d'en-tête de signature invalide")
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

    except Exception as e:
        logger.error(f"Erreur de vérification: {str(e)}")
        return False

@app.route('/webhook', methods=['GET'])
def webhook_verification():
    """Validation initiale du webhook"""
    try:
        if (request.args.get('hub.mode') == 'subscribe' and 
            request.args.get('hub.verify_token') == Config.WEBHOOK_SECRET.decode()):
            logger.info("Validation du webhook réussie")
            return request.args.get('hub.challenge'), 200
    except Exception as e:
        logger.error(f"Erreur lors de la validation: {str(e)}")
    
    logger.warning("Échec de la validation du webhook")
    return "Échec de vérification", 403

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Gestion des requêtes entrantes"""
    if not verify_signature(request):
        logger.warning("Accès non autorisé - Signature HMAC invalide")
        return jsonify(error="Accès refusé"), 403

    try:
        data = request.get_json()
        logger.info(f"Reçu: {data}")
        
        # Traiter le message WhatsApp ici
        return jsonify(status="Message traité"), 200

    except Exception as e:
        logger.error(f"Erreur de traitement: {str(e)}", exc_info=True)
        return jsonify(error="Erreur serveur"), 500

@app.route('/health')
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
            status="healthy",
            database="connected",
            timestamp=datetime.utcnow().isoformat()
        ), 200
    except Exception as e:
        logger.error(f"Erreur MongoDB: {str(e)}")
        return jsonify(
            status="unhealthy",
            database="disconnected",
            error=str(e)
        ), 500

if __name__ == '__main__':
    Config.validate()
    logger.info(f"Démarrage du serveur sur le port {Config.PORT}")
    serve(app, host='0.0.0.0', port=Config.PORT)
