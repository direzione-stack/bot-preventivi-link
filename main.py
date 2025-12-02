import os
import time
import logging
from datetime import datetime, timedelta
from telegram import Bot
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === CONFIGURAZIONI ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PARENT_FOLDER_ID = "1ZvMpmFyAJlosq0hHTKD4NPFmEAaHiLsn"
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

# === INIZIALIZZA BOT ===
bot = Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE API ===
creds = service_account.Credentials.from_service_account_info(eval(GOOGLE_CREDS_JSON))
drive_service = build("drive", "v3", credentials=creds)

# === TRACKING SOLLECITI ===
sent_reminders = {}

# === FUNZIONI ===
def list_subfolders(parent_id):
    results = drive_service.files().list(
        q=f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        spaces='drive', fields='files(id, name, createdTime)', orderBy='createdTime desc'
    ).execute()
    return results.get('files', [])

def list_pdfs(folder_id):
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and mimeType = 'application/pdf' and trashed = false",
        spaces='drive', fields='files(id, name)', orderBy='createdTime desc'
    ).execute()
    return results.get('files', [])

def extract_group_id(folder_name):
    try:
        return int(folder_name.split('_')[-1])
    except:
        return None

def send_preventivo(folder):
    group_id = extract_group_id(folder['name'])
    if not group_id:
        logger.warning(f"Impossibile trovare l'ID gruppo da: {folder['name']}")
        return

    pdfs = list_pdfs(folder['id'])
    if not pdfs:
        logger.info(f"Nessun PDF in {folder['name']}")
        return

    folder_link = f"https://drive.google.com/drive/folders/{folder['id']}"
    message = f"\ud83d\udce9 Nuovo preventivo da confermare: [{pdfs[0]['name']}]({folder_link})"

    try:
        bot.send_message(chat_id=group_id, text=message, parse_mode='Markdown')
        logger.info(f"Inviato a gruppo {group_id}")
        sent_reminders[folder['id']] = {
            "next": datetime.utcnow() + timedelta(hours=5),
            "expires": datetime.utcnow() + timedelta(hours=48),
            "group_id": group_id,
            "message_sent": False
        }
    except Exception as e:
        logger.error(f"Errore invio a gruppo {group_id}: {e}")

def check_reminders():
    now = datetime.utcnow()
    for folder_id in list(sent_reminders):
        data = sent_reminders[folder_id]

        if now >= data["expires"] and not data["message_sent"]:
            try:
                bot.send_message(chat_id=data["group_id"], text="\u274c Ci dispiace, il lavoro sar\u00e0 dato a un altro nostro partner.")
                sent_reminders[folder_id]["message_sent"] = True
                logger.info(f"Messaggio finale inviato a {data['group_id']}")
            except Exception as e:
                logger.error(f"Errore finale: {e}")

        elif now >= data["next"] and not data["message_sent"]:
            try:
                bot.send_message(chat_id=data["group_id"], text="\u23f0 Promemoria: hai un preventivo in attesa di conferma.")
                sent_reminders[folder_id]["next"] = now + timedelta(hours=5)
                logger.info(f"Sollecito inviato a {data['group_id']}")
            except Exception as e:
                logger.error(f"Errore sollecito: {e}")

# === MAIN LOOP ===
if __name__ == "__main__":
    logger.info("Bot conferma preventivi attivo")
    while True:
        try:
            folders = list_subfolders(PARENT_FOLDER_ID)
            for folder in folders:
                if folder['id'] not in sent_reminders:
                    send_preventivo(folder)
            check_reminders()
            time.sleep(300)  # 5 minuti
        except Exception as e:
            logger.error(f"Errore generale: {e}")
            time.sleep(60)
