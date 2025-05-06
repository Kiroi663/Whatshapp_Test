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

# ---------- Configuration Logging ----------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------- Flask App ----------
app = Flask(__name__)

# ---------- Bot Configuration ----------
class Config:
    VERIFY_TOKEN      = 'claudelAI223'
    APP_SECRET        = b'7c61b31a0530bc3cc28f632a9b3e32be'
    MONGO_URI         = offreBot.MONGO_URI
    WA_PHONE_ID       = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN   = offreBot.WA_ACCESS_TOKEN
    TEST_NUMBER       = offreBot.TEST_NUMBER
    PORT              = int(os.getenv('PORT', 10000))
    BASE_URL          = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages"

    @classmethod
    def validate(cls):
        required = {
            'MONGO_URI': cls.MONGO_URI,
            'WA_PHONE_ID': cls.WA_PHONE_ID,
            'WA_ACCESS_TOKEN': cls.WA_ACCESS_TOKEN,
            'TEST_NUMBER': cls.TEST_NUMBER
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Configuration manquante: {', '.join(missing)}")

# ---------- Database Setup ----------
mongo    = MongoClient(Config.MONGO_URI, tls=True, tlsCAFile=certifi.where())
db       = mongo['job_database']
jobs_col = db['christ']
favs_col = db['user_favorites']

# ---------- Constants ----------
CATEGORIES = [
    "Informatique / IT", "Finance / Comptabilité", "Communication / Marketing",
    "Conseil / Stratégie", "Transport / Logistique", "Ingénierie / BTP",
    "Santé / Médical", "Éducation / Formation", "Ressources humaines",
    "Droit / Juridique", "Environnement", "Alternance / Stage", "Remote", "Autre"
]

# ---------- Utilities ----------
def normalize_and_validate(number: str) -> str:
    if number.isdigit():
        number = '+' + number
    if not re.match(r'^\+\d{10,15}$', number):
        raise ValueError(f"Numéro invalide: {number}")
    return number


def verify_signature(payload: bytes, signature_header: str) -> bool:
    if not signature_header or not signature_header.startswith('sha256='):
        return False
    sig = signature_header.split('sha256=')[1]
    expected = hmac.new(Config.APP_SECRET, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def extract_text(msg: dict) -> str:
    return msg.get('text', {}).get('body', '').strip().upper()


def create_message_payload(to: str, content: dict) -> dict:
    return {"messaging_product": "whatsapp", "to": to, **content}


def make_button_list(text: str, buttons: list) -> dict:
    return {"type": "interactive", "interactive": {"type": "button", "body": {"text": text}, "action": {"buttons": buttons}}}


def make_list_message(text: str, rows: list) -> dict:
    section = {"title": "Catégories", "rows": rows}
    return {"type": "interactive", "interactive": {"type": "list", "body": {"text": text}, "action": {"button": "Sélectionner", "sections": [section]}}}


def send_message(to: str, content: dict) -> bool:
    try:
        payload = create_message_payload(to, content)
        headers = {"Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}", "Content-Type": "application/json"}
        res = requests.post(Config.BASE_URL, headers=headers, json=payload)
        if not res.ok:
            logger.error("Échec envoi %s: %s", to, res.text)
        return res.ok
    except Exception as e:
        logger.error("Erreur send_message: %s", e)
        return False

# ---------- User State ----------
user_states = {}
# state: MAIN_MENU, BROWSING, FAVORITES

# ---------- Handlers ----------
def start_conversation(user: str):
    text = "🌟 Bienvenue sur JobFinder 🌟\nQue voulez-vous faire ?"
    buttons = [
        {"type": "reply", "reply": {"id": "EXPLORE", "title": "🔍 Explorer les offres"}},
        {"type": "reply", "reply": {"id": "FAVS",    "title": "⭐ Voir mes favoris"}}
    ]
    send_message(user, make_button_list(text, buttons))
    user_states[user] = {"state": "MAIN_MENU"}


def show_categories(user: str):
    rows = [{"id": f"CAT_{i}", "title": cat} for i, cat in enumerate(CATEGORIES)]
    send_message(user, make_list_message("Sélectionnez une catégorie :", rows))
    user_states[user] = {"state": "BROWSING", "mode": "CATEGORY_MENU"}


def list_jobs_page(user: str, category: str, page: int = 0):
    query = {} if category == 'all' else {"category": category}
    jobs = list(jobs_col.find(query))
    per_page = 5
    total = len(jobs)
    pages = (total + per_page - 1) // per_page
    start = page * per_page
    items = jobs[start:start+per_page]

    for job in items:
        text = f"*{job.get('title')}* chez *{job.get('company')}*\n{job.get('location')}"
        btn = [{"type": "url", "url": job.get('url', '#'), "title": "📝 Postuler"}]
        send_message(user, make_button_list(text, btn))
        time.sleep(0.5)

    # navigation
    nav = []
    if page > 0:
        nav.append({"type": "reply", "reply": {"id": f"PAGE_{category}_{page-1}", "title": "⬅️ Précédent"}})
    if page < pages - 1:
        nav.append({"type": "reply", "reply": {"id": f"PAGE_{category}_{page+1}", "title": "Suivant ➡️"}})
    nav.append({"type": "reply", "reply": {"id": "BACK_CATS", "title": "🔙 Retour"}})
    send_message(user, make_button_list(f"Page {page+1}/{pages} - {total} offres", nav))
    user_states[user].update({"category": category, "page": page})


def show_favorites_menu(user: str):
    favs = favs_col.find_one({"user_id": user}) or {"categories": []}
    current = favs.get('categories', [])
    rows = []
    for i, cat in enumerate(CATEGORIES):
        mark = '✅' if cat in current else '◻️'
        rows.append({"id": f"FAV_{i}", "title": f"{mark} {cat}"})
    send_message(user, make_list_message("Gérez vos notifications :", rows))
    user_states[user] = {"state": "FAVORITES"}

# ---------- Main Message Router ----------
def handle_message(msg: dict):
    raw = msg['from']
    try:
        user = normalize_and_validate(raw)
    except:
        logger.warning("Numéro invalide: %s", raw)
        return
    text = extract_text(msg)
    logger.info("Message %s: %s", user, text)

    state = user_states.get(user, {}).get('state')
    # start or main menu
    if text in ['/START', 'START'] or state is None:
        return start_conversation(user)

    # MAIN_MENU actions
    if state == 'MAIN_MENU':
        if text == 'EXPLORE':
            return show_categories(user)
        if text == 'FAVS':
            return show_favorites_menu(user)

    # BROWSING state
    if state == 'BROWSING':
        mode = user_states[user].get('mode')
        if text.startswith('CAT_'):
            idx = int(text.split('_')[1])
            cat = CATEGORIES[idx]
            return list_jobs_page(user, cat, 0)
        if text == 'BACK_CATS':
            return show_categories(user)
        if text.startswith('PAGE_'):
            _, cat, pg = text.split('_')
            return list_jobs_page(user, cat, int(pg))

    # FAVORITES state
    if state == 'FAVORITES':
        if text.startswith('FAV_'):
            idx = int(text.split('_')[1])
            cat = CATEGORIES[idx]
            favs = favs_col.find_one({"user_id": user}) or {"categories": []}
            current = favs.get('categories', [])
            if cat in current:
                current.remove(cat)
            else:
                current.append(cat)
            favs_col.update_one({"user_id": user}, {"$set": {"categories": current}}, upsert=True)
            return show_favorites_menu(user)

# ---------- Notification Loop ----------
def notify_new_jobs():
    while True:
        try:
            new_jobs = list(jobs_col.find({"is_notified": False}))
            for job in new_jobs:
                cat = job.get('category')
                for u in favs_col.find({"categories": cat}):
                    try:
                        send_message(
                            u['user_id'],
                            {"type":"text","text":{"body":f"🚨 Nouvelle offre: {job.get('title')}"}}
                        )
                    except Exception:
                        pass
                jobs_col.update_one({"_id": job['_id']}, {"$set": {"is_notified": True}})
            time.sleep(60)
        except Exception as e:
            logger.error("notify error: %s", e)
            time.sleep(300)

# ---------- Webhook Endpoints ----------
@app.route('/webhook', methods=['GET'])
def webhook_verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode == 'subscribe' and token == Config.VERIFY_TOKEN:
        return challenge, 200
    return 'Forbidden', 403

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    raw = request.get_data()
    sig = request.headers.get('X-Hub-Signature-256')
    if not verify_signature(raw, sig):
        return jsonify({"status":"invalid signature"}), 403
    data = request.get_json()
    for entry in data.get('entry', []):
        for ch in entry.get('changes', []):
            for m in ch['value'].get('messages', []):
                handle_message(m)
    return jsonify({"status":"success"}), 200

# ---------- Health Check ----------
@app.route('/health', methods=['GET'])
def health():
    try:
        mongo.admin.command('ping')
        return "OK", 200
    except:
        return "DB error", 500

# ---------- Main ----------
if __name__ == '__main__':
    Config.validate()
    threading.Thread(target=notify_new_jobs, daemon=True).start()
    serve(app, host='0.0.0.0', port=Config.PORT)
