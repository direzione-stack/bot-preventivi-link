import os
import time
import json
import threading
from datetime import datetime, timedelta
from telegram import Bot
from telegram.error import TelegramError
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIG ===
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_CREDS_JSON = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
FOLDER_NAME = "PreventiviTelegram"
SOLLECITO_DELAY = 4 * 60 * 60  # 4 ore in secondi

bot = Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

# === TRACKING ===
processed_folders = {}
solleciti = {}

# === FUNZIONI ===
def get_subfolders(folder_id):
    query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = drive_service.files().list(q=query, fields="files(id, name)").execute()
    return response.get('files', [])

def get_folder_link(folder_id):
    return f"https://drive.google.com/drive/folders/{folder_id}"

def find_main_folder():
    query = f"name = '{FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = drive_service.files().list(q=query, fields="files(id)").execute()
    files = response.get('files', [])
    return files[0]['id'] if files else None

def monitor_group_folder(group_folder_id, chat_id):
    global processed_folders, solleciti
    while True:
        try:
            subfolders = get_subfolders(group_folder_id)
            for folder in subfolders:
                folder_id = folder['id']
                folder_name = folder['name']

                if folder_id not in processed_folders:
                    link = get_folder_link(folder_id)
                    message = f"📂 Nuova cartella caricata: *{folder_name}*\n🔗 {link}"
                    bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
                    processed_folders[folder_id] = {'sent': True, 'time': datetime.now(), 'chat_id': chat_id, 'name': folder_name, 'link': link}
        except TelegramError as te:
            print(f"Errore Telegram: {te}")
        except Exception as e:
            print(f"Errore nel monitoraggio cartelle: {e}")

        time.sleep(30)

def monitor_solleciti():
    while True:
        now = datetime.now()
        for folder_id, info in processed_folders.items():
            if 'reminded' not in info:
                elapsed = (now - info['time']).total_seconds()
                if elapsed > SOLLECITO_DELAY:
                    msg = f"🔔 *Sollecito*: Attendi ancora conferma per la cartella *{info['name']}*.\n🔗 {info['link']}"
                    try:
                        bot.send_message(chat_id=info['chat_id'], text=msg, parse_mode='Markdown')
                        info['reminded'] = True
                    except TelegramError as te:
                        print(f"Errore sollecito Telegram: {te}")
        time.sleep(60)

# === AVVIO ===
main_folder_id = find_main_folder()
if not main_folder_id:
    raise Exception("Cartella 'PreventiviTelegram' non trovata su Google Drive")

response = drive_service.files().list(q=f"'{main_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false", fields="files(id, name)").execute()
group_folders = response.get('files', [])

print("✅ Bot avviato. Monitoraggio attivo sulle cartelle gruppi:")
for folder in group_folders:
    folder_id = folder['id']
    folder_name = folder['name']
    if folder_name.startswith("gruppo_"):
        chat_id = folder_name.replace("gruppo_", "")
        print(f"- {folder_name} (chat_id: {chat_id})")
        t = threading.Thread(target=monitor_group_folder, args=(folder_id, int(chat_id)))
        t.start()

# Thread separato per solleciti
t_solleciti = threading.Thread(target=monitor_solleciti)
t_solleciti.start()
