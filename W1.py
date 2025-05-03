import os
import hmac
import hashlib
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import certifi
import offreBot

app = Flask(__name__)

# Configuration
CONFIG = {
    "WA_PHONE_ID": offreBot.WA_PHONE_ID,
    "WA_ACCESS_TOKEN": offreBot.WA_ACCESS_TOKEN,
    "WEBHOOK_SECRET": "claudelAI223",
    "MONGO_URI": offreBot.MONGO_URI,
    "PORT": int(os.getenv("PORT", 3000))
}

class WhatsAppJobBot:
    def __init__(self):
        self.db_client = AsyncIOMotorClient(
            CONFIG["MONGO_URI"],
            tls=True,
            tlsCAFile=certifi.where()
        )
        self.db = self.db_client["job_bot_db"]
        self.jobs = self.db["jobs"]
        self.users = self.db["users"]
        self.user_activity = {}

    async def init_db(self):
        """Initialize database indexes"""
        await self.users.create_index("user_id", unique=True)
        await self.jobs.create_index([("category", 1), ("valid_until", -1)])

    # Webhook Verification
    def verify_webhook(self, signature, payload):
        """Verify WhatsApp webhook signature"""
        if not signature:
            return False
            
        secret = CONFIG["WEBHOOK_SECRET"].encode()
        expected_hash = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected_hash}", signature)

    # Message Processing
    async def process_message(self, message):
        """Process incoming WhatsApp message"""
        user_id = message["from"]
        msg_type = message["type"]

        await self.update_user_activity(user_id)

        if msg_type == "text":
            text = message["text"]["body"].lower()
            return await self.handle_text_message(user_id, text)
            
        return False

    # User Management
    async def update_user_activity(self, user_id):
        """Update user last activity timestamp"""
        now = datetime.utcnow()
        self.user_activity[user_id] = now
        
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"last_activity": now}},
            upsert=True
        )

    async def get_active_users(self, since=timedelta(days=1)):
        """Get users active since given time delta"""
        cutoff = datetime.utcnow() - since
        return await self.users.find({
            "last_activity": {"$gte": cutoff}
        }).to_list(None)

    # Job Management
    async def get_relevant_jobs(self, user_id, category=None, limit=5, page=0):
        """Get jobs relevant to user"""
        query = {"is_active": True}
        
        if category:
            query["category"] = category
        else:
            user = await self.users.find_one({"user_id": user_id})
            if user and user.get("preferences"):
                query["category"] = {"$in": user["preferences"].get("categories", [])}

        return await self.jobs.find(query).sort("posted_at", -1).skip(page * limit).limit(limit).to_list(None)

    async def send_job_notification(self, user_id, job):
        """Send job notification to user"""
        message = {
            "header": f"📌 {job['title']}",
            "body": (
                f"🏢 Company: {job['company']}\n"
                f"📍 Location: {job['location']}\n"
                f"📅 Valid until: {job['valid_until'].strftime('%d/%m/%Y')}"
            ),
            "buttons": [
                {"type": "reply", "title": "📨 Apply", "id": f"apply_{job['_id']}"},
                {"type": "reply", "title": "ℹ️ Details", "id": f"details_{job['_id']}"}
            ]
        }
        
        return await self.send_whatsapp_message(user_id, message)

    # WhatsApp API Communication
    async def send_whatsapp_message(self, user_id, content):
        """Send message via WhatsApp API"""
        if not await self.is_user_active(user_id):
            return False

        # In production, you would actually call the WhatsApp API here
        print(f"Would send to {user_id}: {content}")
        return True

    # Command Handlers
    async def handle_text_message(self, user_id, text):
        """Handle text commands"""
        commands = {
            "start": self.send_welcome_message,
            "menu": self.show_main_menu,
            "jobs": self.show_job_categories
        }
        
        handler = commands.get(text, self.send_help_message)
        return await handler(user_id)

    async def send_welcome_message(self, user_id):
        """Send welcome message"""
        return await self.send_whatsapp_message(user_id, {
            "header": "👋 Welcome to JobBot!",
            "body": "Available commands:\n- menu: Show main menu\n- jobs: Browse jobs\n- help: Show help",
            "buttons": [
                {"type": "reply", "title": "📋 Menu", "id": "show_menu"},
                {"type": "reply", "title": "🔍 Jobs", "id": "show_jobs"}
            ]
        })

    # Notification Service
    async def run_notification_service(self):
        """Background notification service"""
        while True:
            try:
                await self.check_new_jobs()
                await asyncio.sleep(3600)  # Check hourly
            except Exception as e:
                print(f"Notification error: {str(e)}")
                await asyncio.sleep(300)

    async def check_new_jobs(self):
        """Check and notify about new jobs"""
        new_jobs = await self.jobs.find({
            "is_notified": False,
            "valid_until": {"$gt": datetime.utcnow()}
        }).to_list(None)

        for job in new_jobs:
            await self.notify_subscribers(job)
            await self.jobs.update_one(
                {"_id": job["_id"]},
                {"$set": {"is_notified": True}}
            )

# Flask Routes
bot = WhatsAppJobBot()

@app.route('/webhook', methods=['GET'])
def webhook_verification():
    if request.args.get('hub.mode') == 'subscribe' and \
       request.args.get('hub.verify_token') == CONFIG["WEBHOOK_SECRET"]:
        return request.args.get('hub.challenge'), 200
    return "Verification failed", 403

@app.route('/webhook', methods=['POST'])
async def webhook_handler():
    signature = request.headers.get('X-Hub-Signature-256')
    if not bot.verify_webhook(signature, request.data):
        return jsonify({"status": "invalid signature"}), 403

    data = request.json
    entry = data.get('entry', [{}])[0]
    changes = entry.get('changes', [{}])[0].get('value', {})

    if 'messages' in changes:
        await bot.process_message(changes['messages'][0])
    elif 'interactive' in changes:
        await bot.process_interaction(changes['interactive'])

    return jsonify({"status": "success"}), 200

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

# Startup
async def initialize():
    await bot.init_db()
    asyncio.create_task(bot.run_notification_service())

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(initialize())
    app.run(host='0.0.0.0', port=CONFIG["PORT"])
