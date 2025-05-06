import os
import hmac
import hashlib
import json
import logging
import random
import time
import threading
import re
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
from waitress import serve
import requests
import offreBot

# ---------- Initialisation ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# ---------- Configuration ----------
class Config:
    VERIFY_TOKEN = 'claudelAI223'
    APP_SECRET = b'7c61b31a0530bc3cc28f632a9b3e32be'
    MONGO_URI = offreBot.MONGO_URI
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    TEST_NUMBER = offreBot.TEST_NUMBER
    PORT = int(os.getenv('PORT', 10000))
    BASE_URL = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages"
    TELEGRAM_DEMO_URL = "https://t.me/yourchannel/video123"

    @classmethod
    def validate(cls):
        required = {
            'MONGO_URI': cls.MONGO_URI,
            'WA_PHONE_ID': cls.WA_PHONE_ID,
            'WA_ACCESS_TOKEN': cls.WA_ACCESS_TOKEN,
            'TEST_NUMBER': cls.TEST_NUMBER  # Nouvelle validation
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Configuration manquante: {', '.join(missing)}")

# ---------- Database ----------
mongo = MongoClient(Config.MONGO_URI, tls=True, tlsCAFile=certifi.where())
db = mongo['job_database']
jobs_col = db['jobs']
favs_col = db['user_favorites']

# ---------- Templates ----------
JOB_TEMPLATES = [
    "📌 *{title}*\n🏢 *{company}*\n📍 {location}\n\n{description}\n\n🔗 {url}",
    "🚀 Opportunité : *{title}*\n📌 Entreprise : *{company}*\n📍 {location}\n\n{description}\n📎 {url}",
    "🎯 Poste : *{title}*\n🏭 Employeur : *{company}*\n🌍 {location}\n\n📝 Description :\n{description}\n🌐 {url}"
]

CATEGORIES = [
    "Informatique / IT", "Finance / Comptabilité", "Communication / Marketing",
    "Conseil / Stratégie", "Transport / Logistique", "Ingénierie / BTP",
    "Santé / Médical", "Éducation / Formation", "Ressources humaines",
    "Droit / Juridique", "Environnement", "Alternance / Stage", "Remote", "Autre"
]

# ---------- Core Functions ----------
def validate_phone_number(number: str) -> bool:
    """Valide le format international du numéro"""
    return bool(re.match(r'^\+\d{10,15}$', number))

def verify_signature(payload: bytes, signature_header: str) -> bool:
    """Valide la signature HMAC du webhook"""
    if not signature_header or not signature_header.startswith('sha256='):
        return False
    
    secret = Config.APP_SECRET
    received_sig = signature_header.split('sha256=')[1].strip()
    expected_sig = hmac.new(secret, msg=payload, digestmod=hashlib.sha256).hexdigest()
    
    return hmac.compare_digest(received_sig, expected_sig)

def create_message_payload(to: str, content: dict) -> dict:
    """Crée le payload complet avec validation"""
    if not validate_phone_number(to):
        raise ValueError(f"Numéro invalide: {to}")
    
    return {
        "messaging_product": "whatsapp",
        "to": to,
        **content
    }

def create_interactive_content(text: str, buttons=None, sections=None) -> dict:
    """Crée le contenu interactif"""
    content = {
        "type": "interactive",
        "interactive": {
            "body": {"text": text},
            "action": {}
        }
    }

    if buttons:
        content["interactive"]["type"] = "button"
        content["interactive"]["action"]["buttons"] = []
        for btn in buttons:
            if 'url' in btn:
                content["interactive"]["action"]["buttons"].append({
                    "type": "cta_url",
                    "title": btn['title'],
                    "cta_url": {
                        "display_text": btn.get('display', btn['title']),
                        "url": btn['url']
                    }
                })
            else:
                content["interactive"]["action"]["buttons"].append({
                    "type": "reply",
                    "reply": {
                        "id": btn.get('id', btn['title'][0]),
                        "title": btn['title']
                    }
                })
    elif sections:
        content["interactive"]["type"] = "list"
        content["interactive"]["action"]["button"] = "Options"
        content["interactive"]["action"]["sections"] = sections
    
    return content

def send_whatsapp_message(to: str, text: str, buttons=None, sections=None) -> bool:
    """Envoie un message avec gestion robuste des erreurs"""
    try:
        if not validate_phone_number(to):
            logger.error(f"Numéro {to} invalide")
            return False

        content = {
            "type": "text",
            "text": {"body": text}
        } if not (buttons or sections) else create_interactive_content(text, buttons, sections)

        payload = create_message_payload(to, content)
        
        headers = {
            "Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        response = requests.post(Config.BASE_URL, headers=headers, json=payload)
        
        if not response.ok:
            error_msg = response.json().get('error', {}).get('message', '')
            logger.error(f"Échec d'envoi à {to}: {error_msg}")
            return False
            
        return True
    except Exception as e:
        logger.error(f"Erreur d'envoi à {to}: {str(e)}")
        return False

# ---------- Business Logic ----------
user_states = {}

def start_conversation(user: str):
    """Démarre une nouvelle conversation avec validation"""
    if not validate_phone_number(user):
        logger.error(f"Conversation non démarrée - numéro invalide: {user}")
        return

    welcome_msg = (
        "🌟 *Bienvenue sur JobFinder* 🌟\n\n"
        "Trouvez les meilleures opportunités d'emploi.\n\n"
        "Envoyez *MENU* ou cliquez ci-dessous."
    )
    
    send_whatsapp_message(
        user,
        welcome_msg,
        buttons=[{"title": "📋 Ouvrir le Menu", "id": "MENU"}]
    )
    user_states[user] = {"state": "MAIN_MENU"}

# ... (les autres fonctions business logiques restent similaires mais utilisent send_whatsapp_message)

def handle_favorites(user: str):
    """Gère les favoris avec validation du numéro"""
    if not validate_phone_number(user):
        logger.error(f"Consultation favoris impossible - numéro invalide: {user}")
        return

    favs = favs_col.find_one({"user_id": user}) or {"categories": []}
    
    if not favs["categories"]:
        send_whatsapp_message(user, "Vous n'avez aucune catégorie en favoris.")
        return
    
    jobs = list(jobs_col.find({"category": {"$in": favs["categories"]}}))
    
    if not jobs:
        send_whatsapp_message(user, "Aucune offre dans vos favoris.")
    else:
        send_jobs_page(user, jobs, "Vos Favoris")

def notify_new_jobs():
    """Notification des nouvelles offres avec validation des numéros"""
    while True:
        try:
            new_jobs = list(jobs_col.find({"is_notified": {"$ne": True}}))
            for job in new_jobs:
                if 'category' not in job:
                    continue
                    
                job.setdefault('url', 'https://emploicd.com/offre')
                job.setdefault('title', 'Nouvelle offre')
                job.setdefault('description', '')
                
                users = favs_col.find({"categories": job['category']})
                for user in users:
                    if not validate_phone_number(user['user_id']):
                        continue
                        
                    send_whatsapp_message(
                        user['user_id'],
                        "🚨 NOUVELLE OFFRE !\n" + random.choice(JOB_TEMPLATES).format(**job),
                        buttons=[{'title': '📌 Voir offre', 'url': job['url']}]
                    )
                    time.sleep(1)
                
                jobs_col.update_one(
                    {"_id": job['_id']}, 
                    {"$set": {"is_notified": True, "notified_at": datetime.utcnow()}}
                )
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"Erreur de notification: {str(e)}")
            time.sleep(300)

# ---------- Webhook Endpoints ----------
@app.route('/webhook', methods=['GET'])
def webhook_verify():
    """Validation du webhook WhatsApp"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == Config.VERIFY_TOKEN:
        logger.info("Webhook validé")
        return challenge, 200
    return 'Échec de validation', 403

@app.route('/webhook', methods=['POST'])
# Modifier la fonction webhook_receive pour logger les requêtes entrante
def webhook_receive():
    """Réception des messages avec validation de signature"""
    try:
        raw = request.get_data()
        logger.debug("Requête reçue:\n%s", raw.decode('utf-8'))
        
        if not verify_signature(raw, request.headers.get('X-Hub-Signature-256')):
            logger.warning("Signature invalide rejetée")
            return jsonify({"status": "signature invalide"}), 403

        data = request.get_json()
        logger.info("Payload JSON reçu: %s", json.dumps(data, indent=2))
        
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                for msg in change['value'].get('messages', []):
                    logger.debug(
                        "Message traité - From: %s | Type: %s | Contenu: %s",
                        msg.get('from'),
                        msg.get('type'),
                        msg.get('text', {}).get('body')
                    )
                    if not validate_phone_number(msg['from']):
                        logger.warning("Numéro invalide ignoré: %s", msg['from'])
                        continue
                    handle_message(msg)
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error("ERREUR WEBHOOK: %s", str(e), exc_info=True)
        return jsonify({"status": "error"}), 500

# Ajouter ce logging dans handle_message
def handle_message(msg: dict):
    """Traite un message entrant"""
    try:
        user = msg['from']
        text = extract_message_content(msg)
        logger.info("Nouveau message - From: %s | Text: %s", user, text)
        
        if not text or user not in user_states or text in ['/START', 'START', 'MENU']:
            logger.info("Démarrage nouvelle conversation pour: %s", user)
            return start_conversation(user)
            
        state = user_states[user].get('state', 'MAIN_MENU')
        logger.debug("État utilisateur: %s | Commande: %s", state, text)
        
        # ... reste du code inchangé ...
        
    except Exception as e:
        logger.error("ERREUR handle_message: %s", str(e), exc_info=True)
        send_whatsapp_message(user, "Erreur interne - Veuillez réessayer")

# Ajouter cette configuration de logging au début
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_debug.log'),
        logging.StreamHandler()
    ]
)

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de santé avec vrai test d'envoi"""
    try:
        # Test de base de données
        mongo.admin.command('ping')
        
        # Test WhatsApp avec un vrai numéro
        test_msg = {
            "type": "text",
            "text": {"body": "TEST"}
        }
        payload = create_message_payload(Config.TEST_NUMBER, test_msg)
        
        headers = {
            "Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(Config.BASE_URL, headers=headers, json=payload)
        
        if not response.ok:
            raise Exception(f"Erreur WhatsApp: {response.text}")
            
        return jsonify({
            "status": "healthy",
            "services": {
                "database": "ok",
                "whatsapp": "ok"
            }
        }), 200
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

# ---------- Main ----------
if __name__ == '__main__':
    Config.validate()
    
    # Démarrer le système de notification
    threading.Thread(target=notify_new_jobs, daemon=True).start()
    
    # Démarrer le serveur
    logger.info(f"Démarrage du serveur sur le port {Config.PORT}")
    serve(app, host='0.0.0.0', port=Config.PORT)
