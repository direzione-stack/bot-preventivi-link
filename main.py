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
SOLLECITO_INTERVAL = 4 * 3600  # ogni 4 ore
SOLLECITO_MAX = 12  # per 48 ore

bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
SCOPES = ['https://www.googleapis.com/auth/drive']
CREDENTIALS_FILE = "credentials.json"
creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
drive = build('drive', 'v3', credentials=creds)

# === CACHE ===
sent_cache = {}  # chiave: gruppo_id_preventivo_id
reminder_cache = {}  # chiave: gruppo_id_preventivo_id -> [timestamp_primo_invio, numero_solleciti]
confirmed_cache = set()

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
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass
    return f"https://drive.google.com/drive/folders/{folder_id}"

def invia_preventivo(gruppo_id, nome_file, link, key):
    messaggio = f"\u2709\ufe0f <b>Nuovo preventivo disponibile:</b>\n<b>{nome_file}</b>\n{link}"
    try:
        bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode=telegram.ParseMode.HTML)
        bot.send_message(chat_id=CONFIRMATION_GROUP_ID, text=f"\u2705 Inviato al gruppo <code>{gruppo_id}</code>: {nome_file}", parse_mode=telegram.ParseMode.HTML)
        sent_cache[key] = True
        reminder_cache[key] = [time.time(), 0]
        print(f"✅ Inviato: {nome_file} al gruppo {gruppo_id}")
    except Exception as e:
        print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")

def invia_sollecito():
    ora = time.time()
    for key in list(reminder_cache):
        if key in confirmed_cache:
            continue
        primo_invio, count = reminder_cache[key]
        if count >= SOLLECITO_MAX:
            gruppo_id = key.split("_")[0]
            try:
                bot.send_message(chat_id=int(gruppo_id), text="❌ Ci dispiace che tu non abbia risposto. Il lavoro verrà assegnato a un'altra azienda.")
                bot.send_message(chat_id=CONFIRMATION_GROUP_ID, text=f"⛔ Nessuna risposta dal gruppo <code>{gruppo_id}</code>. Lavoro riassegnato.", parse_mode=telegram.ParseMode.HTML)
            except Exception as e:
                print(f"Errore invio messaggio finale a {gruppo_id}: {e}")
            del reminder_cache[key]
        elif ora - primo_invio >= (count + 1) * SOLLECITO_INTERVAL:
            gruppo_id, preventivo_id = key.split("_")
            link = generate_share_link(preventivo_id)
            try:
                bot.send_message(chat_id=int(gruppo_id), text=f"🔔 <b>Gentile collaboratore, ti ricordiamo il preventivo ancora da confermare:</b>\n{link}", parse_mode=telegram.ParseMode.HTML)
                reminder_cache[key][1] += 1
                print(f"🔁 Sollecito inviato a gruppo {gruppo_id}")
            except Exception as e:
                print(f"Errore sollecito a gruppo {gruppo_id}: {e}")

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
            if key in sent_cache:
                continue
            link = generate_share_link(p['id'])
            invia_preventivo(gruppo_id, p['name'], link, key)

def conferma(update, context):
    msg = update.message
    testo = msg.text.lower()
    if testo in ["ok", "confermo", "va bene", "accetto"]:
        gruppo_id = msg.chat.id
        user = msg.from_user.full_name
        for key in reminder_cache:
            if str(gruppo_id) in key:
                confirmed_cache.add(key)
                try:
                    bot.send_message(chat_id=CONFIRMATION_GROUP_ID, text=f"✅ Conferma ricevuta da <b>{user}</b> nel gruppo <code>{gruppo_id}</code>", parse_mode=telegram.ParseMode.HTML)
                    print(f"✅ Conferma registrata per {gruppo_id} da {user}")
                except Exception as e:
                    print(f"Errore invio conferma: {e}")
                break

from telegram.ext import Updater, MessageHandler, Filters
updater = Updater(token=BOT_TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(MessageHandler(Filters.text & (~Filters.command), conferma))
updater.start_polling()

if __name__ == '__main__':
    print("🚀 BOT preventivi avviato...")
    while True:
        try:
            scan_and_send()
            invia_sollecito()
        except Exception as e:
            print(f"❌ Errore: {traceback.format_exc()}")
        time.sleep(CHECK_INTERVAL)
