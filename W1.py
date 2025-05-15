from flask import Flask, request, jsonify
import requests
import offreBot

app = Flask(__name__)

# Variables à configurer
PHONE_NUMBER_ID = offreBot.WA_PHONE_ID
WHATSAPP_TOKEN = offreBot.WA_ACCESS_TOKEN

WHATSAPP_API_URL = f'https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages'

headers = {
    'Authorization': f'Bearer {WHATSAPP_TOKEN}',
    'Content-Type': 'application/json'
}

def send_buttons(to_number):
    # Exemple de boutons rapides (quick reply buttons)
    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Bienvenue! Que souhaitez-vous faire ?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "btn_1",
                            "title": "Option 1"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "btn_2",
                            "title": "Option 2"
                        }
                    }
                ]
            }
        }
    }
    response = requests.post(WHATSAPP_API_URL, json=data, headers=headers)
    print("Send buttons response:", response.status_code, response.text)

@app.route('/webhook', methods=['POST'])
def webhook():
    incoming = request.json
    print("Incoming message:", incoming)
    
    # Extraire le message reçu et le numéro de l'expéditeur
    try:
        messages = incoming['entry'][0]['changes'][0]['value']['messages']
        for msg in messages:
            from_number = msg['from']
            if 'text' in msg:
                text = msg['text']['body']
                if text.strip() == '/start':
                    send_buttons(from_number)
    except Exception as e:
        print("Erreur traitement message:", e)
    
    return jsonify(status='received')

# Route GET pour vérification du webhook (Meta demande un challenge à valider)
@app.route('/webhook', methods=['GET'])
def verify():
    VERIFY_TOKEN = 'claudelAI223'
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode and token:
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            print('WEBHOOK VERIFIED')
            return challenge, 200
        else:
            return 'Forbidden', 403
    return 'Hello world', 200


if __name__ == '__main__':
    app.run(port=5000)
