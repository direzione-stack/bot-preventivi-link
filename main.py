import os
import time
import json
import telegram
import gspread
import traceback
import sys
sys.stdout.reconfigure(encoding='utf-8')
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
sheet = gc.open("Report Preventivi").sheet1

# === TRACKING stato preventivi inviati ===
cache = {}

# === CONFIG ===
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # ogni 60 secondi
SOLLECITO_INTERVALLO = 4 * 60 * 60  # ogni 4 ore
FINE_SOLLECITI = 48 * 60 * 60  # dopo 48 ore

# === UTILS GOOGLE DRIVE ===
from googleapiclient.discovery import build
drive_service = creds.with_scopes(['https://www.googleapis.com/auth/drive'])
drive = build('drive', 'v3', credentials=drive_service)

def get_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        print(f"[ERRORE] Recupero sottocartelle: {e}")
        return []

def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get('files', [])
        return folders[0]['id'] if folders else None
    except Exception as e:
        print(f"[ERRORE] Ricerca cartella principale: {e}")
        return None

def generate_share_link(folder_id):
    try:
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass  # ignoriamo se il permesso esiste
    return f"https://drive.google.com/drive/folders/{folder_id}"

def aggiorna_conferma(chat_id):
    records = sheet.get_all_records()
    for idx, row in enumerate(records, start=2):
        if str(row.get("chat_id")) == str(chat_id):
            sheet.update_cell(idx, 4, "confermato")
            break

def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("[X] Cartella PreventiviTelegram non trovata.")
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
            messaggio = f"*📁 Nuovo preventivo disponibile:*\n{nome_file}\n[{p['name']}]({link})"
            try:
                bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                cache[key] = {
                    'timestamp': time.time(),
                    'chat_id': gruppo_id,
                    'nome': nome_file
                }
                print(f"[\u2714] Inviato {nome_file} al gruppo {gruppo_id}")
            except Exception as e:
                print(f"[X] Errore invio a gruppo {gruppo_id}: {e}")

def invia_solleciti():
    now = time.time()
    for key, info in cache.items():
        tempo_passato = now - info['timestamp']
        if tempo_passato > FINE_SOLLECITI:
            try:
                bot.send_message(chat_id=int(info['chat_id']), text=f"❌ Il preventivo *{info['nome']}* non è stato confermato. Sarà assegnato ad altri.", parse_mode=telegram.ParseMode.MARKDOWN)
                print(f"[X] Messaggio di chiusura a {info['chat_id']}")
            except:
                pass
            continue
        elif tempo_passato > SOLLECITO_INTERVALLO:
            try:
                bot.send_message(chat_id=int(info['chat_id']), text=f"⏰ Sollecito: conferma il preventivo *{info['nome']}*", parse_mode=telegram.ParseMode.MARKDOWN)
                cache[key]['timestamp'] = now  # aggiorna orario
                print(f"[\u231b] Sollecito inviato a {info['chat_id']}")
            except:
                pass

def ascolta_conferme(update):
    messaggio = update.message.text.lower()
    chat_id = update.message.chat.id
    if messaggio in ["ok", "confermo", "va bene", "accetto"]:
        aggiorna_conferma(chat_id)
        try:
            bot.send_message(chat_id=chat_id, text="✅ Grazie, preventivo confermato.")
        except:
            pass

from telegram.ext import Updater, MessageHandler, Filters

if __name__ == '__main__':
    print("[INFO] BOT avviato e in ascolto di nuovi preventivi...")
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), ascolta_conferme))
    updater.start_polling()

    while True:
        try:
            scan_and_send()
            invia_solleciti()
        except Exception as e:
            print(f"[X] Errore nel ciclo principale: {traceback.format_exc()}")
        time.sleep(CHECK_INTERVAL)
