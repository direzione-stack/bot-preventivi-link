import os
import time
import telegram
from googleapiclient.discovery import build
from google.oauth2 import service_account

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # in secondi
SOLLECITO_INTERVALLO = 4 * 60 * 60  # 4 ore in secondi
SOLLECITO_MAX_ORE = 48
GRUPPO_CONFERME_ID = -5071236492

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
creds = service_account.Credentials.from_service_account_file("credentials.json")
drive = build('drive', 'v3', credentials=creds)

# === TRACCIAMENTO ===
cache = {}  # {preventivo_id: timestamp_ultimo_sollecito}
confermati = set()

# === FUNZIONI ===
def get_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])
    except Exception as e:
        print(f"Errore nel recupero sottocartelle: {e}")
        return []

def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get("files", [])
        return folders[0]['id'] if folders else None
    except Exception as e:
        print(f"Errore nella ricerca della cartella: {e}")
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

def invia_preventivo(gruppo_id, p):
    link = generate_share_link(p['id'])
    nome_file = p['name']
    messaggio = f"\U0001F4C4 *Nuovo preventivo disponibile:*\n\U0001F4C1 {nome_file}\n\U0001F517 {link}"
    try:
        bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
        bot.send_message(chat_id=GRUPPO_CONFERME_ID, text=f"\u2709\ufe0f Inviato preventivo '{nome_file}' al gruppo {gruppo_id}", parse_mode=telegram.ParseMode.MARKDOWN)
    except Exception as e:
        print(f"Errore invio a gruppo {gruppo_id}: {e}")

def invia_sollecito(gruppo_id, p):
    link = generate_share_link(p['id'])
    nome_file = p['name']
    messaggio = f"\u26A0\ufe0f *Sollecito:* Preventivo non ancora confermato.\n\U0001F4C1 {nome_file}\n\U0001F517 {link}"
    try:
        bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
        bot.send_message(chat_id=GRUPPO_CONFERME_ID, text=f"\u23F0 Sollecito per preventivo '{nome_file}' al gruppo {gruppo_id}", parse_mode=telegram.ParseMode.MARKDOWN)
    except Exception as e:
        print(f"Errore invio sollecito a gruppo {gruppo_id}: {e}")

def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("\u274C Cartella principale non trovata.")
        return
    gruppi = get_subfolders(root_id)
    for gruppo in gruppi:
        gruppo_id = gruppo['name'].replace("gruppo_", "")
        gruppo_folder_id = gruppo['id']
        preventivi = get_subfolders(gruppo_folder_id)
        for p in preventivi:
            preventivo_id = p['id']
            key = f"{gruppo_id}_{preventivo_id}"
            if key in confermati:
                continue
            if key not in cache:
                cache[key] = time.time()
                invia_preventivo(gruppo_id, p)
            else:
                elapsed = time.time() - cache[key]
                if elapsed >= SOLLECITO_INTERVALLO and elapsed <= SOLLECITO_MAX_ORE * 3600:
                    invia_sollecito(gruppo_id, p)
                elif elapsed > SOLLECITO_MAX_ORE * 3600:
                    print(f"\u274C Tempo massimo raggiunto per {key}, rimozione dalla coda.")
                    del cache[key]

def gestisci_conferme(update, context):
    chat_id = update.effective_chat.id
    messaggio = update.message.text.strip().lower()
    if messaggio in ["ok", "confermo", "va bene", "accetto"]:
        for key in list(cache.keys()):
            if key.startswith(str(chat_id)):
                confermati.add(key)
                del cache[key]
                bot.send_message(chat_id=chat_id, text="\u2705 Preventivo confermato!")
                bot.send_message(chat_id=GRUPPO_CONFERME_ID, text=f"\U0001F4CC Confermato: {key}")

# === AVVIO ===
if __name__ == '__main__':
    from telegram.ext import Updater, MessageHandler, Filters

    print("\U0001F680 BOT avviato e in ascolto...")

    updater = Updater(token=BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, gestisci_conferme))
    updater.start_polling()

    while True:
        try:
            scan_and_send()
        except Exception as e:
            print(f"Errore generale: {e}")
        time.sleep(CHECK_INTERVAL)
