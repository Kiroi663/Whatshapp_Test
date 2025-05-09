import os
import hmac
import hashlib
import json
import logging
import re
import time
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
from waitress import serve
import requests
import offreBot

# ---------- Logging ----------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('bot_debug.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ---------- Flask App ----------
app = Flask(__name__)

# ---------- Config ----------
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

# ---------- Utils ----------
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
        resp = requests.post(Config.BASE_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error(f"Error send: {resp.text}")
    except Exception as e:
        logger.error(f"send error: {e}")

# ---------- State ----------
user_states = {}

def reset_state(user: str):
    user_states.pop(user, None)

# ---------- Templates ----------
def text_message(text: str) -> dict:
    return {"type": "text", "text": {"body": text}}

# ---------- Main Menu as List ----------
def start_flow(user: str):
    reset_state(user)
    rows = [
        {"id": "BROWSE", "title": "Parcourir les offres", "description": ""},
        {"id": "FAVORITES", "title": "Mes favoris", "description": ""}
    ]
    payload = {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "🌟 Bienvenue sur JobBot! Choisissez une action :"},
            "action": {
                "button": "Voir options",
                "sections": [{"title": "Menu", "rows": rows}]
            }
        }
    }
    send_whatsapp(user, payload)
    user_states[user] = {"state": "MAIN_MENU"}

# ---------- Category Listing ----------
def show_categories_page(user: str, page: int = 0):
    start = page * ROWS_PER_PAGE
    end = start + ROWS_PER_PAGE
    rows = []
    for i in range(start, min(end, len(CATEGORIES))):
        raw = CATEGORIES[i]
        title = raw if len(raw) <= 24 else raw[:21] + '...'
        rows.append({"id": f"CAT_{i}", "title": title, "description": ""})
    if page > 0:
        rows.append({"id": f"CAT_PAGE_{page-1}", "title": "◀️ Précédent", "description": ""})
    if end < len(CATEGORIES):
        rows.append({"id": f"CAT_PAGE_{page+1}", "title": "Suivant ▶️", "description": ""})
    rows.append({"id": "MAIN_MENU", "title": "🔙 Retour au menu", "description": ""})
    payload = {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "Choisissez une catégorie :"},
            "action": {"button": "Voir catégories", "sections": [{"title": "Catégories", "rows": rows}]}  
        }
    }
    send_whatsapp(user, payload)
    user_states[user] = {"state": "CATEGORY_SELECTION", "cat_page": page}

# ---------- Show Favorites ----------
def show_favorites(user: str):
    favs = list(favs_col.find({"user": user}))
    if not favs:
        send_whatsapp(user, text_message("Vous n'avez pas de favoris."))
    else:
        for fav in favs:
            send_whatsapp(user, text_message(f"⭐ {fav.get('title')} - {fav.get('url')}"))
    send_whatsapp(user, {"type": "text", "text": {"body": "🔙 Tapez /start pour revenir au menu."}})
    reset_state(user)

# ---------- Jobs Listing ----------
def send_jobs_page(user: str, category: str, page: int = 0):
    cat_name = CATEGORIES[int(category)]
    query = {"category": cat_name}
    total = jobs_col.count_documents(query)
    per = ROWS_PER_PAGE
    jobs = list(jobs_col.find(query).sort("created_at", -1).skip(page * per).limit(per))
    if not jobs:
        send_whatsapp(user, text_message("Aucune offre disponible."))
        return
    for job in jobs:
        msg = f"📌 {job.get('title')}\n🏢 {job.get('company')}\n📍 {job.get('location')}\n🔗 {job.get('url')}"
        send_whatsapp(user, text_message(msg))
        time.sleep(0.3)
    # navigation via buttons
    buttons = []
    if page > 0:
        buttons.append({"type": "reply", "reply": {"id": f"PAGE_{category}_{page-1}", "title": "◀️ Précédent"}})
    if (page + 1) * per < total:
        buttons.append({"type": "reply", "reply": {"id": f"PAGE_{category}_{page+1}", "title": "Suivant ▶️"}})
    buttons.append({"type": "reply", "reply": {"id": "MAIN_MENU", "title": "🔙 Menu"}})
    send_whatsapp(user, {"type": "interactive", "interactive": {"type": "button", "body": {"text": f"Page {page+1}"}, "action": {"buttons": buttons}}})
    user_states[user] = {"state": "BROWSING", "category": category, "page": page}

# ---------- Handlers ----------
def handle_interactive(user: str, inter: dict):
    itype = inter.get("type")
    if itype == "list_reply":
        sel = inter["list_reply"]["id"]
        if sel == "BROWSE":
            show_categories_page(user, 0)
        elif sel == "FAVORITES":
            show_favorites(user)
        elif sel.startswith("CAT_PAGE_"):
            page = int(sel.split("_")[2])
            show_categories_page(user, page)
        elif sel.startswith("CAT_"):
            idx = int(sel.split("_")[1])
            send_jobs_page(user, str(idx), 0)
        elif sel == "MAIN_MENU":
            start_flow(user)

# ---------- Webhooks ----------
@app.route('/webhook', methods=['GET'])
def webhook_verify():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == Config.VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return "Forbidden", 403

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    try:
        pkt = request.get_data()
        if not verify_signature(pkt, request.headers.get('X-Hub-Signature-256', '')):
            return jsonify({"status": "invalid signature"}), 403
        data = request.json
        for e in data.get('entry', []):
            for c in e.get('changes', []):
                for m in c.get('value', {}).get('messages', []):
                    if m.get('type') == 'interactive':
                        handle_interactive(normalize_number(m['from']), m['interactive'])
                    else:
                        # ignore any user text replies
                        pass
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"webhook error: {e}")
        return jsonify({"status": "error"}), 500

# ---------- Main ----------
if __name__ == '__main__':
    Config.validate()
    jobs_col.update_many({'category': 'Rouder'}, {'$set': {'category': 'Remote'}})
    serve(app, host='0.0.0.0', port=Config.PORT)
