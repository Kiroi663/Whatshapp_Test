import os
import hmac
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
import logging
import offreBot

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class Config:
    # Configuration MongoDB améliorée
    MONGO_URI = offreBot.MONGO_URI
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    WEBHOOK_SECRET = ("claudelAI223").encode('utf-8')
    PORT = int(os.getenv("PORT", 10000))

    @classmethod
    def validate(cls):
        required_params = {
            "MONGO_URI": cls.MONGO_URI,
            "WA_PHONE_ID": cls.WA_PHONE_ID,
            "WA_ACCESS_TOKEN": cls.WA_ACCESS_TOKEN
        }
        for name, value in required_params.items():
            if not value:
                raise ValueError(f"Paramètre manquant: {name}")

def get_mongo_client():
    """Crée une connexion MongoDB sécurisée avec timeout"""
    return MongoClient(
        Config.MONGO_URI,
        tls=True,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=3000,
        socketTimeoutMS=3000
    )

def verify_signature(request):
    """Vérification avancée de signature avec logging"""
    signature_header = request.headers.get('X-Hub-Signature-256', '')
    
    if not signature_header.startswith('sha256='):
        logger.error("Format de signature invalide")
        return False
    
    received_signature = signature_header.split('=')[1]
    generated_signature = hmac.new(
        Config.WEBHOOK_SECRET,
        request.get_data(),
        digestmod=hashlib.sha256
    ).hexdigest()

    logger.debug(f"Signature reçue: {received_signature}")
    logger.debug(f"Signature générée: {generated_signature}")
    
    return hmac.compare_digest(received_signature, generated_signature)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    if not verify_signature(request):
        logger.warning("Tentative d'accès non autorisée")
        return jsonify(error="Accès refusé"), 403

    try:
        data = request.get_json()
        logger.info(f"Reçu: {data}")
        
        # Traitement de base
        return jsonify(status="OK"), 200

    except Exception as e:
        logger.error(f"Erreur: {str(e)}", exc_info=True)
        return jsonify(error="Erreur serveur"), 500

@app.route('/health')
def health_check():
    try:
        # Vérification connexion MongoDB
        with get_mongo_client() as client:
            client.admin.command('ping')
        return jsonify(
            status="healthy",
            mongo="connected",
            timestamp=datetime.utcnow().isoformat()
        ), 200
    except Exception as e:
        logger.error(f"Erreur MongoDB: {str(e)}")
        return jsonify(
            status="unhealthy",
            mongo="disconnected",
            error=str(e)
        ), 500

if __name__ == '__main__':
    Config.validate()
    
    # Configuration serveur de production
    from waitress import serve
    logger.info(f"Démarrage du serveur sur le port {Config.PORT}")
    serve(app, host="0.0.0.0", port=Config.PORT)
