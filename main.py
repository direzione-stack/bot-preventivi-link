import os
import time
import json
import telegram
import traceback
from googleapiclient.discovery import build
from google.oauth2 import service_account

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # ogni 60 secondi
CONFERME_GROUP_ID = -5071236492  # gruppo dedicato alle conferme

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
drive_service = build("drive", "v3", credentials=creds)

# === TRACKING ===
cache = {}
confermati = set()

# === FUNZIONI ===
def get_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])
    except Exception as e:
        print(f"❌ Errore durante recupero sottocartelle: {e}")
        return []

def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get("files", [])
        return folders[0]['id'] if folders else None
    except Exception as e:
        print(f"❌ Errore durante ricerca cartella principale: {e}")
        return None

def generate_share_link(folder_id):
    try:
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        drive_service.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass  # la permission potrebbe esistere già
    return f"https://drive.google.com/drive/folders/{folder_id}"

def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("❌ Cartella PreventiviTelegram non trovata.")
        return

    gruppi = get_subfolders(root_id)
    for gruppo in gruppi:
        gruppo_id = gruppo['name'].replace("gruppo_", "")
        gruppo_folder_id = gruppo['id']
        preventivi = get_subfolders(gruppo_folder_id)

        for p in preventivi:
            key = f"{gruppo_id}_{p['id']}"
            if key in cache:
                continue  # Già inviato

            link = generate_share_link(p['id'])
            nome_file = p['name']
            messaggio = f"*📁 Nuovo preventivo disponibile:*
{nome_file}\n{link}"

            try:
                bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                bot.send_message(chat_id=CONFERME_GROUP_ID, text=f"✅ Inviato a gruppo `{gruppo_id}`: {nome_file}", parse_mode=telegram.ParseMode.MARKDOWN)
                cache[key] = {
                    'folder_id': p['id'],
                    'timestamp': time.time(),
                    'tentativi': 0
                }
                print(f"✅ Inviato: {nome_file} al gruppo {gruppo_id}")
            except Exception as e:
                print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")

def gestisci_risposte(update, context):
    try:
        messaggio = update.message
        testo = messaggio.text.lower().strip()
        chat_id = str(messaggio.chat_id)
        parole_ok = ["ok", "confermo", "va bene", "accetto"]

        if testo in parole_ok:
            confermati.add(chat_id)
            bot.send_message(chat_id=CONFERME_GROUP_ID, text=f"🟢 Conferma ricevuta dal gruppo `{chat_id}`", parse_mode=telegram.ParseMode.MARKDOWN)
            print(f"🟢 Conferma da {chat_id}")
    except Exception as e:
        print(f"❌ Errore nella gestione delle risposte: {e}")

# === MAIN ===
if __name__ == '__main__':
    print("✅ BOT avviato e in ascolto di nuovi preventivi...")

    from telegram.ext import Updater, MessageHandler, Filters
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), gestisci_risposte))
    updater.start_polling()

    while True:
        try:
            scan_and_send()
        except Exception as e:
            print(f"❌ Errore nel ciclo principale: {traceback.format_exc()}")
        time.sleep(CHECK_INTERVAL)
