import os
import hmac
import hashlib
import json
import logging
import re
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
from waitress import serve
import requests
import offreBot

# ---------- Configuration Logging ----------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('bot_debug.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ---------- Flask App ----------
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

    @classmethod
    def validate(cls):
        required = ['MONGO_URI', 'WA_PHONE_ID', 'WA_ACCESS_TOKEN']
        missing = [k for k in required if not getattr(cls, k)]
        if missing:
            raise ValueError(f"Configuration manquante: {', '.join(missing)}")

# ---------- Database ----------
mongo = MongoClient(Config.MONGO_URI, tlsCAFile=certifi.where())
db = mongo.job_database
jobs_col = db.christ  # Collection validée
favs_col = db.user_favorites

# ---------- Constantes ----------
CATEGORIES = [
    "Informatique / IT",
    "Finance / Comptabilité",
    "Communication / Marketing",
    "Conseil / Stratégie",
    "Transport / Logistique",
    "Ingénierie / BTP",
    "Santé / Médical",
    "Éducation / Formation",
    "Ressources humaines",
    "Droit / Juridique",
    "Environnement",
    "Alternance / Stage",
    "Remote",
    "Autre"
]

# ---------- Utilitaires ----------
def normalize_number(number: str) -> str:
    number = number.lstrip('+')
    if not re.match(r'^\d{10,15}$', number):
        raise ValueError("Format de numéro invalide")
    return f"+{number}"

def verify_signature(payload: bytes, signature: str) -> bool:
    digest = hmac.new(Config.APP_SECRET, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature)

def create_message(to: str, content: dict) -> dict:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        **content
    }

# ---------- Gestion des états ----------
user_states = {}

def reset_state(user: str):
    user_states.pop(user, None)

# ---------- Templates de messages ----------
def text_message(text: str) -> dict:
    return {"type": "text", "text": {"body": text}}

def list_message(header: str, rows: list) -> dict:
    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": header},
            "action": {
                "button": "Options",
                "sections": [{
                    "title": "Catégories",
                    "rows": rows[:10]
                }]
            }
        }
    }

# ---------- Logique métier ----------
def start_flow(user: str):
    reset_state(user)
    message = "🌟 Bienvenue sur JobBot! Choisissez une action :"
    buttons = [
        {"type": "reply", "reply": {"id": "BROWSE", "title": "Parcourir les offres"}},
        {"type": "reply", "reply": {"id": "FAVORITES", "title": "Mes favoris"}}
    ]
    send_whatsapp(user, {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": message},
            "action": {"buttons": buttons}
        }
    })
    user_states[user] = {"state": "MAIN_MENU"}

def show_categories(user: str):
    rows = [{"id": f"CAT_{i}", "title": cat} for i, cat in enumerate(CATEGORIES)]
    send_whatsapp(user, list_message("Choisissez une catégorie :", rows))
    user_states[user] = {"state": "CATEGORY_SELECTION"}

def send_jobs_page(user: str, category: str, page: int = 0):
    try:
        category_name = CATEGORIES[int(category)]
        query = {"category": category_name}
        total = jobs_col.count_documents(query)
        per_page = 5
        
        jobs = list(jobs_col.find(query)
            .sort("created_at", -1)
            .skip(page * per_page)
            .limit(per_page))
        
        if not jobs:
            send_whatsapp(user, text_message("Aucune offre disponible dans cette catégorie"))
            return

        for job in jobs:
            response = f"""📌 {job.get('title', 'Sans titre')}
🏢 {job.get('company', 'Entreprise non spécifiée')}
📍 {job.get('location', 'Localisation non précisée')}
🔗 {job.get('url', '#')}"""
            send_whatsapp(user, text_message(response))
            time.sleep(0.5)

        # Navigation
        buttons = []
        if page > 0:
            buttons.append({
                "type": "reply",
                "reply": {"id": f"PAGE_{category}_{page-1}", "title": "◀️ Précédent"}
            })
        
        if (page + 1) * per_page < total:
            buttons.append({
                "type": "reply",
                "reply": {"id": f"PAGE_{category}_{page+1}", "title": "Suivant ▶️"}
            })
        
        buttons.append({
            "type": "reply", 
            "reply": {"id": "BACK_CAT", "title": "🔙 Catégories"}
        })
        
        send_whatsapp(user, {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": f"Page {page+1}"},
                "action": {"buttons": buttons}
            }
        })
        
        user_states[user] = {
            "state": "BROWSING",
            "category": category,
            "page": page
        }

    except Exception as e:
        logger.error(f"Erreur d'envoi des offres : {str(e)}")
        send_whatsapp(user, text_message("Une erreur est survenue"))

# ---------- Gestion des webhooks ----------
@app.route('/webhook', methods=['GET'])
def webhook_verify():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == Config.VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return "Forbidden", 403

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    try:
        payload = request.get_data()
        if not verify_signature(payload, request.headers.get('X-Hub-Signature-256', '')):
            return jsonify({"status": "invalid signature"}), 403
        
        data = request.json
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                for message in change.get('value', {}).get('messages', []):
                    process_message(message)
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Erreur webhook : {str(e)}")
        return jsonify({"status": "error"}), 500

def process_message(msg: dict):
    try:
        user = normalize_number(msg['from'])
        message_type = msg.get('type')
        
        if message_type == 'text':
            handle_text(user, msg['text']['body'].strip())
        elif message_type == 'interactive':
            handle_interactive(user, msg['interactive'])
            
    except Exception as e:
        logger.error(f"Erreur traitement message : {str(e)}")

# ---------- Gestion des messages texte ----------
def handle_text(user: str, text: str):
    text = text.upper()
    state = user_states.get(user, {}).get("state")
    
    logger.debug(f"Traitement texte: {text} | State: {state}")
    
    if text in ["/START", "START"]:
        start_flow(user)
    elif state == "MAIN_MENU":
        if text == "BROWSE":
            show_categories(user)
        elif text == "FAVORITES":
            show_favorites(user)
    elif state == "BROWSING":
        if text.startswith("PAGE_"):
            _, category, page = text.split("_")
            send_jobs_page(user, category, int(page))
        elif text == "BACK_CAT":
            show_categories(user)
    else:
        start_flow(user)

# ---------- Gestion des interactions ----------
def handle_interactive(user: str, interactive: dict):
    itype = interactive.get("type")
    
    if itype == "list_reply":
        selected_id = interactive["list_reply"]["id"]
        if selected_id.startswith("CAT_"):
            category_index = int(selected_id.split("_")[1])
            send_jobs_page(user, str(category_index), 0)
            
    elif itype == "button_reply":
        button_id = interactive["button_reply"]["id"]
        handle_text(user, button_id)

# ---------- Envoi WhatsApp ----------
def send_whatsapp(to: str, content: dict):
    try:
        payload = create_message(to, content)
        headers = {
            "Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        response = requests.post(Config.BASE_URL, headers=headers, json=payload)
        
        if response.status_code != 200:
            logger.error(f"Erreur envoi: {response.text}")
            
    except Exception as e:
        logger.error(f"Erreur send_whatsapp: {str(e)}")

# ---------- Lancement ----------
if __name__ == '__main__':
    Config.validate()
    
    # Nettoyage initial des données
    jobs_col.update_many(
        {"category": "Rouder"},
        {"$set": {"category": "Remote"}}
    )
    
    # Démarrage serveur
    serve(app, host='0.0.0.0', port=Config.PORT)
