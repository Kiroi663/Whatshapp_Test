import os
import hmac
import hashlib
import json
import logging
import random
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
from waitress import serve
import requests
import offreBot

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Configurations ----------
class Config:
    # WhatsApp webhook
    VERIFY_TOKEN = 'claudelAI223'
    APP_SECRET = b'7c61b31a0530bc3cc28f632a9b3e32be'
    MONGO_URI = offreBot.MONGO_URI
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    PORT = int(os.getenv('PORT', 10000))
    BASE_URL = f"https://graph.facebook.com/v15.0/{WA_PHONE_ID}/messages"
    TELEGRAM_DEMO_URL = "https://t.me/yourchannel/video123"

    @classmethod
    def validate(cls):
        required = {
            'MONGO_URI': cls.MONGO_URI,
            'WA_PHONE_ID': cls.WA_PHONE_ID,
            'WA_ACCESS_TOKEN': cls.WA_ACCESS_TOKEN
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing configuration: {', '.join(missing)}")

# ---------- Signature Verification ----------
def verify_signature(payload: bytes, header: str) -> bool:
    """Valide la signature HMAC-SHA256 des webhooks WhatsApp"""
    if not header or not header.startswith('sha256='):
        return False
    
    secret = Config.APP_SECRET
    received_sig = header.split('sha256=', 1)[1].strip()
    
    expected_sig = hmac.new(
        secret,
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(received_sig, expected_sig)

# ---------- Database ----------
mongo = MongoClient(Config.MONGO_URI, tls=True, tlsCAFile=certifi.where())
db = mongo['job_database']
jobs_col = db['jobs']
favs_col = db['user_favorites']

# ---------- Application State ----------
user_states = {}

# ---------- Templates & Categories ----------
JOB_TEMPLATES = [
    "📌 *{title}*\n🏢 *{company}*\n📍 {location}\n\n{description}\n\n🔗 {url}",
    "🚀 Opportunité : *{title}*\n\n📌 Entreprise : *{company}*\n📍 Localisation : {location}\n\n{description}\n\n📎 {url}",
    "🎯 Poste : *{title}*\n🏭 Employeur : *{company}*\n🌍 {location}\n\n📝 Description :\n{description}\n\n🌐 {url}"
]

CATEGORIES = {
    "Informatique / IT": ["développeur", "it", "digital"],
    "Finance / Comptabilité": ["finance", "comptable", "audit"],
    "Communication / Marketing": ["communication", "marketing"],
    "Conseil / Stratégie": ["consultant", "analyse"],
    "Transport / Logistique": ["transport", "logistique"],
    "Ingénierie / BTP": ["ingénieur", "technicien"],
    "Santé / Médical": ["santé", "hôpital"],
    "Éducation / Formation": ["éducation", "professeur"],
    "Ressources humaines": ["recrutement", "rh"],
    "Droit / Juridique": ["juridique", "avocat"],
    "Environnement": ["environnement", "écologie"],
    "Alternance / Stage": ["Alternance", "Stage"],
    "Remote": ["Remote", "A distance"],
    "Autre": []
}

# ---------- WhatsApp Helpers ----------
def create_interactive_message(text, buttons=None, sections=None):
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "type": "interactive"
    }

    interactive = {"body": {"text": text}}

    if buttons:
        interactive["type"] = "button"
        interactive["action"] = {"buttons": []}
        for btn in buttons:
            if 'url' in btn:
                interactive["action"]["buttons"].append({
                    "type": "cta_url",
                    "title": btn['title'],
                    "cta_url": {
                        "display_text": btn.get('display', btn['title']),
                        "url": btn['url']
                    }
                })
            else:
                interactive["action"]["buttons"].append({
                    "type": "reply",
                    "reply": {
                        "id": btn.get('id', btn['title'][0]),
                        "title": btn['title']
                    }
                })
    elif sections:
        interactive["type"] = "list"
        interactive["action"] = {
            "button": "Options",
            "sections": sections
        }

    payload["interactive"] = interactive
    return payload

def send_whatsapp(to: str, text: str, buttons=None, sections=None):
    try:
        if buttons or sections:
            payload = create_interactive_message(text, buttons, sections)
        else:
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "type": "text",
                "text": {"body": text}
            }

        headers = {
            "Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        response = requests.post(Config.BASE_URL, headers=headers, json=payload)
        if not response.ok:
            logger.error(f"Failed to send message: {response.text}")
        return response.ok
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return False

# ---------- Business Logic ----------
def start_conversation(user: str):
    welcome_msg = (
        "🌟 *Bienvenue sur JobFinder* 🌟\n\n"
        "Trouvez les meilleures opportunités d'emploi en RDC.\n\n"
        "Envoyez *MENU* ou cliquez ci-dessous pour commencer."
    )
    
    send_whatsapp(
        user,
        welcome_msg,
        buttons=[{"title": "📋 Ouvrir le Menu", "id": "MENU"}]
    )
    user_states[user] = {"state": "MAIN_MENU"}

def show_main_menu(user: str):
    sections = [{
        "title": "Menu Principal",
        "rows": [
            {"id": "1", "title": "📂 Explorer par catégories"},
            {"id": "2", "title": "📋 Voir toutes les offres"},
            {"id": "3", "title": "❤️ Mes favoris"},
            {"id": "4", "title": "🔍 Recherche avancée"}
        ]
    }]
    
    send_whatsapp(user, "Choisissez une option :", sections=sections)
    send_whatsapp(user, "Regardez notre tutoriel :", 
        buttons=[{'title': '🎥 Voir la démo', 'url': Config.TELEGRAM_DEMO_URL}])
    
    user_states[user]["state"] = "AWAIT_MENU"

def show_categories(user: str):
    category_rows = [{"id": str(i+1), "title": f"{cat} ({jobs_col.count_documents({'category': cat})}"} 
                   for i, cat in enumerate(CATEGORIES)]
    
    send_whatsapp(user, "Catégories disponibles :", 
                 sections=[{"title": "Catégories", "rows": category_rows}])
    user_states[user]["state"] = "AWAIT_CATEGORY"

def send_jobs_page(user: str, jobs: list, category: str, page: int = 0):
    PER_PAGE = 5
    total_pages = (len(jobs) + PER_PAGE - 1) // PER_PAGE
    
    # Set default values for missing fields
    for job in jobs:
        job.setdefault('url', 'https://emploicd.com/offre')
        job.setdefault('title', 'Sans titre')
        job.setdefault('company', 'Entreprise non spécifiée')
        job.setdefault('location', 'Localisation non spécifiée')
        job.setdefault('description', 'Aucune description disponible')

    # Update user state
    user_states[user].update({
        "jobs": jobs,
        "page": page,
        "category": category,
        "total_pages": total_pages
    })

    # Send jobs
    start = page * PER_PAGE
    for job in jobs[start:start+PER_PAGE]:
        template = random.choice(JOB_TEMPLATES)
        send_whatsapp(user, template.format(**job), 
                     buttons=[{'title': '📌 Voir offre', 'url': job['url']}])

    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append({'title': '⏮ Précédent', 'id': 'P'})
    if page < total_pages - 1:
        nav_buttons.append({'title': '⏭ Suivant', 'id': 'N'})
    nav_buttons.append({'title': '🏠 Menu', 'id': 'M'})
    
    send_whatsapp(user, f"Page {page+1}/{total_pages}", buttons=nav_buttons)
    user_states[user]["state"] = "AWAIT_NAV"

# ---------- Webhook Handler ----------
app = Flask(__name__)

@app.route('/webhook', methods=['GET'])
def webhook_verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == Config.VERIFY_TOKEN:
        logger.info("Webhook verified")
        return challenge, 200
    return 'Verification failed', 403

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    try:
        raw = request.get_data()
        if not verify_signature(raw, request.headers.get('X-Hub-Signature-256')):
            return jsonify({"status": "invalid signature"}), 403

        data = request.get_json()
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                for msg in change['value'].get('messages', []):
                    handle_message(msg)
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({"status": "error"}), 500

def handle_message(msg: dict):
    user = msg['from']
    text = extract_message_content(msg)
    
    if text in ['START', 'MENU'] or user not in user_states:
        return start_conversation(user)
        
    state = user_states[user].get('state', 'MAIN_MENU')
    
    if state == 'MAIN_MENU' and text == 'MENU':
        show_main_menu(user)
    elif state == 'AWAIT_MENU':
        handle_menu_selection(user, text)
    elif state == 'AWAIT_CATEGORY':
        handle_category_selection(user, text)
    elif state == 'AWAIT_NAV':
        handle_navigation(user, text)

# ---------- Notification System ----------
def notify_new_jobs():
    import time
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
                    send_whatsapp(
                        user['user_id'],
                        "🚨 NOUVELLE OFFRE !\n" + random.choice(JOB_TEMPLATES).format(**job),
                        buttons=[{'title': '📌 Voir offre', 'url': job['url']}]
                    )
                    time.sleep(1)
                
                jobs_col.update_one({"_id": job['_id']}, {"$set": {"is_notified": True}})
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"Notification error: {str(e)}")
            time.sleep(300)

# ---------- Startup ----------
if __name__ == '__main__':
    Config.validate()
    threading.Thread(target=notify_new_jobs, daemon=True).start()
    logger.info(f"Starting server on port {Config.PORT}")
    serve(app, host='0.0.0.0', port=Config.PORT)
