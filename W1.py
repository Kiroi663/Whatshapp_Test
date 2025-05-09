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
    PORT = int(os.getenv('PORT', 10000))
    BASE_URL = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages"

    @classmethod
    def validate(cls):
        missing = [k for k in ['MONGO_URI', 'WA_PHONE_ID', 'WA_ACCESS_TOKEN'] if not getattr(cls, k)]
        if missing:
            raise ValueError(f"Missing config: {missing}")

# ---------- Database ----------
mongo = MongoClient(Config.MONGO_URI, tlsCAFile=certifi.where())
db = mongo.job_database
jobs_col = db.christ
favs_col = db.user_favorites

# ---------- Constants ----------
CATEGORIES = [
    "Informatique / IT","Finance / Comptabilité","Communication / Marketing",
    "Conseil / Stratégie","Transport / Logistique","Ingénierie / BTP",
    "Santé / Médical","Éducation / Formation","Ressources humaines",
    "Droit / Juridique","Environnement","Alternance / Stage","Remote","Autre"
]
ROWS_PER_PAGE = 5

# ---------- Utilities ----------
def normalize_number(num: str) -> str:
    n = num.lstrip('+')
    if not re.match(r'^\d{10,15}$', n):
        raise ValueError("Invalid number format")
    return f"+{n}"

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

def send_whatsapp(to: str, content: dict):
    try:
        payload = create_message(to, content)
        headers = {
            "Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        response = requests.post(Config.BASE_URL, headers=headers, json=payload)
        if response.status_code != 200:
            logger.error(f"Error sending message: {response.text}")
    except Exception as e:
        logger.error(f"send_whatsapp error: {e}")

# ---------- State Management ----------
user_states = {}

def reset_state(user: str):
    user_states.pop(user, None)

# ---------- Message Templates ----------
def text_message(text: str) -> dict:
    return {"type": "text", "text": {"body": text}}

# ---------- Category Listing (Interactive List) ----------
def show_categories_page(user: str, page: int = 0):
    start = page * ROWS_PER_PAGE
    end = start + ROWS_PER_PAGE
    rows = []
    # Build rows with truncated titles (max 24 chars)
    for i in range(start, min(end, len(CATEGORIES))):
        raw = CATEGORIES[i]
        title = raw if len(raw) <= 24 else raw[:21] + '...'
        rows.append({"id": f"CAT_{i}", "title": title, "description": ""})
    if page > 0:
        rows.append({"id": f"CAT_PAGE_{page-1}", "title": "◀️ Précédent", "description": ""})
    if end < len(CATEGORIES):
        rows.append({"id": f"CAT_PAGE_{page+1}", "title": "Suivant ▶️", "description": ""})
    rows.append({"id": "MAIN_MENU", "title": "🔙 Menu", "description": ""})

    payload = {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "Choisissez une catégorie :"},
            "action": {
                "button": "Voir options",
                "sections": [{"title": "Catégories", "rows": rows}]
            }
        }
    }
    send_whatsapp(user, payload)
    user_states[user] = {"state": "CATEGORY_SELECTION", "cat_page": page}

# ---------- Favorites ----------
def show_favorites(user: str):
    favs = list(favs_col.find({"user": user}))
    if not favs:
        send_whatsapp(user, text_message("Vous n'avez pas encore de favoris."))
    else:
        for fav in favs:
            send_whatsapp(user, text_message(f"⭐ {fav.get('title')} - {fav.get('url')}"))
    payload = {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Retour?"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "MAIN_MENU", "title": "🔙 Menu"}}
            ]}
        }
    }
    send_whatsapp(user, payload)
    user_states[user] = {"state": "MAIN_MENU"}

# ---------- Start Flow ----------
def start_flow(user: str):
    reset_state(user)
    payload = {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "🌟 Bienvenue sur JobBot!"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "BROWSE", "title": "Parcourir offres"}},
                {"type": "reply", "reply": {"id": "FAVORITES", "title": "Mes favoris"}}
            ]}
        }
    }
    send_whatsapp(user, payload)
    user_states[user] = {"state": "MAIN_MENU"}

# ---------- Webhook Endpoints ----------
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
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

# ---------- Message Processing ----------
def process_message(msg: dict):
    try:
        user = normalize_number(msg['from'])
        mtype = msg.get('type')
        if mtype == 'text':
            handle_text(user, msg['text']['body'].strip())
        elif mtype == 'interactive':
            handle_interactive(user, msg['interactive'])
    except Exception as e:
        logger.error(f"Process error: {e}")

# ---------- Text Handler ----------
def handle_text(user: str, text: str):
    cmd = text.upper()
    state = user_states.get(user, {}).get('state')
    logger.debug(f"TXT {cmd}|STATE {state}")
    if cmd in ['/START', 'START']:
        start_flow(user)
    elif state == 'MAIN_MENU':
        if cmd == 'BROWSE':
            show_categories_page(user, 0)
        elif cmd == 'FAVORITES':
            show_favorites(user)
    else:
        start_flow(user)

# ---------- Interactive Handler ----------
def handle_interactive(user: str, interactive: dict):
    itype = interactive.get('type')
    if itype == 'list_reply':
        sel_id = interactive['list_reply']['id']
        if sel_id == 'MAIN_MENU':
            start_flow(user)
        elif sel_id.startswith('CAT_PAGE_'):
            page = int(sel_id.split('_')[2])
            show_categories_page(user, page)
        elif sel_id.startswith('CAT_'):
            idx = int(sel_id.split('_')[1])
            send_jobs_page(user, str(idx), 0)
    elif itype == 'button_reply':
        button_id = interactive['button_reply']['id']
        handle_text(user, button_id)

# ---------- Send Jobs (Pagination Buttons) ----------
def send_jobs_page(user: str, category: str, page: int = 0):
    try:
        cat_name = CATEGORIES[int(category)]
        query = {'category': cat_name}
        total = jobs_col.count_documents(query)
        per_page = ROWS_PER_PAGE
        jobs = list(jobs_col.find(query).sort('created_at', -1).skip(page * per_page).limit(per_page))
        if not jobs:
            send_whatsapp(user, text_message('Aucune offre disponible.'))
            return
        for job in jobs:
            msg = f"📌 {job.get('title')}\n🏢 {job.get('company')}\n📍 {job.get('location')}\n🔗 {job.get('url')}"
            send_whatsapp(user, text_message(msg))
            time.sleep(0.5)
        buttons = []
        if page > 0:
            buttons.append({"type": "reply", "reply": {"id": f"PAGE_{category}_{page-1}", "title": "◀️ Précédent"}})
        if (page + 1) * per_page < total:
            buttons.append({"type": "reply", "reply": {"id": f"PAGE_{category}_{page+1}", "title": "Suivant ▶️"}})
        buttons.append({"type": "reply", "reply": {"id": "MAIN_MENU", "title": "🔙 Menu"}})
        payload = {"type": "interactive", "interactive": {"type": "button", "body": {"text": f"Page {page+1}"}, "action": {"buttons": buttons}}}
        send_whatsapp(user, payload)
        user_states[user] = {"state": "BROWSING", "category": category, "page": page}
    except Exception as e:
        logger.error(f"send_jobs_page error: {e}")

# ---------- Main Entrypoint ----------
if __name__ == '__main__':
    Config.validate()
    jobs_col.update_many({'category': 'Rouder'}, {'$set': {'category': 'Remote'}})
    serve(app, host='0.0.0.0', port=Config.PORT)
