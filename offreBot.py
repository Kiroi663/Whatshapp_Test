# Configuration du mode debug
DEBUG = True  # Mettre à False en production
WA_PHONE_ID = "554234621112117"
WA_ACCESS_TOKEN = "EAA1Jrhn7LicBO2M0jlV7vE8ZAx56isDsC2ynNJLsBa3yaspDkSRA46ZB515ZCfOJpeXe5zoRGj0I0qX0Wog9DfTT7MMhvV0UEE6N9Gq2z7xdG0wLWGBArge0mUieOVBngrvZCya93eSRNk5pjaPUQSKoAKPXLMDHAiFAuQT5KmGnZAI9TWxLGMZCEUAIT9wqb42gZDZD"
WEBHOOK_SECRET = "claudelAI223"
TEST_NUMBER = "+15556364720"
# Version du bot
VERSION = "1.0.0"
TELEGRAM_BOT_TOKEN = "7532881306:AAEWQHmhnrPDd6EpB1mfd3bdX8NIhOGvfZk"
API_ID = "25426984"
API_HASH = "7d8d92cee8b7411879b472dcd36bfdab"
MONGO_URI = "mongodb+srv://claudelAI:claudelAI@cluster0.w0t3l.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
MONGO_URIU="mongodb+srv://claudelAI:claudelAI@cluster0.w0t3l.mongodb.net/job_database?retryWrites=true&w=majority"

TELEGRAM_CHANNEL = '@JobFinderHub001'
CHANNEL_ID = '@JobFinderHub001'
SCRIPT = """
Prompt pour résumer l'offre d'emploi
Instructions pour le modèle :

Tu es un assistant spécialisé dans l'extraction et la synthèse des informations clés des offres d'emploi. 
Ton objectif est de transformer une description détaillée d'une offre d'emploi en un résumé structuré contenant 
uniquement les informations essentielles Voici les champs que tu dois inclure dans ton résumé :

1. **Titre du poste**
2. **Lieu**
3. **Nom de l'entreprise**
3. **Durée** (si applicable)
4. **Diplôme requis**
5. **Expérience requise**
6. **Langues nécessaires**
7. **Date limite de candidature**
8. **Comment postuler**

Utilise un format clair et concis, comme celui-ci :
Exemple de format attendu :
**[Titre du poste]**
- Lieu : [lieu]
- Nom de l'entreprise: [entreprise]
- Durée : [durée]
- Diplôme requis : [diplôme]
- Expérience : [expérience]
- Langues : [langues]
- Date limite candidature : [date]
- Comment postuler : [instructions]
Entrée (texte brut de l'offre d'emploi) :

Resumé avec au maximum 100 mots
"""

