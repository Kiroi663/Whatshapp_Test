import os
import hmac
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
import offreBot

app = Flask(__name__)

class Config:
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    WEBHOOK_SECRET = "claudelAI223".encode('utf-8')
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
    """Vérifie la signature du webhook WhatsApp"""
    signature_header = request.headers.get('X-Hub-Signature-256', '')
    if not signature_header.startswith('sha256='):
        app.logger.error("Format de signature invalide")
        return False
        
    received_signature = signature_header.split('=')[1]
    generated_signature = hmac.new(
        Config.WEBHOOK_SECRET,
        request.get_data(),
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(received_signature, generated_signature)

class WhatsAppClient:
    def __init__(self):
        self.base_url = f"https://graph.facebook.com/v18.0/{Config.WA_PHONE_ID}"
        self.headers = {
            "Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

    def send_message(self, payload):
        app.logger.info(f"Envoi WhatsApp à {payload.get('to')}")
        return True

# Initialisation
whatsapp = WhatsAppClient()
db_client = MongoClient(Config.MONGO_URI, tls=True, tlsCAFile=certifi.where())
db = db_client["job_bot"]

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    if not verify_signature(request):
        return jsonify(error="Signature invalide"), 403

    try:
        data = request.json
        entry = data['entry'][0]['changes'][0]['value']
        
        if 'messages' in entry:
            message = entry['messages'][0]
            response = process_message(message)
            whatsapp.send_message(response)
            
            return jsonify(status="message envoyé"), 200
            
    except Exception as e:
        app.logger.error(f"Erreur: {str(e)}")
        return jsonify(error="Erreur serveur"), 500

def process_message(message):
    return {
        "messaging_product": "whatsapp",
        "to": message['from'],
        "type": "text",
        "text": {"body": "Merci pour votre message!"}
    }

if __name__ == '__main__':
    Config.validate()
    app.run(host='0.0.0.0', port=Config.PORT, debug=False)
