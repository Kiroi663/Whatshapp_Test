import os
import hmac
import hashlib
import json
import logging
import random
import asyncio
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi
from waitress import serve

from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import UserNotParticipantError
from motor.motor_asyncio import AsyncIOMotorClient

import offreBot

# ---------- Logging ----------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ---------- Flask App for WhatsApp Webhook ----------
app = Flask(__name__)

class Config:
    # WhatsApp webhook
    VERIFY_TOKEN = 'claudelAI223'
    APP_SECRET   = b'7c61b31a0530bc3cc28f632a9b3e32be'
    MONGO_URI    = offreBot.MONGO_URI
    WA_PHONE_ID  = offreBot.WA_PHONE_ID
    WA_ACCESS_TOKEN = offreBot.WA_ACCESS_TOKEN
    PORT         = int(os.getenv('PORT', 10000))

    @classmethod
    def validate(cls):
        missing = []
        if not cls.MONGO_URI:
            missing.append('MONGODB_URI')
        if not cls.WA_PHONE_ID:
            missing.append('WHATSAPP_PHONE_ID')
        if not cls.WA_ACCESS_TOKEN:
            missing.append('WHATSAPP_ACCESS_TOKEN')
        if missing:
            raise ValueError(f"Missing configuration: {', '.join(missing)}")


def verify_signature(payload: bytes, signature_header: str) -> bool:
    logger.debug(f"Verifying signature header: {signature_header}")
    if not signature_header:
        logger.error('No signature header provided')
        return False

    if signature_header.startswith('sha256='):
        algo = hashlib.sha256
        logger.debug('Using SHA256')
        received = signature_header.split('=',1)[1]
    elif signature_header.startswith('sha1='):
        algo = hashlib.sha1
        logger.debug('Using SHA1')
        received = signature_header.split('=',1)[1]
    else:
        logger.error('Invalid signature format')
        return False

    expected = hmac.new(Config.APP_SECRET, payload, digestmod=algo).hexdigest()
    valid = hmac.compare_digest(received, expected)
    if not valid:
        logger.debug(f'Received: {received}, Expected: {expected}')
    return valid

@app.route('/webhook', methods=['GET'])
def webhook_verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    chal  = request.args.get('hub.challenge')
    logger.debug(f"Verify attempt mode={mode}, token={token}")
    if mode=='subscribe' and token==Config.VERIFY_TOKEN:
        return chal, 200
    return 'Verification failed', 403

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    payload   = request.get_data()
    sig_header= request.headers.get('X-Hub-Signature-256') or request.headers.get('X-Hub-Signature')
    logger.debug(f"Payload: {payload}\nSig: {sig_header}")
    if not verify_signature(payload, sig_header):
        return jsonify(error='Access denied'), 403
    data = json.loads(payload)
    logger.info(f"WhatsApp webhook received: {data}")
    # TODO: process WhatsApp message
    return jsonify(status='Message processed'), 200

@app.route('/health', methods=['GET'])
def health_check():
    try:
        client = MongoClient(Config.MONGO_URI, tls=True, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        return jsonify(status='healthy', database='connected', timestamp=datetime.utcnow().isoformat()), 200
    except Exception as e:
        logger.error(f"Health failed: {e}")
        return jsonify(status='unhealthy', database='disconnected', error=str(e)), 500

# ---------- Telegram JobBot ----------
class JobBot:
    def __init__(self):
        self.bot = TelegramClient("bot", offreBot.API_ID, offreBot.API_HASH).start(bot_token=offreBot.TELEGRAM_BOT_TOKEN)
        self.mongo = AsyncIOMotorClient(offreBot.MONGO_URI)
        self.db = self.mongo["job_database"]
        self.jobs = self.db["christ"]
        self.favs = self.db["user_favorites"]
        self.REQUIRED_GROUP = "JobFinderHub001"
        self.GROUP_LINK = f"https://t.me/{self.REQUIRED_GROUP}"
        self.templates = [
            "📌 *{title}* chez *{company}* à {location}.\n{resume}\n",
            "🚀 Opportunité : *{title}*!\nEntreprise : *{company}*\n📍 {location}\n👉 {resume}\n",
            "🎯 Poste : *{title}*\n🏢 Employeur : *{company}*\n📍 {location}\n📜 {resume}\n"
        ]
        self.categories = {...}  # copier liste existante
        self.user_states = {}
        self.setup_handlers()
        self.bot.loop.create_task(self.hatch_op_loop())

    def setup_handlers(self):
        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start(event): await self.handle_start(event)
        # copier tous les handlers de l'ancien code...

    # copier toutes les méthodes is_group_member, handle_start, etc.
    # ...
    async def hatch_op_loop(self, interval: int = 60):
        while True:
            try: await self.hatch_op()
            except Exception as e: logger.error(f"HatchOp error: {e}")
            await asyncio.sleep(interval)

    def run(self):
        logger.info(f"Starting Telegram JobBot, group={self.GROUP_LINK}")
        self.bot.run_until_disconnected()

# ---------- Launcher ----------
def start_flask():
    Config.validate()
    serve(app, host='0.0.0.0', port=Config.PORT)

if __name__ == '__main__':
    # Run Flask in a background thread
    Thread(target=start_flask, daemon=True).start()
    # Run Telegram bot (blocking)
    JobBot().run()
