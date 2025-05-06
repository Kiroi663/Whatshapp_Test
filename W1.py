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
jobs_col = db['jobs']
favs_col = db['user_favorites']

# ---------- Message Templates & Categories ----------
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

# ---------- Utilities ----------
def normalize_and_validate(number: str) -> str:
    """
    Ajoute un '+' en début si nécessaire et valide le format E.164.
    """
    if number.isdigit():
        number = '+' + number
    if not re.match(r'^\+\d{10,15}$', number):
        raise ValueError(f"Numéro invalide: {number}")
    return number


def verify_signature(payload: bytes, signature_header: str) -> bool:
    """
    Valide la signature HMAC SHA-256 du webhook.
    """
    if not signature_header or not signature_header.startswith('sha256='):
        return False
    received_sig = signature_header.split('sha256=')[1].strip()
    expected_sig = hmac.new(Config.APP_SECRET, msg=payload, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_sig, expected_sig)


def extract_message_content(msg: dict) -> str:
    """
    Extrait et normalise le contenu textuel du message.
    """
    if msg.get('type') == 'text':
        return msg['text']['body'].strip().upper()
    return ''

# ---------- Payload Creation ----------
def create_message_payload(to: str, content: dict) -> dict:
    """
    Construit le JSON complet à envoyer à l'API WhatsApp.
    """
    return {"messaging_product": "whatsapp", "to": to, **content}


def create_interactive_content(text: str, buttons=None, sections=None) -> dict:
    """
    Prépare un message interactif (boutons ou liste).
    """
    content = {"type": "interactive", "interactive": {"body": {"text": text}, "action": {}}}
    if buttons:
        content["interactive"]["type"] = "button"
        content["interactive"]["action"]["buttons"] = []
        for btn in buttons:
            if 'url' in btn:
                content["interactive"]["action"]["buttons"].append({
                    "type": "cta_url",
                    "title": btn['title'],
                    "cta_url": {"display_text": btn.get('display', btn['title']), "url": btn['url']}
                })
            else:
                content["interactive"]["action"]["buttons"].append({
                    "type": "reply",
                    "reply": {"id": btn.get('id', btn['title'][0]), "title": btn['title']}
                })
    elif sections:
        content["interactive"]["type"] = "list"
        content["interactive"]["action"]["button"] = "Options"
        content["interactive"]["action"]["sections"] = sections
    return content

# ---------- Sending Messages ----------
def send_whatsapp_message(to: str, text: str, buttons=None, sections=None) -> bool:
    """
    Envoie un message (texte ou interactif) et gère les erreurs.
    """
    try:
        payload_type = {"type": "text", "text": {"body": text}}
        content = payload_type if not (buttons or sections) else create_interactive_content(text, buttons, sections)
        payload = create_message_payload(to, content)
        headers = {"Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}", "Content-Type": "application/json"}
        resp = requests.post(Config.BASE_URL, headers=headers, json=payload)
        if not resp.ok:
            error = resp.json().get('error', {}).get('message', '')
            logger.error("Échec d'envoi à %s: %s", to, error)
            return False
        return True
    except Exception as e:
        logger.error("Erreur d'envoi à %s: %s", to, str(e))
        return False

# ---------- Business Logic ----------
user_states = {}

def start_conversation(user: str):
    """Démarre la conversation et envoie le menu principal."""
    welcome = (
        "🌟 *Bienvenue sur JobFinder* 🌟\n\n"
        "Trouvez les meilleures opportunités d'emploi.\n\n"
        "Envoyez *MENU* ou cliquez ci-dessous."
    )
    send_whatsapp_message(user, welcome, buttons=[{"title": "📋 Ouvrir le Menu", "id": "MENU"}])
    user_states[user] = {"state": "MAIN_MENU"}

# stub: à remplacer par vos propres handlers

def handle_main_menu(user: str, text: str):
    send_whatsapp_message(user, f"Vous avez tapé: {text}")


