import os
import time
import json
import logging
from telegram import Bot
from telegram.error import TelegramError
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Variabili ambiente
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

# Inizializza bot
bot = Bot(token=BOT_TOKEN)

# Google Drive
credentials = service_account.Credentials.from_service_account_info(
    GOOGLE_CREDS,
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive_service = build("drive", "v3", credentials=credentials)

# Tieni traccia delle cartelle già inviate
sent = set()

def trova_nuove_cartelle():
    try:
        response = drive_service.files().list(
            q=f"'{DRIVE_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder'",
            spaces='drive',
            fields="files(id, name, createdTime)"
        ).execute()
        return response.get("files", [])
    except Exception as e:
        logger.error(f"Errore lettura Drive: {e}")
        return []

def invia_link_cartella(folder_id, folder_name):
    link = f"https://drive.google.com/drive/folders/{folder_id}"
    try:
        bot.send_message(chat_id=OWNER_ID, text=f"📂 Nuovo preventivo: *{folder_name}*\n🔗 {link}", parse_mode='Markdown')
        logger.info(f"Inviato: {folder_name}")
    except TelegramError as e:
        logger.error(f"Errore Telegram: {e}")

if __name__ == "__main__":
    logger.info("🤖 Bot attivo e in ascolto...")
    while True:
        cartelle = trova_nuove_cartelle()
        for cartella in cartelle:
            if cartella['id'] not in sent:
                invia_link_cartella(cartella['id'], cartella['name'])
                sent.add(cartella['id'])
        time.sleep(300)
