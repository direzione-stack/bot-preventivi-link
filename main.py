import os
import time
import telegram
import traceback
from googleapiclient.discovery import build
from google.oauth2 import service_account

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
FOLDER_NAME = "PreventiviTelegram"
CONFIRMATION_GROUP_ID = -5071236492
CHECK_INTERVAL = 60  # ogni 60 secondi

bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
SCOPES = ['https://www.googleapis.com/auth/drive']
CREDENTIALS_FILE = "credentials.json"
creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
drive = build('drive', 'v3', credentials=creds)

def get_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        print(f"❌ Errore durante recupero sottocartelle: {e}")
        return []

def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get('files', [])
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
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass  # permission could already exist
    return f"https://drive.google.com/drive/folders/{folder_id}"

cache = {}

def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("❌ Cartella PreventiviTelegram non trovata.")
        return

    gruppi = get_subfolders(root_id)
    for gruppo in gruppi:
        gruppo_id_str = gruppo['name'].replace("gruppo_", "").replace("_g", "")
        try:
            gruppo_id = int(gruppo_id_str)
        except ValueError:
            print(f"❌ ID gruppo non valido: {gruppo_id_str}")
            continue

        gruppo_folder_id = gruppo['id']
        preventivi = get_subfolders(gruppo_folder_id)

        for p in preventivi:
            key = f"{gruppo_id}_{p['id']}"
            if key in cache:
                continue

            link = generate_share_link(p['id'])
            nome_file = p['name']
            messaggio = f"📂 <b>Nuovo preventivo disponibile:</b>\n<b>{nome_file}</b>\n{link}"
            try:
                bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode=telegram.ParseMode.HTML)
                bot.send_message(chat_id=CONFIRMATION_GROUP_ID, text=f"✅ Preventivo inviato a gruppo <code>{gruppo_id}</code>: {nome_file}", parse_mode=telegram.ParseMode.HTML)
                cache[key] = True
                print(f"✅ Inviato: {nome_file} al gruppo {gruppo_id}")
            except Exception as e:
                print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")

if __name__ == '__main__':
    print("🚀 BOT avviato e in ascolto di nuovi preventivi...")
    while True:
        try:
            scan_and_send()
        except Exception as e:
            print(f"❌ Errore nel ciclo principale:\n{traceback.format_exc()}")
        time.sleep(CHECK_INTERVAL)
