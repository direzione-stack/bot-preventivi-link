import os
import time
import json
import telegram
import gspread
from google.oauth2 import service_account

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
gc = gspread.authorize(creds)
drive_service = creds.with_scopes(['https://www.googleapis.com/auth/drive'])

# === TRACKING preventivi inviati ===
cache = {}

# === CONFIG ===
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # ogni 60 secondi

from googleapiclient.discovery import build
drive = build('drive', 'v3', credentials=drive_service)

def get_subfolders(parent_id):
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def get_folder_id_by_name(name):
    query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get('files', [])
    return folders[0]['id'] if folders else None

def generate_share_link(folder_id):
    permission = {
        'type': 'anyone',
        'role': 'reader'
    }
    try:
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass  # Permission might already exist
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
            messaggio = f"📂 *Nuovo preventivo disponibile:*
[{p['name']}]({link})"
            try:
                bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                cache[key] = True
                print(f"✅ Inviato: {p['name']} al gruppo {gruppo_id}")
            except Exception as e:
                print(f"❌ Errore invio a {gruppo_id}: {e}")

if __name__ == '__main__':
    print("🤖 BOT avviato e in ascolto di nuovi preventivi...")
    while True:
        try:
            scan_and_send()
        except Exception as e:
            print(f"Errore nel ciclo: {e}")
        time.sleep(CHECK_INTERVAL)
