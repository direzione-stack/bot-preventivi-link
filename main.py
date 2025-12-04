import os
import time
import json
import telegram
import traceback
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # per scrivere solo le conferme
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # ogni 60 secondi
SOLLECITO_INTERVAL = 4 * 60 * 60  # ogni 4 ore

# === GOOGLE DRIVE ===
if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
drive = build("drive", "v3", credentials=creds)

def get_folder_id_by_name(name):
    query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get("files", [])
    return folders[0]["id"] if folders else None

def get_subfolders(parent_id):
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive.files().list(q=query, fields="files(id, name)").execute()
    return results.get("files", [])

def generate_share_link(folder_id):
    try:
        permission = {"type": "anyone", "role": "reader"}
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass
    return f"https://drive.google.com/drive/folders/{folder_id}"

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === CACHE ===
cache = {}
solleciti = {}  # chat_id: {folder_id: (timestamp, count)}

# === GOOGLE SHEETS === (solo per le conferme)
import gspread
gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)
sheet = sh.sheet1


def log_confirmation(gruppo_id, nome_cartella):
    sheet.append_row([str(gruppo_id), nome_cartella, time.strftime("%Y-%m-%d %H:%M:%S")])

def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("❌ Cartella principale non trovata")
        return

    gruppi = get_subfolders(root_id)
    for gruppo in gruppi:
        gruppo_id = gruppo["name"].replace("gruppo_", "")
        gruppo_folder_id = gruppo["id"]

        preventivi = get_subfolders(gruppo_folder_id)
        for p in preventivi:
            key = f"{gruppo_id}_{p['id']}"
            if key in cache:
                continue

            link = generate_share_link(p['id'])
            nome_file = p['name']
            messaggio = f"\u2728 *Nuovo preventivo disponibile:*\n[{nome_file}]({link})"

            try:
                bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                cache[key] = time.time()
                solleciti.setdefault(int(gruppo_id), {})[p['id']] = (time.time(), 1)
                print(f"\u2709️ Inviato: {nome_file} al gruppo {gruppo_id}")
            except Exception as e:
                print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")


def invia_solleciti():
    for gruppo_id, folders in solleciti.items():
        for folder_id, (last_time, count) in list(folders.items()):
            if time.time() - last_time >= SOLLECITO_INTERVAL:
                link = generate_share_link(folder_id)
                messaggio = f"\u26a0️ *{count}\u00b0 Sollecito* per confermare il preventivo:\n{link}"
                try:
                    bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                    solleciti[gruppo_id][folder_id] = (time.time(), count + 1)
                    print(f"\u23f3 Sollecito inviato a {gruppo_id} per {folder_id}")
                except Exception as e:
                    print(f"❌ Errore sollecito {gruppo_id}: {e}")


def gestisci_risposte(update):
    try:
        testo = update.message.text.lower()
        if testo in ["ok", "confermo", "va bene", "accetto"]:
            chat_id = update.message.chat_id
            nome = update.message.from_user.full_name
            preventivo = None
            # cerca l'ultimo preventivo non confermato
            for key in cache:
                if str(chat_id) in key:
                    preventivo = key.split("_")[1]
            if preventivo:
                log_confirmation(chat_id, preventivo)
                bot.send_message(chat_id=chat_id, text=f"✅ Conferma ricevuta, grazie {nome}!")
                solleciti[chat_id].pop(preventivo, None)
    except Exception as e:
        print(f"Errore gestione risposta: {e}")


from telegram.ext import Updater, MessageHandler, Filters
updater = Updater(token=BOT_TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, gestisci_risposte))
updater.start_polling()


print("\ud83e\udd16 BOT avviato e in ascolto di nuovi preventivi...")

while True:
    try:
        scan_and_send()
        invia_solleciti()
    except Exception as e:
        print(f"❌ Errore generale: {traceback.format_exc()}")
    time.sleep(CHECK_INTERVAL)
