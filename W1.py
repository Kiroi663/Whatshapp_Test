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

# ---------- Utilities ----------
def normalize_number(num: str) -> str:
    n = num.lstrip('+')
    if not re.match(r'^\d{10,15}$', n):
        raise ValueError("Invalid number format")
    formatted = f"+{n}"
    logger.debug(f"Normalized number: {formatted}")
    return formatted


def verify_signature(payload: bytes, signature: str) -> bool:
    digest = hmac.new(Config.APP_SECRET, payload, hashlib.sha256).hexdigest()
    valid = hmac.compare_digest(f"sha256={digest}", signature)
    logger.debug(f"Signature valid: {valid}")
    return valid


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
        logger.debug(f"WhatsApp response {resp.status_code}: {resp.text}")
        if resp.status_code != 200:
            logger.error(f"Error sending message: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"send_whatsapp exception: {e}")

# ---------- State ----------
user_states = {}

def reset_state(user: str):
    user_states.pop(user, None)

# ---------- Message Templates ----------
def text_message(text: str) -> dict:
    return {"type": "text", "text": {"body": text}}

# ---------- Main Menu as Simple Text (fallback) ----------
def start_flow(user: str):
    reset_state(user)
    # Simple text fallback while awaiting template approval
    welcome = (
        "🌟 Bienvenue sur JobBot!"
        "\nTapez /start pour réafficher ce menu."
    )
    send_whatsapp(user, text_message(welcome))
    user_states[user] = {"state": "MAIN_MENU"}

# ---------- Category Listing (text fallback) ----------
def show_categories_page(user: str, page: int = 0):
    reset_state(user)
    rows = CATEGORIES
    formatted = "\n".join(f"{i+1}. {cat}" for i, cat in enumerate(rows))
    send_whatsapp(user, text_message(f"Choisissez une catégorie par numéro :\n{formatted}"))
    user_states[user] = {"state": "CATEGORY_SELECTION", "cat_page": page}

# ---------- Show Favorites ----------
def show_favorites(user: str):
    favs = list(favs_col.find({"user": user}))
    if not favs:
        send_whatsapp(user, text_message("Vous n'avez pas de favoris."))
    else:
        for fav in favs:
            send_whatsapp(user, text_message(f"⭐ {fav.get('title')} - {fav.get('url')}"))
            time.sleep(0.1)
    send_whatsapp(user, text_message("Tapez /start pour revenir au menu."))
    reset_state(user)

# ---------- Jobs Listing ----------
def send_jobs_page(user: str, category_idx: int, page: int = 0):
    cat_name = CATEGORIES[category_idx]
    query = {"category": cat_name}
    total = jobs_col.count_documents(query)
    per = ROWS_PER_PAGE
    jobs = list(jobs_col.find(query).sort("created_at", -1).skip(page * per).limit(per))
    if not jobs:
        send_whatsapp(user, text_message("Aucune offre disponible."))
        return
    for job in jobs:
        msg = (
            f"📌 {job.get('title')}\n"
            f"🏢 {job.get('company')}\n"
            f"📍 {job.get('location')}\n"
            f"🔗 {job.get('url')}"
        )
        send_whatsapp(user, text_message(msg))
        time.sleep(0.2)
    send_whatsapp(user, text_message(f"Page {page+1}/{(total-1)//per+1}. Tapez /start pour menu."))
    user_states[user] = {"state": "BROWSING", "category": category_idx, "page": page}

# ---------- Handlers ----------
def handle_interactive(user: str, inter: dict):
    # Interactive handler left as placeholder for future template use
    send_whatsapp(user, text_message("Les messages interactifs ne sont pas encore disponibles."))
    user_states[user] = {"state": "MAIN_MENU"}

# ---------- Webhooks ----------
@app.route('/webhook', methods=['GET'])
def webhook_verify():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == Config.VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return "Forbidden", 403

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    raw = request.get_data()
    logger.debug(f"Received POST /webhook, headers={dict(request.headers)} payload={raw}")
    if not verify_signature(raw, request.headers.get('X-Hub-Signature-256', '')):
        logger.warning("Invalid signature on incoming webhook")
        return jsonify({"status": "invalid signature"}), 403
    data = request.json
    for entry in data.get('entry', []):
        for change in entry.get('changes', []):
            for message in change.get('value', {}).get('messages', []):
                mtype = message.get('type')
                try:
                    user = normalize_number(message['from'])
                except ValueError as ve:
                    logger.error(f"Invalid user number: {message.get('from')}")
                    continue
                if mtype == 'text':
                    handle_text(user, message['text']['body'].strip())
                elif mtype == 'interactive':
                    handle_interactive(user, message['interactive'])
    return jsonify({"status": "success"}), 200

# ---------- Text Handler ----------
def handle_text(user: str, text: str):
    cmd = text.upper()
    state = user_states.get(user, {}).get('state')
    logger.debug(f"TXT {cmd}|STATE {state}")
    if cmd in ['/START', 'START']:
        start_flow(user)
    else:
        # Fallback to main menu on any text
        start_flow(user)

# ---------- Main Entrypoint ----------
if __name__ == '__main__':
    Config.validate()
    # Correct any miscategorized documents
    jobs_col.update_many({'category': 'Rouder'}, {'$set': {'category': 'Remote'}})
    serve(app, host='0.0.0.0', port=Config.PORT)
