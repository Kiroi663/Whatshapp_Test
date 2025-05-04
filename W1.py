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

# ---------- Enhanced WhatsApp Helpers ----------
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
                # Correction du format CTA URL
                interactive["action"]["buttons"].append({
                    "type": "cta_url",
                    "title": btn['title'],
                    "cta_url": {
                        "display_text": btn.get('display', btn['title']),
                        "url": btn['url']
                    }
                })
            else:
                # Correction du format reply button
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

# ---------- Enhanced Business Logic ----------
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
    
    send_whatsapp(
        user,
        "Choisissez une option dans le menu :",
        sections=sections
    )
    
    # Send Telegram demo button separately
    send_whatsapp(
        user,
        "Pour voir comment utiliser notre service :",
        buttons=[{
            'title': '🎥 Regarder la démo vidéo', 
            'url': Config.TELEGRAM_DEMO_URL,
            'display': 'Voir la démo'
        }]
    )
    
    user_states[user]["state"] = "AWAIT_MENU"

def show_categories(user: str):
    category_rows = []
    for i, category in enumerate(CATEGORIES.keys(), start=1):
        category_rows.append({
            "id": str(i),
            "title": f"{category} ({len(list(jobs_col.find({'category': category})))} offres)"
        })
    
    sections = [{
        "title": "Catégories disponibles",
        "rows": category_rows
    }]
    
    send_whatsapp(
        user,
        "Choisissez une catégorie :",
        sections=sections
    )
    user_states[user]["state"] = "AWAIT_CATEGORY"

