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

# Logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler('bot_debug.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)

# Config\class Config:
    VERIFY_TOKEN = 'claudelAI223'
    APP_SECRET = b'7c61b31a0530bc3cc28f632a9b3e32be'
    MONGO_URI = offreBot.MONGO_URI
    WA_PHONE_ID = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    PORT = int(os.getenv('PORT',10000))
    BASE_URL = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages"

    @classmethod
    def validate(cls):
        missing=[k for k in ['MONGO_URI','WA_PHONE_ID','WA_ACCESS_TOKEN'] if not getattr(cls,k)]
        if missing: raise ValueError(f"Missing config: {missing}")

# DB
mongo=MongoClient(Config.MONGO_URI,tlsCAFile=certifi.where())
db=mongo.job_database
jobs_col=db.christ
favs_col=db.user_favorites

# Constants
CATEGORIES=[
    "Informatique / IT","Finance / Comptabilité","Communication / Marketing",
    "Conseil / Stratégie","Transport / Logistique","Ingénierie / BTP",
    "Santé / Médical","Éducation / Formation","Ressources humaines",
    "Droit / Juridique","Environnement","Alternance / Stage","Remote","Autre"
]
ROWS_PER_PAGE=5

# Utils
def normalize_number(num:str)->str:
    n=num.lstrip('+')
    if not re.match(r'^\d{10,15}$',n): raise ValueError("Invalid number")
    return f"+{n}"