def handle_message(msg: dict):
    """Traite un message entrant et route selon l'état."""
    try:
        raw_from = msg['from']
        user = normalize_and_validate(raw_from)
        msg['from'] = user
        text = extract_message_content(msg)
        logger.info("Reçu de %s : %s", user, text)

        # Démarrer si premier contact ou commande /start ou MENU
        if not text or user not in user_states or text in ['/START', 'START', 'MENU']:
            logger.info("Démarrage nouvelle conversation pour: %s", user)
            return start_conversation(user)

        state = user_states[user].get('state', 'MAIN_MENU')
        logger.debug("État %s, commande: %s", state, text)

        if state == 'MAIN_MENU':
            handle_main_menu(user, text)
        # elif state == 'AUTRE_ETAT':
        #     ...

    except Exception as e:
        logger.error("ERREUR handle_message: %s", str(e), exc_info=True)
        try:
            send_whatsapp_message(user, "Erreur interne - Veuillez réessayer")
        except:
            pass

# ---------- Background Notification ----------
def notify_new_jobs():
    while True:
        try:
            new_jobs = list(jobs_col.find({"is_notified": {"$ne": True}}))
            for job in new_jobs:
                cat = job.get('category')
                if not cat:
                    continue
                url = job.get('url', 'https://emploicd.com/offre')
                job.setdefault('title', 'Nouvelle offre')
                job.setdefault('description', '')
                users = favs_col.find({"categories": cat})
                for u in users:
                    try:
                        to = normalize_and_validate(u['user_id'])
                        send_whatsapp_message(
                            to,
                            "🚨 NOUVELLE OFFRE !\n" + random.choice(JOB_TEMPLATES).format(**job),
                            buttons=[{'title': '📌 Voir offre', 'url': url}]
                        )
                        time.sleep(1)
                    except Exception:
                        pass
                jobs_col.update_one({"_id": job['_id']}, {"$set": {"is_notified": True, "notified_at": datetime.utcnow()}})
            time.sleep(60)
        except Exception as e:
            logger.error("Erreur de notification: %s", str(e))
            time.sleep(300)

# ---------- Webhook Endpoints ----------
@app.route('/webhook', methods=['GET'])
def webhook_verify():
    mode      = request.args.get('hub.mode')
    token     = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode == 'subscribe' and token == Config.VERIFY_TOKEN:
        logger.info("Webhook validé")
        return challenge, 200
    return 'Échec de validation', 403

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    try:
        raw = request.get_data()
        logger.debug("Requête reçue:\n%s", raw.decode('utf-8'))
        sig = request.headers.get('X-Hub-Signature-256')
        if not verify_signature(raw, sig):
            logger.warning("Signature invalide rejetée")
            return jsonify({"status": "signature invalide"}), 403

        data = request.get_json()
        logger.info("Payload JSON reçu: %s", json.dumps(data, indent=2))

        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                for msg in change['value'].get('messages', []):
                    logger.debug("Message brut: %s", msg)
                    handle_message(msg)

        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error("ERREUR WEBHOOK: %s", str(e), exc_info=True)
        return jsonify({"status": "error"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    try:
        mongo.admin.command('ping')
        test_msg = {"type": "text", "text": {"body": "TEST"}}
        payload = create_message_payload(normalize_and_validate(Config.TEST_NUMBER), test_msg)
        headers = {"Authorization": f"Bearer {Config.WA_ACCESS_TOKEN}", "Content-Type": "application/json"}
        resp = requests.post(Config.BASE_URL, headers=headers, json=payload)
        if not resp.ok:
            raise Exception(f"Erreur WhatsApp: {resp.text}")
        return jsonify({"status": "healthy", "services": {"database": "ok", "whatsapp": "ok"}}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# ---------- Main ----------
if __name__ == '__main__':
    Config.validate()
    threading.Thread(target=notify_new_jobs, daemon=True).start()
    logger.info(f"Démarrage du serveur sur le port {Config.PORT}")
    serve(app, host='0.0.0.0', port=Config.PORT)
