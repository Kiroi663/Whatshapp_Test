import os
import hmac
import hashlib
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import offreBot
import certifi

app = Flask(__name__)

class WhatsAppJobBot:
    def __init__(self):
        # Configuration WhatsApp
        self.phone_id = offreBot.WA_PHONE_ID
        self.access_token = offreBot.WA_ACCESS_TOKEN
        self.webhook_secret = "claudelAI223"

        # Base de données
        # Modifiez la connexion MongoDB avec ces paramètres
        self.db_client = AsyncIOMotorClient(
            offreBot.MONGO_URI,
            tls=True,
            tlsAllowInvalidCertificates=False,  # À n'utiliser qu'en dev
            tlsCAFile=certifi.where(),

        )
        self.db = self.db_client["job_database"]
        self.jobs = self.db["christ"]
        self.users = self.db["utilisateurs"]

        # Cache d'activité
        self.user_activity = {}

    async def init(self):
        """Initialisation asynchrone"""
        await self.db.users.create_index("user_id", unique=True)
        await self.db.jobs.create_index([("metadata.category", 1), ("status.valid_until", -1)])

    # --- Gestion Webhook ---
    def verify_signature(self, payload):
        """Vérification de la signature WhatsApp"""
        signature = request.headers.get("X-Hub-Signature-256", "").split("sha256=")[-1]
        local_hash = hmac.new(self.webhook_secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(local_hash, signature)

    async def handle_webhook(self, data):
        """Traite les événements entrants"""
        if not self.verify_signature(request.data):
            return False

        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0].get("value", {})

        if "messages" in changes:
            return await self.process_message(changes["messages"][0])
        elif "interactive" in changes:
            return await self.process_interaction(changes["interactive"])
        

        return True

    # --- Traitement des messages ---
    async def process_message(self, message):
        """Traite les messages utilisateur"""
        user_id = message["from"]
        msg_type = message["type"]

        await self.update_user_activity(user_id)

        if msg_type == "text":
            text = message["text"]["body"].lower()
            return await self.handle_text(user_id, text)
        
        return False

    async def process_interaction(self, interaction):
        """Gère les interactions boutons"""
        user_id = interaction["from"]
        action = interaction["button_reply"]["id"]

        await self.update_user_activity(user_id)

        if action.startswith("category_"):
            return await self.show_category_jobs(user_id, action.split("_")[1])
        elif action == "show_more":
            return await self.show_more_jobs(user_id)
        elif action.startswith("apply_"):
            return await self.handle_application(user_id, action.split("_")[1])
        
        return False

    # --- Gestion Utilisateurs ---
    async def update_user_activity(self, user_id):
        """Met à jour l'activité utilisateur"""
        now = datetime.utcnow()
        self.user_activity[user_id] = now
        
        await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"last_activity": now}},
            upsert=True
        )

    async def is_active_user(self, user_id):
        """Vérifie si la conversation est active"""
        last_active = self.user_activity.get(user_id)
        if not last_active:
            user = await self.db.users.find_one({"user_id": user_id})
            last_active = user.get("last_activity") if user else None
        
        return last_active and (datetime.utcnow() - last_active) < timedelta(hours=24)

    # --- Gestion des Offres ---
    async def get_user_jobs(self, user_id, category=None, page=0):
        """Récupère les offres pertinentes"""
        query = {"status.is_active": True}
        if category:
            query["metadata.category"] = category

        user = await self.db.users.find_one({"user_id": user_id})
        if user and user.get("preferences"):
            query.update({
                "metadata.category": {"$in": user["preferences"].get("categories", [])},
                "location.city": {"$in": user["preferences"].get("locations", [])}
            })

        return await self.jobs.find(query).sort("created_at", -1).skip(page * 5).limit(5).to_list(None)

    async def format_job_message(self, job):
        """Formate un message d'offre"""
        return {
            "header": f"📌 {job['title']['fr']}",
            "body": (
                f"🏢 Entreprise : {job['company']}\n"
                f"📍 Lieu : {job['location']['city']}\n"
                f"📅 Valide jusqu'au : {job['status']['valid_until'].strftime('%d/%m/%Y')}"
            ),
            "buttons": [
                {"type": "reply", "title": "📨 Postuler", "id": f"apply_{job['_id']}"},
                {"type": "reply", "title": "ℹ️ Détails", "id": f"details_{job['_id']}"}
            ]
        }

    # --- Envoi de messages ---
    async def send_whatsapp_message(self, user_id, content):
        """Envoie un message via l'API WhatsApp"""
        if not await self.is_active_user(user_id):
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": user_id,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {"type": "text", "text": content["header"]},
                "body": {"text": content["body"]},
                "action": {"buttons": content.get("buttons", [])}
            }
        }

        # Envoi réel désactivé pour l'exemple
        print(f"Message envoyé à {user_id}: {payload}")
        return True

    # --- Handlers d'interface ---
    async def handle_text(self, user_id, text):
        """Gère les messages texte"""
        if text == "/start":
            return await self.send_welcome(user_id)
        elif text == "1":
            return await self.show_main_menu(user_id)
        elif text == "2":
            return await self.show_categories(user_id)
        return await self.send_default_response(user_id)

    async def send_welcome(self, user_id):
        """Message de bienvenue"""
        return await self.send_whatsapp_message(user_id, {
            "header": "👋 Bienvenue sur JobFinder!",
            "body": (
                "Trouvez les meilleures offres d'emploi\n\n"
                "1. Voir les nouvelles offres\n"
                "2. Parcourir par catégorie\n"
                "3. Gérer mes alertes"
            )
        })

    async def show_main_menu(self, user_id):
        """Affiche le menu principal"""
        return await self.send_whatsapp_message(user_id, {
            "header": "📋 Menu Principal",
            "body": "Sélectionnez une option :",
            "buttons": [
                {"type": "reply", "title": "🔍 Nouveaux jobs", "id": "show_new"},
                {"type": "reply", "title": "📚 Catégories", "id": "show_cats"},
                {"type": "reply", "title": "⚙️ Préférences", "id": "show_prefs"}
            ]
        })

    # --- Service de Notifications ---
    async def notification_service(self):
        """Service de notifications automatiques"""
        while True:
            try:
                await self.check_and_notify()
                await asyncio.sleep(3600)  # Toutes les heures
            except Exception as e:
                print(f"Erreur notification_service: {str(e)}")
                await asyncio.sleep(300)

    async def check_and_notify(self):
        """Vérifie et envoie les notifications"""
        new_jobs = await self.jobs.find({
            "status.is_notified": False,
            "status.valid_until": {"$gt": datetime.utcnow()}
        }).to_list(None)

        for job in new_jobs:
            await self.notify_job_subscribers(job)
            await self.jobs.update_one(
                {"_id": job["_id"]},
                {"$set": {"status.is_notified": True}}
            )

    async def notify_job_subscribers(self, job):
        """Notifie les abonnés"""
        pipeline = [
            {"$match": {
                "preferences.categories": {"$in": job["metadata"]["category"]},
                "last_activity": {"$gt": datetime.utcnow() - timedelta(days=7)}
            }},
            {"$project": {"user_id": 1}}
        ]

        async for user in self.users.aggregate(pipeline):
            if await self.is_active_user(user["user_id"]):
                await self.send_job_alert(user["user_id"], job)

    async def send_job_alert(self, user_id, job):
        """Envoie une alerte d'offre"""
        message = await self.format_job_message(job)
        message["body"] = "🚨 NOUVELLE OFFRE!\n\n" + message["body"]
        return await self.send_whatsapp_message(user_id, message)

# --- Configuration Flask ---
bot = WhatsAppJobBot()

@app.route('/webhook', methods=['POST'])
async def webhook_handler():
    if not bot.handle_webhook(request.json):
        return jsonify({"status": "error"}), 403
    return jsonify({"status": "success"}), 200

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if mode == "subscribe" and token == os.getenv("WEBHOOK_SECRET"):
        return challenge, 200
    return "Verification failed", 403

@app.route('/health')
def health_check():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()}), 200

if __name__ == "__main__":
    # Initialisation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot.init())
    
    # Démarrer le service de notifications
    loop.create_task(bot.notification_service())
    
    # Démarrer Flask
    app.run(host='0.0.0.0', port=3000)