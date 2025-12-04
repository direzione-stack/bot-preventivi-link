import os
import time
import json
import telegram
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from telegram import Update, ParseMode
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")
DRIVE_ROOT_FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # secondi

# Convert credentials
if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
drive_service = build("drive", "v3", credentials=creds)

# === CACHE preventivi già inviati ===
cache = {}

# === GRUPPI TELEGRAM ===
GRUPPI = {
    "123456789": "NomeGruppo1",
    "987654321": "NomeGruppo2",
    # Aggiungi altri ID gruppo se necessario
}

# === FUNZIONI GOOGLE DRIVE ===
def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = (
            drive_service.files()
            .list(q=query, fields="files(id, name)")
            .execute()
        )
        folders = results.get("files", [])
        return folders[0]["id"] if folders else None
    except HttpError as e:
        print(f"Errore ricerca folder: {e}")
        return None

def get_subfolders(parent_id):
    try:
        query = (
            f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])
    except HttpError as e:
        print(f"Errore ricerca sottocartelle: {e}")
        return []

def generate_share_link(folder_id):
    try:
        permission = {"type": "anyone", "role": "reader"}
        drive_service.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass  # se esiste già la permission
    return f"https://drive.google.com/drive/folders/{folder_id}"

# === SCANSIONE E INVIO ===
def scan_and_send():
    root_id = get_folder_id_by_name(DRIVE_ROOT_FOLDER_NAME)
    if not root_id:
        print("❌ Cartella principale non trovata")
        return

    gruppi = get_subfolders(root_id)
    for gruppo in gruppi:
        gruppo_id = gruppo['name'].replace("gruppo_", "")
        gruppo_folder_id = gruppo['id']

        preventivi = get_subfolders(gruppo_folder_id)
        for p in preventivi:
            key = f"{gruppo_id}_{p['id']}"
            if key in cache:
                continue

            link = generate_share_link(p['id'])
            nome_file = p['name']
            messaggio = f"*📁 Nuovo preventivo disponibile:*
{nome_file}
{link}"

            try:
                bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode=ParseMode.MARKDOWN)
                cache[key] = True
                print(f"✅ Inviato a gruppo {gruppo_id}: {nome_file}")
            except Exception as e:
                print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")

# === RISPOSTE DI CONFERMA ===
CONFERME = ["ok", "confermo", "va bene", "accetto"]


def handle_messages(update: Update, context: CallbackContext):
    message = update.message
    text = message.text.lower().strip()
    gruppo_id = str(message.chat_id)

    if text in CONFERME:
        conferma_msg = f"✅ Preventivo confermato da [{message.from_user.first_name}](tg://user?id={message.from_user.id})"
        try:
            # Conferma inviata nel gruppo stesso o gruppo dedicato
            bot.send_message(chat_id=gruppo_id, text=conferma_msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            print(f"❌ Errore invio conferma: {e}")

# === AVVIO ===
if __name__ == "__main__":
    print("🚀 BOT avviato e in ascolto...")

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_messages))
    updater.start_polling()

    while True:
        try:
            scan_and_send()
        except Exception as e:
            print(f"❌ Errore scansione: {e}")
        time.sleep(CHECK_INTERVAL)
