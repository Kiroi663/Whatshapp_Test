import os
import hmac
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
import offreBot

app = Flask(__name__)

# Configuration
CONFIG = {
    "WA_PHONE_ID": offreBot.WA_PHONE_ID,
    "WA_ACCESS_TOKEN": offreBot.WA_ACCESS_TOKEN,
    "WEBHOOK_SECRET": ("claudelAI223").encode('utf-8'),  # Encodé en bytes
    "MONGO_URI": offreBot.MONGO_URI,
    "PORT": int(os.getenv("PORT", 10000))
}

class WhatsAppJobBot:
    def __init__(self):
        self.db_client = MongoClient(
            CONFIG["MONGO_URI"],
            tls=True,
            tlsCAFile=certifi.where()
        )
        self.db = self.db_client["job_bot_db"]
        self.jobs = self.db["jobs"]
        self.users = self.db["users"]

    def verify_signature(self, request):
        """Vérifie la signature du webhook WhatsApp"""
        signature_header = request.headers.get('X-Hub-Signature-256', '')
        if not signature_header:
            app.logger.error("Missing X-Hub-Signature-256 header")
            return False
            
        sha_name, signature = signature_header.split('=')
        if sha_name != 'sha256':
            app.logger.error(f"Unsupported signature method: {sha_name}")
            return False

        # Calcul de la signature attendue
        mac = hmac.new(CONFIG["WEBHOOK_SECRET"], msg=request.data, digestmod=hashlib.sha256)
        expected_signature = mac.hexdigest()

        # Comparaison sécurisée des signatures
        return hmac.compare_digest(signature, expected_signature)

# Initialize bot
bot = WhatsAppJobBot()

@app.route('/webhook', methods=['GET'])
def webhook_verification():
    """Endpoint de vérification du webhook"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == CONFIG["WEBHOOK_SECRET"].decode('utf-8'):
        app.logger.info("Webhook verified successfully")
        return challenge, 200
    
    app.logger.error("Webhook verification failed")
    return "Verification failed", 403

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    """Endpoint principal pour les webhooks"""
    if not bot.verify_signature(request):
        app.logger.warning("Invalid request signature")
        return jsonify({"status": "invalid signature"}), 403

    try:
        data = request.json
        app.logger.debug(f"Received webhook data: {data}")
        
        # Traitement de base pour confirmer la réception
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        app.logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "whatsapp-job-bot"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=CONFIG["PORT"], debug=True)
