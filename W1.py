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
ROWS_PER_PAGE = 5

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

# ---------- Catégories avec pagination ----------
def show_categories_page(user: str, page: int = 0):
    rows = []
    for i, cat in enumerate(CATEGORIES):
        truncated = (cat[:21] + '...') if len(cat) > 24 else cat
        rows.append({
            "id": f"CAT_{i}",
            "title": truncated,
            "description": ""
        })
    total = len(rows)
    start = page * ROWS_PER_PAGE
    end = start + ROWS_PER_PAGE
    page_rows = rows[start:end]

    # Construction interactive list
    interactive = {
        "type": "list",
        "body": {"text": "Choisissez une catégorie :"},
        "action": {
            "button": "Voir options",
            "sections": [{
                "title": "Catégories d'emplois",
                "rows": page_rows
            }]
        }
    }

    # Boutons de navigation si plusieurs pages
    buttons = []
    if page > 0:
        buttons.append({
            "type": "reply",
            "reply": {"id": f"CAT_PAGE_{page-1}", "title": "◀️ Précédent"}
        })
    if end < total:
        buttons.append({
            "type": "reply",
            "reply": {"id": f"CAT_PAGE_{page+1}", "title": "Suivant ▶️"}
        })

    content = {"type": "interactive", "interactive": interactive}
    if buttons:
        # On transforme en message bouton
        content = {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": "Choisissez une catégorie :"},
                "action": {"buttons": buttons}
            }
        }

    send_whatsapp(user, content)
    user_states[user] = {"state": "CATEGORY_SELECTION", "cat_page": page}

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

# ---------- Webhooks ----------
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

# ---------- Traitement messages ----------
def process_message(msg: dict):
    try:
        user = normalize_number(msg['from'])
        mtype = msg.get('type')
        if mtype == 'text':
            handle_text(user, msg['text']['body'].strip())
        elif mtype == 'interactive':
            handle_interactive(user, msg['interactive'])
    except Exception as e:
        logger.error(f"Erreur traitement message : {str(e)}")

# ---------- Messages texte ----------
def handle_text(user: str, text: str):
    cmd = text.upper()
    state = user_states.get(user, {}).get('state')
    logger.debug(f"Traitement texte: {cmd} | State: {state}")
    if cmd in ['/START', 'START']:
        start_flow(user)
    elif state == 'MAIN_MENU':
        if cmd == 'BROWSE':
            show_categories_page(user, 0)
        elif cmd == 'FAVORITES':
            show_favorites(user)
    elif cmd.startswith('PAGE_') and state == 'BROWSING':
        _, cat, page = cmd.split('_')
        send_jobs_page(user, cat, int(page))
    else:
        start_flow(user)

# ---------- Interactions ----------
def handle_interactive(user: str, interactive: dict):
    itype = interactive.get('type')
    if itype == 'list_reply':
        sid = interactive['list_reply']['id']
        if sid.startswith('CAT_'):
            idx = int(sid.split('_')[1])
            send_jobs_page(user, str(idx), 0)
    elif itype == 'button_reply':
        bid = interactive['button_reply']['id']
        if bid.startswith('CAT_PAGE_'):
            page = int(bid.split('_')[2])
            show_categories_page(user, page)
        else:
            handle_text(user, bid)

# ---------- Parcours offres ----------
def send_jobs_page(user: str, category: str, page: int = 0):
    try:
        cat_name = CATEGORIES[int(category)]
        query = {'category': cat_name}
        total = jobs_col.count_documents(query)
        per_page = 5
        jobs = list(jobs_col.find(query)
                    .sort('created_at', -1)
                    .skip(page * per_page)
                    .limit(per_page))
        if not jobs:
            send_whatsapp(user, text_message('Aucune offre disponible dans cette catégorie'))
            return
        for job in jobs:
            msg = f"📌 {job.get('title','Sans titre')}\n" + \
                  f"🏢 {job.get('company','Entreprise non spécifiée')}\n" + \
                  f"📍 {job.get('location','Localisation non précisée')}\n" + \
                  f"🔗 {job.get('url','#')}"
            send_whatsapp(user, text_message(msg))
            time.sleep(0.5)
        # Navigation
        buttons = []
        if page > 0:
            buttons.append({'type':'reply','reply':{'id':f'PAGE_{category}_{page-1}','title':'◀️ Précédent'}})
        if (page+1)*per_page < total:
            buttons.append({'type':'reply','reply':{'id':f'PAGE_{category}_{page+1}','title':'Suivant ▶️'}})
        buttons.append({'type':'reply','reply':{'id':'BACK_CAT','title':'🔙 Catégories'}})
        send_whatsapp(user, {
            'type':'interactive','interactive':{'type':'button','body':{'text':f'Page {page+1}'},'action':{'buttons':buttons}}
        })
        user_states[user] = {'state':'BROWSING','category':category,'page':page}
    except Exception as e:
        logger.error(f"Erreur d'envoi des offres : {str(e)}")
        send_whatsapp(user, text_message('Une erreur est survenue'))

# ---------- Lancement ----------
if __name__ == '__main__':
    Config.validate()
    jobs_col.update_many({'category': 'Rouder'},{'$set': {'category': 'Remote'}})
    serve(app, host='0.0.0.0', port=Config.PORT)
