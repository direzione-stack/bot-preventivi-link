import os
import time
import telegram
import traceback
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2 import service_account

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
FOLDER_NAME = "PreventiviTelegram"
CONFIRMATION_GROUP_ID = -5071236492
CHECK_INTERVAL = 60  # ogni 60 secondi
SOLLECITO_INTERVAL = 14400  # ogni 4 ore (in secondi)
SOLLECITO_MAX_HOURS = 48

bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
SCOPES = ['https://www.googleapis.com/auth/drive']
CREDENTIALS_FILE = "credentials.json"
creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
drive = build('drive', 'v3', credentials=creds)

# === CACHE ===
sent_cache = {}
reminder_cache = {}
confirmed_cache = set()

# === DRIVE UTILS ===
def get_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        print(f"❌ Errore recupero sottocartelle: {e}")
        return []

def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get('files', [])
        return folders[0]['id'] if folders else None
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

# === SCAN E INVIO ===
def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("❌ Cartella principale non trovata.")
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
            if key in confirmed_cache:
                continue

            if key not in sent_cache:
                link = generate_share_link(p['id'])
                nome_file = p['name']
                messaggio = f"\U0001F4C2 <b>Nuovo preventivo disponibile:</b>\n<b>{nome_file}</b>\n{link}"
                try:
                    bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode=telegram.ParseMode.HTML)
                    bot.send_message(chat_id=CONFIRMATION_GROUP_ID, text=f"\u2705 Inviato a <code>{gruppo_id}</code>: {nome_file}", parse_mode=telegram.ParseMode.HTML)
                    sent_cache[key] = {
                        "nome_file": nome_file,
                        "gruppo_id": gruppo_id,
                        "first_sent": datetime.now(),
                        "last_reminder": datetime.now(),
                        "reminders": 0
                    }
                except Exception as e:
                    print(f"❌ Errore invio gruppo {gruppo_id}: {e}")

# === SOLLECITI ===
def invia_solleciti():
    now = datetime.now()
    for key, data in list(sent_cache.items()):
        if key in confirmed_cache:
            continue

        elapsed = now - data['last_reminder']
        total_time = now - data['first_sent']

        if total_time.total_seconds() > SOLLECITO_MAX_HOURS * 3600:
            try:
                bot.send_message(chat_id=data['gruppo_id'], text="❌ Tempo scaduto: inoltreremo il lavoro ad un'altra azienda.")
                bot.send_message(chat_id=CONFIRMATION_GROUP_ID, text=f"⚠️ Nessuna risposta dal gruppo <code>{data['gruppo_id']}</code> per il preventivo: {data['nome_file']}.", parse_mode=telegram.ParseMode.HTML)
                confirmed_cache.add(key)
            except:
                pass
            continue

        if elapsed.total_seconds() >= SOLLECITO_INTERVAL:
            try:
                bot.send_message(chat_id=data['gruppo_id'], text=f"🔔 Sollecito: confermi il preventivo <b>{data['nome_file']}</b>?", parse_mode=telegram.ParseMode.HTML)
                data['last_reminder'] = now
                data['reminders'] += 1
            except:
                pass

# === GESTIONE CONFERME ===
def handle_update(update):
    if not update.message:
        return

    text = update.message.text.lower()
    if text in ["ok", "confermo", "va bene", "accetto"]:
        user_id = update.message.chat.id
        for key, data in sent_cache.items():
            if data['gruppo_id'] == user_id and key not in confirmed_cache:
                confirmed_cache.add(key)
                bot.send_message(chat_id=CONFIRMATION_GROUP_ID, text=f"✅ Conferma ricevuta da gruppo <code>{user_id}</code> per il preventivo <b>{data['nome_file']}</b>.", parse_mode=telegram.ParseMode.HTML)
                break

# === AVVIO ===
if __name__ == '__main__':
    print("🚀 BOT avviato e operativo.")
    updater = telegram.ext.Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(telegram.ext.MessageHandler(telegram.ext.Filters.text & ~telegram.ext.Filters.command, handle_update))
    updater.start_polling()

    while True:
        try:
            scan_and_send()
            invia_solleciti()
        except Exception as e:
            print(f"❌ Errore generale:\n{traceback.format_exc()}")
        time.sleep(CHECK_INTERVAL)