def verify_signature(pkt:bytes,sig:str)->bool:
    dig=hmac.new(Config.APP_SECRET,pkt,hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={dig}",sig)

def create_message(to:str,content:dict)->dict:
    return {"messaging_product":"whatsapp","recipient_type":"individual","to":to,**content}

def send_whatsapp(to:str,content:dict):
    try:
        payload=create_message(to,content)
        headers={"Authorization":f"Bearer {Config.WA_ACCESS_TOKEN}","Content-Type":"application/json"}
        r=requests.post(Config.BASE_URL,headers=headers,json=payload)
        if r.status_code!=200: logger.error(f"Error send: {r.text}")
    except Exception as e:
        logger.error(f"send error: {e}")

# State
user_states={}
def reset_state(u:str): user_states.pop(u,None)

# Templates
def text_message(txt:str)->dict:
    return {"type":"text","text":{"body":txt}}

# Categories as list type
def show_categories_page(user:str,page:int=0):
    start=page*ROWS_PER_PAGE
    end=start+ROWS_PER_PAGE
    rows=[]
    for i in range(start,min(end,len(CATEGORIES))):
        rows.append({"id":f"CAT_{i}","title":CATEGORIES[i]})
    # nav rows
    if page>0: rows.append({"id":f"CAT_PAGE_{page-1}","title":"◀️ Précédent"})
    if end<len(CATEGORIES): rows.append({"id":f"CAT_PAGE_{page+1}","title":"Suivant ▶️"})
    rows.append({"id":"MAIN_MENU","title":"🔙 Menu"})

    send_whatsapp(user,{"type":"interactive","interactive":{
        "type":"list",
        "body":{"text":"Choisissez une catégorie :"},
        "action":{
            "button":"Voir options",
            "sections":[{"title":"Catégories","rows":rows}]
        }
    }})
    user_states[user]={"state":"CATEGORY_SELECTION","cat_page":page}

# Favorites
def show_favorites(user:str):
    favs=list(favs_col.find({"user":user}))
    if not favs: send_whatsapp(user,text_message("Aucun favori."))
    else:
        for f in favs: send_whatsapp(user,text_message(f"⭐ {f.get('title')} - {f.get('url')}"))
    send_whatsapp(user,{"type":"interactive","interactive":{
        "type":"button","body":{"text":"Retour?"},"action":{"buttons":[{"type":"reply","reply":{"id":"MAIN_MENU","title":"🔙 Menu"}}]}
    }})
    user_states[user]={"state":"MAIN_MENU"}

# Start
def start_flow(user:str):
    reset_state(user)
    send_whatsapp(user,{"type":"interactive","interactive":{
        "type":"button",
        "body":{"text":"🌟 Bienvenue sur JobBot!"},
        "action":{"buttons":[
            {"type":"reply","reply":{"id":"BROWSE","title":"Parcourir offres"}},
            {"type":"reply","reply":{"id":"FAVORITES","title":"Mes favoris"}}
        ]}
    }})
    user_states[user]={"state":"MAIN_MENU"}

# Webhook
@app.route('/webhook',methods=['GET'])
def webhook_verify():
    if request.args.get('hub.mode')=='subscribe' and request.args.get('hub.verify_token')==Config.VERIFY_TOKEN:
        return request.args.get('hub.challenge'),200
    return "Forbidden",403

@app.route('/webhook',methods=['POST'])
def webhook_receive():
    try:
        pkt=request.get_data()
        if not verify_signature(pkt,request.headers.get('X-Hub-Signature-256','')): return jsonify({"status":"invalid"}),403
        data=request.json
        for e in data.get('entry',[]):
            for ch in e.get('changes',[]):
                for m in ch.get('value',{}).get('messages',[]): process_message(m)
        return jsonify({"status":"ok"}),200
    except Exception as e:
        logger.error(f"webhook error: {e}")
        return jsonify({"status":"error"}),500

# Process
def process_message(msg:dict):
    try:
        user=normalize_number(msg['from'])
        t=msg.get('type')
        if t=='text': handle_text(user,msg['text']['body'].strip())
        elif t=='interactive': handle_interactive(user,msg['interactive'])
    except Exception as e: logger.error(f"proc error: {e}")

# Handle text
def handle_text(user:str,txt:str):
    cmd=txt.upper(); st=user_states.get(user,{}).get('state')
    logger.debug(f"TXT {cmd}|ST {st}")
    if cmd in ['/START','START']: return start_flow(user)
    if st=='MAIN_MENU':
        if cmd=='BROWSE': return show_categories_page(user,0)
        if cmd=='FAVORITES': return show_favorites(user)
    return start_flow(user)

# Handle interactive
def handle_interactive(user:str,inter:dict):
    if inter.get('type')=='list_reply':
        sel=inter['list_reply']['id']
        if sel=='MAIN_MENU': return start_flow(user)
        if sel.startswith('CAT_PAGE_'): return show_categories_page(user,int(sel.split('_')[2]))
        if sel.startswith('CAT_'): return send_jobs_page(user,sel.split('_')[1],0)
    if inter.get('type')=='button_reply':
        bid=inter['button_reply']['id']
        return handle_text(user,bid)

# Send jobs
def send_jobs_page(user:str,category:str,page:int=0):
    try:
        cat=CATEGORIES[int(category)]; q={'category':cat}
        total=jobs_col.count_documents(q); per=ROWS_PER_PAGE
        jobs=list(jobs_col.find(q).sort('created_at',-1).skip(page*per).limit(per))
        if not jobs: return send_whatsapp(user,text_message('Aucune offre'))
        for j in jobs:
            msg=f"📌 {j.get('title')}\n🏢 {j.get('company')}\n📍 {j.get('location')}\n🔗 {j.get('url')}"
            send_whatsapp(user,text_message(msg)); time.sleep(0.5)
        # buttons
        btns=[]
        if page>0: btns.append({"type":"reply","reply":{"id":f"PAGE_{category}_{page-1}","title":"◀️ Précédent"}})
        if (page+1)*per<total: btns.append({"type":"reply","reply":{"id":f"PAGE_{category}_{page+1}","title":"Suivant ▶️"}})
        btns.append({"type":"reply","reply":{"id":"MAIN_MENU","title":"🔙 Menu"}})
        send_whatsapp(user,{"type":"interactive","interactive":{
            "type":"button","body":{"text":f"Page {page+1}"},"action":{"buttons":btns}
        }})
        user_states[user]={"state":"BROWSING","category":category,"page":page}
    except Exception as e: logger.error(f"jobs error: {e}")

# Main
if __name__=='__main__':
    Config.validate()
    jobs_col.update_many({'category':'Rouder'},{'$set':{'category':'Remote'}})
    serve(app,host='0.0.0.0',port=Config.PORT)
