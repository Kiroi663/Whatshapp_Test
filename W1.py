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
    PORT = int(os.getenv('PORT', 10000))
    BASE_URL = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages"
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
def verify_signature(payload: bytes, signature_header: str) -> bool:
    """Valide la signature HMAC du webhook"""
    if not signature_header or not signature_header.startswith('sha256='):
        return False
    
    secret = Config.APP_SECRET
    received_sig = signature_header.split('sha256=')[1].strip()
    expected_sig = hmac.new(secret, msg=payload, digestmod=hashlib.sha256).hexdigest()
    
    return hmac.compare_digest(received_sig, expected_sig)

def create_interactive_message(text: str, buttons=None, sections=None):
    """Crée un message interactif pour WhatsApp"""
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "type": "interactive",
        "interactive": {
            "body": {"text": text}
        }
    }

    if buttons:
        payload["interactive"]["type"] = "button"
        payload["interactive"]["action"] = {"buttons": []}
        for btn in buttons:
            if 'url' in btn:
                payload["interactive"]["action"]["buttons"].append({
                    "type": "cta_url",
                    "title": btn['title'],
                    "cta_url": {
                        "display_text": btn.get('display', btn['title']),
                        "url": btn['url']
                    }
                })
            else:
                payload["interactive"]["action"]["buttons"].append({
                    "type": "reply",
                    "reply": {
                        "id": btn.get('id', btn['title'][0]),
                        "title": btn['title']
                    }
                })
    elif sections:
        payload["interactive"]["type"] = "list"
        payload["interactive"]["action"] = {
            "button": "Options",
            "sections": sections
        }

    return payload

