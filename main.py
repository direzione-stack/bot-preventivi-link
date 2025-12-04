import os
import time
import json
import telegram
import traceback
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60
SOLLECITO_INTERVAL = 4 * 3600
FINE_SOLLECITI = 48 * 3600
GRUPPO_CONFERME_ID = -5071236492

bot = telegram.Bot(token=BOT_TOKEN)
cache = {}
solleciti = {}

# === Google Drive ===
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")
if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

creds = service_account.Credentials.from_service_account_info(
    GOOGLE_CREDS_JSON,
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive = build("drive", "v3", credentials=creds)


def get_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])
    except Exception as e:
        print(f"❌ Errore recupero sottocartelle: {e}")
        return []


def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get("files", [])
        return folders[0]["id"] if folders else None
    except Exception as e:
        print(f"❌ Errore ricerca cartella principale: {e}")
        return None


def generate_share_link(folder_id):
    try:
        permission = {'type': 'anyone', 'role': 'reader'}
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass
    return f"https://drive.google.com/drive/folders/{folder_id}"


def invia_solleciti():
    ora = time.time()
    for key, (ts_invio, numero_solleciti, gruppo_id, nome_file) in list(solleciti.items()):
        if key in cache:
            continue

        tempo_trascorso = ora - ts_invio

        if tempo_trascorso > FINE_SOLLECITI:
            del solleciti[key]
            continue

        if tempo_trascorso > (numero_solleciti + 1) * SOLLECITO_INTERVAL:
            messaggio = f"⚠️ *Sollecito #{numero_solleciti + 1}* per confermare il preventivo:\n{nome_file}"
            try:
                bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                solleciti[key] = (ts_invio, numero_solleciti + 1, gruppo_id, nome_file)
                print(f"🔁 Sollecito inviato a gruppo {gruppo_id}")
            except Exception as e:
                print(f"❌ Errore invio sollecito a {gruppo_id}: {e}")


def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
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

            link = generate_share_link(p["id"])
            messaggio = f"📂 *Nuovo preventivo disponibile:*\n{p['name']}\n{link}"
            try:
                bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                print(f"✅ Inviato a gruppo {gruppo_id}: {p['name']}")
                cache[key] = True
                solleciti[key] = (time.time(), 0, int(gruppo_id), p['name'])
            except Exception as e:
                print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")


def gestisci_risposte(update, context):
    try:
        messaggio = update.message.text.lower()
        chat_id = update.message.chat_id
        nome_utente = update.message.from_user.first_name
        conferme_valide = ["ok", "confermo", "va bene", "accetto"]

        if messaggio in conferme_valide:
            for key in list(solleciti.keys()):
                _, _, gruppo_id, nome_file = solleciti[key]
                if gruppo_id == chat_id:
                    del solleciti[key]
                    cache[key] = True
                    testo = f"✅ *Preventivo confermato da {nome_utente}*\n📁 {nome_file}"
                    bot.send_message(chat_id=GRUPPO_CONFERME_ID, text=testo, parse_mode=telegram.ParseMode.MARKDOWN)
                    print(f"🟢 Conferma ricevuta da {nome_utente} - gruppo {chat_id}")
                    break
    except Exception as e:
        print(f"❌ Errore gestione risposta: {e}")


# === SETUP HANDLER ===
from telegram.ext import Updater, MessageHandler, Filters

updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, gestisci_risposte))

# === AVVIO ===
print("🤖 BOT avviato e in ascolto di nuovi preventivi...")

updater.start_polling()

while True:
    try:
        scan_and_send()
        invia_solleciti()
    except Exception as e:
        print(f"❌ Errore nel ciclo principale:\n{traceback.format_exc()}")
    time.sleep(CHECK_INTERVAL)
