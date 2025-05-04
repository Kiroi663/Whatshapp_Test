import os
import hmac
import hashlib
import json
import logging
import random
import asyncio
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
    VERIFY_TOKEN      = 'claudelAI223'
    APP_SECRET        = b'7c61b31a0530bc3cc28f632a9b3e32be'
    MONGO_URI         = offreBot.MONGO_URI
    WA_PHONE_ID       = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN   = offreBot.WA_ACCESS_TOKEN
    PORT              = int(os.getenv('PORT', 10000))
    BASE_URL          = f"https://graph.facebook.com/v15.0/{WA_PHONE_ID}/messages"

    @classmethod
    def validate(cls):
        missing = []
        if not cls.MONGO_URI:       missing.append('MONGODB_URI')
        if not cls.WA_PHONE_ID:     missing.append('WHATSAPP_PHONE_ID')
        if not cls.WA_ACCESS_TOKEN: missing.append('WHATSAPP_ACCESS_TOKEN')
        if missing:
            raise ValueError(f"Missing configuration: {', '.join(missing)}")

# ---------- Database ----------
mongo = MongoClient(Config.MONGO_URI, tls=True, tlsCAFile=certifi.where())
db = mongo['job_database']
jobs_col = db['christ']
favs_col = db['user_favorites']

# ---------- Application State ----------
user_states = {}  # phone_number -> { state, category, page, jobs }

# ---------- Message Templates & Categories ----------
templates = [
    "📌 *{title}* chez *{company}* à {location}.\n{resume}\n",
    "🚀 Opportunité : *{title}*!\nEntreprise : *{company}*\n📍 {location}\n👉 {resume}\n",
    "🎯 Poste : *{title}*\n🏢 Employeur : *{company}*\n📍 {location}\n📜 {resume}\n"
]

categories = {
    "Informatique / IT": ["développeur","it","digital"],
    "Finance / Comptabilité": ["finance","comptable","audit"],
    "Communication / Marketing": ["communication","marketing"],
    "Conseil / Stratégie": ["consultant","analyse"],
    "Transport / Logistique": ["transport","logistique"],
    "Ingénierie / BTP": ["ingénieur","technicien"],
    "Santé / Médical": ["santé","hôpital"],
    "Éducation / Formation": ["éducation","professeur"],
    "Ressources humaines": ["recrutement","rh"],
    "Droit / Juridique": ["juridique","avocat"],
    "Environnement": ["environnement","écologie"],
    "Alternance / Stage": ["Alternance","Stage"],
    "Remote": ["Remote","A distance"],
    "Autre": []
}

# ---------- WhatsApp Helpers ----------
def verify_signature(payload: bytes, header: str) -> bool:
    if not header or not header.startswith('sha256='):
        return False
    received = header.split('=',1)[1]
    expected = hmac.new(Config.APP_SECRET, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received, expected)

def send_whatsapp(to: str, text: str, buttons=None, list_sections=None):
    payload = {"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":text}}
    # This is a simplified text send; buttons & lists need interactive payloads
    headers = {"Authorization":f"Bearer {Config.WA_ACCESS_TOKEN}","Content-Type":"application/json"}
    r = requests.post(Config.BASE_URL, headers=headers, json=payload)
    if not r.ok:
        logger.error(f"Failed to send message to {to}: {r.text}")
    return r.ok

# ---------- Business Logic ----------
def start_conversation(user: str):
    text = f"Bienvenue sur JobFinder, envoyez 'MENU' pour commencer."
    send_whatsapp(user, text)
    user_states[user] = {"state":"MAIN_MENU"}

def show_menu(user: str):
    msg = "Menu principal:\n1. Explorer catégories\n2. Voir toutes les offres\n3. Mes favoris\n4. Recherche avancée"
    send_whatsapp(user, msg)
    user_states[user]["state"] = "AWAIT_MENU"

def list_categories(user: str):
    msg = "Catégories disponibles:" + ''.join(f"\n- {c}" for c in categories)
    send_whatsapp(user, msg)
    user_states[user].update({"state":"AWAIT_CATEGORY"})

