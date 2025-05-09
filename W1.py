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
        missing = [k for k in ['MONGO_URI','WA_PHONE_ID','WA_ACCESS_TOKEN'] if not getattr(cls,k)]
        if missing:
            raise ValueError(f"Configuration manquante: {', '.join(missing)}")

# ---------- Database ----------
mongo = MongoClient(Config.MONGO_URI, tlsCAFile=certifi.where())
db = mongo.job_database
jobs_col = db.christ
favs_col = db.user_favorites

# ---------- Constantes ----------
CATEGORIES = [
    "Informatique / IT","Finance / Comptabilité","Communication / Marketing",
    "Conseil / Stratégie","Transport / Logistique","Ingénierie / BTP",
    "Santé / Médical","Éducation / Formation","Ressources humaines",
    "Droit / Juridique","Environnement","Alternance / Stage","Remote","Autre"
]
ROWS_PER_PAGE = 5

# ---------- Utilitaires ----------
def normalize_number(number: str) -> str:
    number = number.lstrip('+')
    if not re.match(r'^\d{10,15}$', number): raise ValueError("Format invalide")
    return f"+{number}"

def verify_signature(payload: bytes, signature: str) -> bool:
    digest = hmac.new(Config.APP_SECRET, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature)

def create_message(to: str, content: dict) -> dict:
    return {"messaging_product":"whatsapp","recipient_type":"individual","to":to,**content}

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

# ---------- États utilisateur ----------
user_states = {}
def reset_state(user: str): user_states.pop(user,None)

# ---------- Templates ----------
def text_message(text: str) -> dict:
    return {"type":"text","text":{"body":text}}

def show_favorites(user: str):
    # Exemple basique, à adapter
    favs = list(favs_col.find({"user": user}))
    if not favs:
        send_whatsapp(user, text_message("Vous n'avez pas encore de favoris."))
    else:
        for fav in favs:
            send_whatsapp(user, text_message(f"⭐ {fav.get('title')} - {fav.get('url')}"))
    send_whatsapp(user, {"type":"interactive","interactive":{
        "type":"button","body":{"text":"Que voulez-vous faire?"},"action":{"buttons":[
            {"type":"reply","reply":{"id":"MAIN_MENU","title":"🔙 Menu"}}
        ]}
    }})
    user_states[user] = {"state":"MAIN_MENU"}

# ---------- CATÉGORIES COMME BOUTONS ----------
def show_categories_page(user: str, page: int = 0):
    start = page * ROWS_PER_PAGE
    end = start + ROWS_PER_PAGE
    buttons = []
    for i in range(start, min(end, len(CATEGORIES))):
        title = CATEGORIES[i]
        truncated = (title[:25] + '...') if len(title)>28 else title
        buttons.append({"type":"reply","reply":{"id":f"CAT_{i}","title":truncated}})
    if page>0:
        buttons.append({"type":"reply","reply":{"id":f"CAT_PAGE_{page-1}","title":"◀️ Précédent"}})
    if end < len(CATEGORIES):
        buttons.append({"type":"reply","reply":{"id":f"CAT_PAGE_{page+1}","title":"Suivant ▶️"}})
    buttons.append({"type":"reply","reply":{"id":"MAIN_MENU","title":"🔙 Menu"}})

    send_whatsapp(user,{"type":"interactive","interactive":{
        "type":"button","body":{"text":"Choisissez une catégorie :"},"action":{"buttons":buttons}
    }})
    user_states[user] = {"state":"CATEGORY_SELECTION","cat_page":page}

# ---------- DÉMARRAGE ----------
def start_flow(user: str):
    reset_state(user)
    buttons = [
        {"type":"reply","reply":{"id":"BROWSE","title":"Parcourir les offres"}},
        {"type":"reply","reply":{"id":"FAVORITES","title":"Mes favoris"}}
    ]
    send_whatsapp(user,{"type":"interactive","interactive":{
        "type":"button","body":{"text":"🌟 Bienvenue sur JobBot!"},"action":{"buttons":buttons}
    }})
    user_states[user] = {"state":"MAIN_MENU"}