def send_jobs_page(user: str, jobs: list, category: str, page: int = 0):
    per_page = 5
    total_pages = (len(jobs) // per_page) + (1 if len(jobs) % per_page != 0 else 0)
    start_idx = page * per_page
    end_idx = start_idx + per_page
    
    # Update user state
    user_states[user].update({
        "jobs": jobs,
        "page": page,
        "category": category,
        "total_pages": total_pages
    })
    
    # Send page info
    send_whatsapp(
        user,
        f"📄 Page *{page + 1}/{total_pages}* | Catégorie : *{category}*"
    )
    
    # Send each job with URL button
    for job in jobs[start_idx:end_idx]:
        # Set default values if missing
        job.setdefault('url', 'https://emploicd.com/offre')
        job.setdefault('title', 'Sans titre')
        job.setdefault('company', 'Entreprise non spécifiée')
        job.setdefault('location', 'Localisation non spécifiée')
        job.setdefault('description', 'Aucune description disponible')
        
        template = random.choice(JOB_TEMPLATES)
        job_msg = template.format(**job)
        
        send_whatsapp(
            user,
            job_msg,
            buttons=[{
                'title': '📌 Voir offre complète',
                'url': job['url'],
                'display': 'Voir détails'
            }]
        )
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append({'title': '⏮ Précédent', 'id': 'P'})
    if page + 1 < total_pages:
        nav_buttons.append({'title': '⏭ Suivant', 'id': 'N'})
    nav_buttons.append({'title': '🏠 Menu Principal', 'id': 'M'})
    
    send_whatsapp(
        user,
        "Que souhaitez-vous faire ensuite ?",
        buttons=nav_buttons
    )
    
    user_states[user]["state"] = "AWAIT_NAV"

def handle_favorites(user: str):
    favs = favs_col.find_one({"user_id": user}) or {"categories": []}
    if not favs["categories"]:
        send_whatsapp(user, "Vous n'avez aucune catégorie en favoris.")
        return
    
    favorite_jobs = list(jobs_col.find({"category": {"$in": favs["categories"]}}))
    
    if not favorite_jobs:
        send_whatsapp(user, "Aucune offre disponible dans vos catégories favorites.")
    else:
        send_jobs_page(user, favorite_jobs, "Vos Favoris")

# ---------- Webhook Handler ----------
app = Flask(__name__)

@app.route('/webhook', methods=['GET'])
def webhook_verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == Config.VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return challenge, 200
    return 'Verification failed', 403

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    try:
        # Verify signature
        raw = request.get_data()
        sig = request.headers.get('X-Hub-Signature-256')
        if not verify_signature(raw, sig):
            return jsonify({"status": "invalid signature"}), 403
        
        data = request.get_json()
        
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change['value']
                
                # Process each message
                for message in value.get('messages', []):
                    user = message['from']
                    text = ''
                    
                    # Handle interactive messages (buttons/lists)
                    if 'interactive' in message:
                        interactive = message['interactive']
                        if interactive['type'] == 'button_reply':
                            text = interactive['button_reply']['id']
                        elif interactive['type'] == 'list_reply':
                            text = interactive['list_reply']['id']
                    # Handle text messages
                    elif 'text' in message:
                        text = message['text']['body'].strip().upper()
                    
                    # Initialize new user
                    if user not in user_states or text in ['START', 'MENU']:
                        start_conversation(user)
                        continue
                    
                    state = user_states[user].get('state', 'MAIN_MENU')
                    
                    # State machine
                    if state == 'MAIN_MENU':
                        if text == 'MENU':
                            show_main_menu(user)
                    
                    elif state == 'AWAIT_MENU':
                        if text == '1':
                            show_categories(user)
                        elif text == '2':
                            jobs = list(jobs_col.find({}))
                            send_jobs_page(user, jobs, "Toutes les offres")
                        elif text == '3':
                            handle_favorites(user)
                        elif text == '4':
                            send_whatsapp(user, "Fonctionnalité de recherche avancée à venir!")
                        else:
                            send_whatsapp(user, "Option invalide. Veuillez choisir dans le menu.")
                    
                    elif state == 'AWAIT_CATEGORY':
                        if text.isdigit():
                            categories = list(CATEGORIES.keys())
                            if 1 <= int(text) <= len(categories):
                                selected_category = categories[int(text)-1]
                                jobs = list(jobs_col.find({"category": selected_category}))
                                send_jobs_page(user, jobs, selected_category)
                            else:
                                send_whatsapp(user, "Numéro de catégorie invalide.")
                        else:
                            send_whatsapp(user, "Veuillez sélectionner une catégorie valide.")
                    
                    elif state == 'AWAIT_NAV':
                        if text == 'P':
                            current_page = user_states[user]['page']
                            if current_page > 0:
                                send_jobs_page(
                                    user,
                                    user_states[user]['jobs'],
                                    user_states[user]['category'],
                                    current_page - 1
                                )
                        elif text == 'N':
                            current_page = user_states[user]['page']
                            if current_page + 1 < user_states[user]['total_pages']:
                                send_jobs_page(
                                    user,
                                    user_states[user]['jobs'],
                                    user_states[user]['category'],
                                    current_page + 1
                                )
                        elif text == 'M':
                            show_main_menu(user)
                        else:
                            send_whatsapp(user, "Commande de navigation invalide.")
        
        return jsonify({"status": "success"}), 200
    
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ---------- Notification System ----------
def notify_new_jobs():
    import time
    while True:
        try:
            # Find jobs not yet notified
            new_jobs = list(jobs_col.find({"is_notified": {"$ne": True}}))
            
            for job in new_jobs:
                # Skip if missing required fields
                if 'category' not in job:
                    logger.warning(f"Job {job.get('_id')} skipped - missing category")
                    continue
                    
                # Set default values
                job.setdefault('url', 'https://emploicd.com/offre')
                job.setdefault('title', 'Nouvelle offre')
                job.setdefault('description', '')
                
                # Find subscribers
                users = favs_col.find({"categories": job['category']})
                
                for user in users:
                    template = random.choice(JOB_TEMPLATES)
                    notification = template.format(**job)
                    
                    send_whatsapp(
                        user['user_id'],
                        "🚨 NOUVELLE OFFRE DANS VOS FAVORIS 🚨\n\n" + notification,
                        buttons=[{
                            'title': '📌 Voir offre',
                            'url': job['url'],
                            'display': 'Voir détails'
                        }]
                    )
                    time.sleep(1)  # Rate limiting
                
                # Mark as notified
                jobs_col.update_one(
                    {"_id": job['_id']},
                    {"$set": {
                        "is_notified": True,
                        "notified_at": datetime.utcnow()
                    }}
                )
            
            time.sleep(60)  # Check every minute
            
        except Exception as e:
            logger.error(f"Notification error: {str(e)}")
            time.sleep(300)  # Wait 5 minutes on error

# ---------- Health Check ----------
@app.route('/health', methods=['GET'])
def health_check():
    try:
        # Check database connection
        mongo.admin.command('ping')
        
        # Check WhatsApp connection
        test_msg = {"messaging_product": "whatsapp", "to": "test", "type": "text", "text": {"body": "test"}}
        headers = {"Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}", "Content-Type": "application/json"}
        response = requests.post(Config.BASE_URL, headers=headers, json=test_msg)
        
        if response.status_code != 200:
            raise Exception("WhatsApp API not responding")
            
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "whatsapp_api": "responsive",
            "timestamp": datetime.utcnow().isoformat()
        }), 200
    
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500

# ---------- Startup ----------
if __name__ == '__main__':
    Config.validate()
    
    # Start notification thread
    notification_thread = threading.Thread(target=notify_new_jobs, daemon=True)
    notification_thread.start()
    
    # Start Flask server
    logger.info(f"Starting server on port {Config.PORT}")
    serve(app, host='0.0.0.0', port=Config.PORT)
