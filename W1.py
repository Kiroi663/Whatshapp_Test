import os
import hmac
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from pymongo import MongoClient
import certifi

app = Flask(__name__)

# Configuration
CONFIG = {
    "WA_PHONE_ID": offreBot.WA_PHONE_ID,
    "WA_ACCESS_TOKEN": offreBot.WA_ACCESS_TOKEN,
    "WEBHOOK_SECRET": "claudelAI223",
    "MONGO_URI": offreBot.MONGO_URI,
    "PORT": int(os.getenv("PORT", 10000))
}

class WhatsAppJobBot:
    def __init__(self):
        self.db_client = MongoClient(
            CONFIG["MONGO_URI"],
            tls=True,
            tlsCAFile=certifi.where()
        )
        self.db = self.db_client["job_bot_db"]
        self.jobs = self.db["jobs"]
        self.users = self.db["users"]
        self.user_activity = {}

    def init_db(self):
        """Initialize database indexes"""
        self.users.create_index("user_id", unique=True)
        self.jobs.create_index([("category", 1), ("valid_until", -1)])

    # Webhook Verification
    def verify_webhook(self, signature, payload):
        """Verify WhatsApp webhook signature"""
        if not signature:
            return False
            
        secret = CONFIG["WEBHOOK_SECRET"].encode()
        expected_hash = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected_hash}", signature)

    # Message Processing
    def process_message(self, message):
        """Process incoming WhatsApp message"""
        user_id = message["from"]
        msg_type = message["type"]

        self.update_user_activity(user_id)

        if msg_type == "text":
            text = message["text"]["body"].lower()
            return self.handle_text_message(user_id, text)
            
        return False

    # User Management
    def update_user_activity(self, user_id):
        """Update user last activity timestamp"""
        now = datetime.utcnow()
        self.user_activity[user_id] = now
        
        self.users.update_one(
            {"user_id": user_id},
            {"$set": {"last_activity": now}},
            upsert=True
        )

    # Job Management
    def get_relevant_jobs(self, user_id, category=None, limit=5, page=0):
        """Get jobs relevant to user"""
        query = {"is_active": True}
        
        if category:
            query["category"] = category
        else:
            user = self.users.find_one({"user_id": user_id})
            if user and user.get("preferences"):
                query["category"] = {"$in": user["preferences"].get("categories", [])}

        return list(self.jobs.find(query).sort("posted_at", -1).skip(page * limit).limit(limit))

    # WhatsApp API Communication
    def send_whatsapp_message(self, user_id, content):
        """Send message via WhatsApp API"""
        # In production, you would actually call the WhatsApp API here
        print(f"Would send to {user_id}: {content}")
        return True

    # Command Handlers
    def handle_text_message(self, user_id, text):
        """Handle text commands"""
        if text == "start":
            return self.send_welcome_message(user_id)
        elif text == "menu":
            return self.show_main_menu(user_id)
        elif text == "jobs":
            return self.show_job_categories(user_id)
        else:
            return self.send_help_message(user_id)

    def send_welcome_message(self, user_id):
        """Send welcome message"""
        return self.send_whatsapp_message(user_id, {
            "header": "👋 Welcome to JobBot!",
            "body": "Available commands:\n- menu: Show main menu\n- jobs: Browse jobs\n- help: Show help",
            "buttons": [
                {"type": "reply", "title": "📋 Menu", "id": "show_menu"},
                {"type": "reply", "title": "🔍 Jobs", "id": "show_jobs"}
            ]
        })

# Initialize bot
bot = WhatsAppJobBot()
bot.init_db()

# Flask Routes
@app.route('/webhook', methods=['GET'])
def webhook_verification():
    if request.args.get('hub.mode') == 'subscribe' and \
       request.args.get('hub.verify_token') == CONFIG["WEBHOOK_SECRET"]:
        return request.args.get('hub.challenge'), 200
    return "Verification failed", 403

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    signature = request.headers.get('X-Hub-Signature-256')
    if not bot.verify_webhook(signature, request.data):
        return jsonify({"status": "invalid signature"}), 403

    data = request.json
    entry = data.get('entry', [{}])[0]
    changes = entry.get('changes', [{}])[0].get('value', {})

    if 'messages' in changes:
        bot.process_message(changes['messages'][0])
    elif 'interactive' in changes:
        # Handle interactive messages here
        pass

    return jsonify({"status": "success"}), 200

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

@app.route('/')
def home():
    return jsonify({"message": "JobBot API is running"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=CONFIG["PORT"])
