import os
import hmac
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
import offreBot

app = Flask(__name__)

# Configuration améliorée
class Config:
    WEBHOOK_SECRET = ("claudelAI223").encode('utf-8')
    MONGO_URI = offreBot.MONGO_URI
    PORT = int(os.getenv("PORT", 10000))

    # Validation des paramètres
    @classmethod
    def validate(cls):
        if not cls.WEBHOOK_SECRET:
            raise ValueError("WEBHOOK_SECRET manquant")
        if not cls.MONGO_URI:
            raise ValueError("MONGO_URI manquant")

# Initialisation de la base de données
db_client = MongoClient(
    Config.MONGO_URI,
    tls=True,
    tlsCAFile=certifi.where()
)
db = db_client["job_bot"]

def verify_signature(request):
    """Vérification robuste de la signature"""
    try:
        signature_header = request.headers.get('X-Hub-Signature-256', '')
        if not signature_header.startswith('sha256='):
            app.logger.error("Format de signature invalide")
            return False
            
        received_signature = signature_header.split('=')[1]
        generated_signature = hmac.new(
            Config.WEBHOOK_SECRET,
            request.get_data(),  # Utilisation des données brutes
            digestmod=hashlib.sha256
        ).hexdigest()

        app.logger.debug(f"Signature reçue: {received_signature}")
        app.logger.debug(f"Signature générée: {generated_signature}")
        
        return hmac.compare_digest(received_signature, generated_signature)
        
    except Exception as e:
        app.logger.error(f"Erreur de vérification: {str(e)}")
        return False

@app.route('/webhook', methods=['GET'])
def webhook_verification():
    """Validation du webhook"""
    try:
        if (request.args.get('hub.mode') == 'subscribe' and 
            request.args.get('hub.verify_token') == Config.WEBHOOK_SECRET.decode()):
            return request.args['hub.challenge'], 200
    except Exception as e:
        app.logger.error(f"Erreur de validation: {str(e)}")
    return "Échec de validation", 403

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Gestion des requêtes WhatsApp"""
    if not verify_signature(request):
        app.logger.warning("Requête non autorisée")
        return jsonify(error="Signature invalide"), 403

    try:
        data = request.json
        entry = data['entry'][0]['changes'][0]['value']
        
        # Gestion des messages
        if 'messages' in entry:
            message = entry['messages'][0]
            return process_message(message)
            
        return jsonify(status="ok"), 200

    except Exception as e:
        app.logger.error(f"Erreur de traitement: {str(e)}")
        return jsonify(error="Erreur serveur"), 500

def process_message(message):
    """Traitement des messages entrants"""
    user_id = message['from']
    content = message['text']['body'].lower()
    
    # Enregistrement de l'activité
    db.users.update_one(
        {'user_id': user_id},
        {'$set': {'last_active': datetime.utcnow()}},
        upsert=True
    )

    # Réponse dynamique
    responses = {
        '/start': send_welcome,
        '/menu': show_menu,
        '/help': show_help
    }
    
    handler = responses.get(content.split()[0], handle_unknown)
    return handler(user_id)

def send_welcome(user_id):
    """Message de bienvenue interactif"""
    return jsonify({
        "messaging_product": "whatsapp",
        "to": user_id,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "👋 Bienvenue sur JobBot!"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "menu_jobs", "title": "📁 Offres"}},
                    {"type": "reply", "reply": {"id": "menu_help", "title": "❓ Aide"}}
                ]
            }
        }
    }), 200

if __name__ == '__main__':
    Config.validate()
    app.run(host='0.0.0.0', port=Config.PORT, debug=False)