def send_whatsapp_message(to: str, text: str, buttons=None, sections=None):
    """Envoie un message via l'API WhatsApp"""
    try:
        payload = create_interactive_message(text, buttons, sections) if (buttons or sections) else {
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
            logger.error(f"Échec d'envoi: {response.text}")
        return response.ok
    except Exception as e:
        logger.error(f"Erreur d'envoi: {str(e)}")
        return False

# ---------- Business Logic ----------
user_states = {}

def start_conversation(user: str):
    """Démarre une nouvelle conversation"""
    welcome_msg = (
        "🌟 *Bienvenue sur JobFinder* 🌟\n\n"
        "Trouvez les meilleures opportunités d'emploi.\n\n"
        "Envoyez *MENU* ou cliquez ci-dessous pour commencer."
    )
    
    send_whatsapp_message(
        user,
        welcome_msg,
        buttons=[{"title": "📋 Ouvrir le Menu", "id": "MENU"}]
    )
    user_states[user] = {"state": "MAIN_MENU"}

def show_main_menu(user: str):
    """Affiche le menu principal"""
    sections = [{
        "title": "Menu Principal",
        "rows": [
            {"id": "1", "title": "📂 Explorer catégories"},
            {"id": "2", "title": "📋 Toutes les offres"},
            {"id": "3", "title": "❤️ Mes favoris"},
            {"id": "4", "title": "🔍 Recherche avancée"}
        ]
    }]
    
    send_whatsapp_message(user, "Choisissez une option :", sections=sections)
    send_whatsapp_message(user, "Voir notre tutoriel :", 
        buttons=[{'title': '🎥 Voir démo', 'url': Config.TELEGRAM_DEMO_URL}])
    
    user_states[user]["state"] = "AWAIT_MENU"

def show_categories(user: str):
    """Affiche les catégories disponibles"""
    category_rows = [{"id": str(i+1), "title": f"{cat} ({jobs_col.count_documents({'category': cat})})"} 
                   for i, cat in enumerate(CATEGORIES)]
    
    send_whatsapp_message(user, "Catégories disponibles :", 
                 sections=[{"title": "Catégories", "rows": category_rows}])
    user_states[user]["state"] = "AWAIT_CATEGORY"

def send_jobs_page(user: str, jobs: list, category: str, page: int = 0):
    """Envoie une page d'offres d'emploi"""
    PER_PAGE = 5
    total_pages = max(1, (len(jobs) + PER_PAGE - 1) // PER_PAGE
    page = max(0, min(page, total_pages - 1))

    # Préparation des données
    for job in jobs:
        job.setdefault('url', 'https://emploicd.com/offre')
        job.setdefault('title', 'Sans titre')
        job.setdefault('company', 'Entreprise non spécifiée')
        job.setdefault('location', 'Localisation non spécifiée')
        job.setdefault('description', 'Aucune description disponible')

    # Mise à jour de l'état utilisateur
    user_states[user].update({
        "jobs": jobs,
        "page": page,
        "category": category,
        "total_pages": total_pages
    })

    # Envoi des offres
    start_idx = page * PER_PAGE
    for job in jobs[start_idx:start_idx + PER_PAGE]:
        template = random.choice(JOB_TEMPLATES)
        send_whatsapp_message(
            user, 
            template.format(**job),
            buttons=[{'title': '📌 Voir offre', 'url': job['url']}]
        )

    # Boutons de navigation
    nav_buttons = []
    if page > 0:
        nav_buttons.append({'title': '⏮ Précédent', 'id': 'P'})
    if page < total_pages - 1:
        nav_buttons.append({'title': '⏭ Suivant', 'id': 'N'})
    nav_buttons.append({'title': '🏠 Menu', 'id': 'M'})
    
    send_whatsapp_message(
        user, 
        f"📄 Page {page+1}/{total_pages} | Catégorie: {category}",
        buttons=nav_buttons
    )
    user_states[user]["state"] = "AWAIT_NAV"

def extract_message_content(msg: dict) -> str:
    """Extrait le contenu textuel d'un message WhatsApp"""
    if 'interactive' in msg:
        interactive = msg['interactive']
        if interactive['type'] == 'button_reply':
            return interactive['button_reply']['id']
        elif interactive['type'] == 'list_reply':
            return interactive['list_reply']['id']
    elif 'text' in msg:
        return msg['text']['body'].strip().upper()
    return ''

def handle_message(msg: dict):
    """Traite un message entrant"""
    user = msg['from']
    text = extract_message_content(msg)
    
    if not text or user not in user_states or text in ['START', 'MENU']:
        return start_conversation(user)
        
    state = user_states[user].get('state', 'MAIN_MENU')
    
    try:
        if state == 'MAIN_MENU' and text == 'MENU':
            show_main_menu(user)
            
        elif state == 'AWAIT_MENU':
            if text == '1':
                show_categories(user)
            elif text == '2':
                jobs = list(jobs_col.find({}))
                send_jobs_page(user, jobs, "Toutes les offres")
            elif text == '3':
                handle_favorites(user)
            else:
                send_whatsapp_message(user, "Option invalide. Veuillez choisir dans le menu.")
                
        elif state == 'AWAIT_CATEGORY':
            if text.isdigit() and 1 <= int(text) <= len(CATEGORIES):
                category = CATEGORIES[int(text)-1]
                jobs = list(jobs_col.find({"category": category}))
                send_jobs_page(user, jobs, category)
            else:
                send_whatsapp_message(user, "Catégorie invalide. Veuillez réessayer.")
                
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
                send_whatsapp_message(user, "Commande invalide.")
                
    except Exception as e:
        logger.error(f"Erreur de traitement: {str(e)}")
        send_whatsapp_message(user, "Une erreur est survenue. Veuillez réessayer.")

def handle_favorites(user: str):
    """Gère la consultation des favoris"""
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
    """Notification des nouvelles offres"""
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
def webhook_receive():
    """Réception des messages WhatsApp"""
    try:
        raw = request.get_data()
        if not verify_signature(raw, request.headers.get('X-Hub-Signature-256')):
            return jsonify({"status": "signature invalide"}), 403

        data = request.get_json()
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                for msg in change['value'].get('messages', []):
                    handle_message(msg)
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Erreur webhook: {str(e)}")
        return jsonify({"status": "error"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de santé"""
    try:
        mongo.admin.command('ping')
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat()
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