# ---------- WEBHOOK ----------
@app.route('/webhook',methods=['GET'])
def webhook_verify():
    if request.args.get('hub.mode')=='subscribe' and request.args.get('hub.verify_token')==Config.VERIFY_TOKEN:
        return request.args.get('hub.challenge'),200
    return "Forbidden",403

@app.route('/webhook',methods=['POST'])
def webhook_receive():
    try:
        payload=request.get_data()
        if not verify_signature(payload,request.headers.get('X-Hub-Signature-256','')):
            return jsonify({"status":"invalid signature"}),403
        data=request.json
        for entry in data.get('entry',[]):
            for change in entry.get('changes',[]):
                for msg in change.get('value',{}).get('messages',[]): process_message(msg)
        return jsonify({"status":"success"}),200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status":"error"}),500

# ---------- TRAITEMENT ----------
def process_message(msg: dict):
    try:
        user=normalize_number(msg['from'])
        t=msg.get('type')
        if t=='text': handle_text(user,msg['text']['body'].strip())
        elif t=='interactive': handle_interactive(user,msg['interactive'])
    except Exception as e:
        logger.error(f"Process error: {e}")

# ---------- TEXTE ----------
def handle_text(user: str, txt: str):
    cmd=txt.upper(); st=user_states.get(user,{}).get('state')
    logger.debug(f"TXT {cmd}|STATE {st}")
    if cmd in ['/START','START']: return start_flow(user)
    if st=='MAIN_MENU':
        if cmd=='BROWSE': return show_categories_page(user,0)
        if cmd=='FAVORITES': return show_favorites(user)
    return start_flow(user)

# ---------- INTERACTIONS ----------
def handle_interactive(user: str, inter: dict):
    it=inter.get('type')
    if it=='button_reply':
        bid=inter['button_reply']['id']
        if bid=='BROWSE': return show_categories_page(user,0)
        if bid=='MAIN_MENU': return start_flow(user)
        if bid.startswith('CAT_PAGE_'): return show_categories_page(user,int(bid.split('_')[2]))
        if bid.startswith('CAT_'): return send_jobs_page(user,bid.split('_')[1],0)
        if bid=='FAVORITES': return show_favorites(user)

# ---------- OFFRES ----------
def send_jobs_page(user: str, category: str, page: int=0):
    try:
        cat=CATEGORIES[int(category)]; q={'category':cat}
        total=jobs_col.count_documents(q); per=ROWS_PER_PAGE
        jobs=list(jobs_col.find(q).sort('created_at',-1).skip(page*per).limit(per))
        if not jobs: return send_whatsapp(user,text_message('Aucune offre'))
        for j in jobs:
            txt=f"📌 {j.get('title','')}\n🏢 {j.get('company','')}\n📍 {j.get('location','')}\n🔗 {j.get('url','#')}"
            send_whatsapp(user,text_message(txt)); time.sleep(0.5)
        btns=[]
        if page>0: btns.append({'type':'reply','reply':{'id':f'PAGE_{category}_{page-1}','title':'◀️ Précédent'}})
        if (page+1)*per<total: btns.append({'type':'reply','reply':{'id':f'PAGE_{category}_{page+1}','title':'Suivant ▶️'}})
        btns.append({'type':'reply','reply':{'id':'MAIN_MENU','title':'🔙 Menu'}})
        send_whatsapp(user,{"type":"interactive","interactive":{
            'type':'button','body':{'text':f'Page {page+1}'},'action':{'buttons':btns}
        }})
        user_states[user]={'state':'BROWSING','category':category,'page':page}
    except Exception as e:
        logger.error(f"Jobs error: {e}"); send_whatsapp(user,text_message('Erreur'))

# ---------- MAIN ----------
if __name__=='__main__':
    Config.validate()
    jobs_col.update_many({'category':'Rouder'},{'$set':{'category':'Remote'}})
    serve(app,host='0.0.0.0',port=Config.PORT)