def send_jobs_page(user: str):
    state = user_states[user]
    jobs = state["jobs"]
    per = 5
    page = state["page"]
    start = page*per
    page_jobs = jobs[start:start+per]
    send_whatsapp(user, f"Page {page+1}/{(len(jobs)-1)//per+1}, catégorie {state['category']}")
    for job in page_jobs:
        text = random.choice(templates).format(
            title=job.get("title"), company=job.get("company"),
            location=job.get("location"), resume=job.get("description")
        )
        send_whatsapp(user, text)
    nav = []
    if page>0: nav.append("P: précédent")
    if (page+1)*per < len(jobs): nav.append("N: suivant")
    nav.append("M: menu")
    send_whatsapp(user, "Navigation: " + ' | '.join(nav))
    user_states[user]["state"] = "AWAIT_NAV"

# ---------- Flask Webhook ----------
app = Flask(__name__)

@app.route('/webhook', methods=['GET'])
def webhook_verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode=='subscribe' and token==Config.VERIFY_TOKEN:
        return challenge,200
    return 'Fail',403

@app.route('/webhook', methods=['POST'])
def webhook_receive():
    raw = request.get_data()
    sig = request.headers.get('X-Hub-Signature-256')
    if not verify_signature(raw, sig): return jsonify(),403
    data = request.get_json()
    for entry in data.get('entry',[]):    
        for msg in entry.get('changes',[]):
            val = msg['value']
            for m in val.get('messages',[]):
                user = m['from']
                text = m.get('text',{}).get('body','').strip().upper()
                # Initialize
                if user not in user_states or text=='START':
                    start_conversation(user)
                else:
                    state = user_states[user]['state']
                    if state=='MAIN_MENU' and text=='MENU':
                        show_menu(user)
                    elif state=='AWAIT_MENU':
                        if text=='1': list_categories(user)
                        elif text=='2': 
                            # all offers
                            jobs = list(jobs_col.find({}))
                            user_states[user].update({'jobs':jobs,'page':0,'category':'all'})
                            send_jobs_page(user)
                        elif text=='3':
                            fav = favs_col.find_one({"user_id":user}) or {"categories":[]}  # sync for simplicity
                            send_whatsapp(user, f"Vos favoris: {fav.get('categories',[])}")
                        else:
                            send_whatsapp(user, "Commande invalide. Envoyez MENU.")
                    elif state=='AWAIT_CATEGORY':
                        cat = text.title()
                        if cat in categories:
                            jobs = list(jobs_col.find({"category":cat}))
                            user_states[user].update({'jobs':jobs,'page':0,'category':cat})
                            send_jobs_page(user)
                        else:
                            send_whatsapp(user, "Catégorie inconnue.")
                    elif state=='AWAIT_NAV':
                        if text=='P': user_states[user]['page']-=1; send_jobs_page(user)
                        elif text=='N': user_states[user]['page']+=1; send_jobs_page(user)
                        elif text=='M': show_menu(user)
                        else: send_whatsapp(user,"Nav invalide.")
    return jsonify(),200

@app.route('/health', methods=['GET'])
def health():
    try:
        mongo.admin.command('ping')
        return jsonify(status='ok'),200
    except:
        return jsonify(status='fail'),500

# ---------- Notifications Loop ----------
def notify_loop():
    while True:
        pending = list(jobs_col.find({"is_notified":False}))
        for job in pending:
            cat = job['category']
            for sub in favs_col.find({"categories":cat}):
                to = sub['user_id']
                text = "🚨 Nouvelle offre dans vos favoris !" + random.choice(templates).format(
                    title=job['title'],company=job['company'],location=job['location'],resume=job['description']
                )
                send_whatsapp(to, text)
            jobs_col.update_one({"_id":job['_id']},{"$set":{"is_notified":True,"notifiedAt":datetime.utcnow()}})
        asyncio.sleep(60)

if __name__=='__main__':
    Config.validate()
    # Start notification thread
    threading.Thread(target=notify_loop,daemon=True).start()
    serve(app,host='0.0.0.0',port=Config.PORT)
