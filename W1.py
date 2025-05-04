import os
import hmac
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
import logging
import offreBot

app = Flask(__name__)

# Configuration du logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class Config:
    # Utilisation directe des variables d'environnement
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    WEBHOOK_SECRET = ("claudelAI223").encode('utf-8')
    MONGO_URI = offreBot.MONGO_URI
    PORT = int(os.getenv("PORT", 10000))

    @classmethod
    def validate(cls):
        required = {
            "WA_PHONE_ID": cls.WA_PHONE_ID,
            "WA_ACCESS_TOKEN": cls.WA_ACCESS_TOKEN,
            "MONGO_URI": cls.MONGO_URI
        }
        for name, value in required.items():
            if not value:
                raise ValueError(f"Configuration manquante: {name}")

def verify_signature(request):
    """Vérification améliorée de la signature avec logging"""
    signature_header = request.headers.get('X-Hub-Signature-256', '')
    logger.debug(f"Signature reçue: {signature_header}")
    
    if not signature_header.startswith('sha256='):
        logger.error("Format de signature invalide")
        return False
        
    received_signature = signature_header.split('=')[1]
    payload = request.get_data()
    
    # Génération de la signature attendue
    generated_signature = hmac.new(
        Config.WEBHOOK_SECRET,
        payload,
        digestmod=hashlib.sha256
    ).hexdigest()

    logger.debug(f"Signature générée: {generated_signature}")
    
    return hmac.compare_digest(received_signature, generated_signature)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Gestionnaire de webhook avec meilleure gestion des erreurs"""
    if not verify_signature(request):
        logger.warning("Échec de vérification de la signature")
        return jsonify(error="Signature invalide"), 403

    try:
        data = request.get_json()
        logger.debug(f"Données reçues: {data}")
        
        # Validation de la structure des données
        if not all(key in data for key in ['entry']):
            logger.error("Structure de données invalide")
            return jsonify(error="Données malformées"), 400
            
        # Traitement du premier entry/changes
        entry = data['entry'][0]['changes'][0]['value']
        
        if 'messages' in entry:
            message = entry['messages'][0]
            logger.info(f"Message reçu de {message['from']}")
            return jsonify(status="Message traité"), 200
            
        return jsonify(status="Événement non traité"), 200

    except Exception as e:
        logger.error(f"Erreur de traitement: {str(e)}", exc_info=True)
        return jsonify(error="Erreur serveur"), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    })

if __name__ == '__main__':
    Config.validate()
    
    # Vérification de la connexion MongoDB
    try:
        MongoClient(Config.MONGO_URI, tls=True, tlsCAFile=certifi.where()).server_info()
    except Exception as e:
        logger.error(f"Erreur de connexion MongoDB: {str(e)}")
        raise
    
    app.run(host='0.0.0.0', port=Config.PORT, debug=False)
