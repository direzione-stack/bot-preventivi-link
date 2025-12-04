# main.py
import os
import time
import telegram
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from report_writer import log_confirmation  # modulo opzionale

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # ogni 60 secondi
SOLLECITO_INTERVAL = 4 * 60 * 60  # ogni 4 ore

bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
creds = service_account.Credentials.from_service_account_info(eval(os.getenv("GOOGLE_CREDENTIALS")))
drive = build("drive", "v3", credentials=creds)

# === TRACKING ===
cache = {}
solleciti = {}


def get_folder_id_by_name(name):
    results = drive.files().list(q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                                 spaces='drive', fields="files(id, name)").execute()
    folders = results.get('files', [])
    return folders[0]['id'] if folders else None


def get_subfolders(parent_id):
    results = drive.files().list(q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                                 spaces='drive', fields="files(id, name)").execute()
    return results.get('files', [])


def generate_share_link(folder_id):
    permission = {
        'type': 'anyone',
        'role': 'reader'
    }
    try:
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass  # permission already exists
    return f"https://drive.google.com/drive/folders/{folder_id}"


def send_preventivo(gruppo_id, nome, link):
    messaggio = f"*Nuovo preventivo disponibile:*\n{nome_file}\n{link}"
    bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
    cache[f"{gruppo_id}_{nome}"] = time.time()
    solleciti[f"{gruppo_id}_{nome}"] = time.time()


def invia_solleciti():
    for chiave, ts_invio in solleciti.items():
        if time.time() - ts_invio >= SOLLECITO_INTERVAL:
            gruppo_id, nome = chiave.split("_", 1)
            bot.send_message(chat_id=gruppo_id, text=f"⏰ *Sollecito:* confermi il preventivo [{nome}]?",
                             parse_mode=telegram.ParseMode.MARKDOWN)
            solleciti[chiave] = time.time()


def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("❌ Cartella root non trovata.")
        return

    gruppi = get_subfolders(root_id)
    for gruppo in gruppi:
        gruppo_id = gruppo['name'].replace("gruppo_", "")
        gruppo_folder_id = gruppo['id']
        preventivi = get_subfolders(gruppo_folder_id)

        for p in preventivi:
            chiave = f"{gruppo_id}_{p['name']}"
            if chiave not in cache:
                link = generate_share_link(p['id'])
                send_preventivo(gruppo_id, p['name'], link)


def gestisci_risposte(update, context):
    testo = update.message.text.lower()
    chat_id = str(update.message.chat_id)
    nome_utente = update.message.from_user.full_name
    if any(k in testo for k in ["ok", "confermo", "va bene", "accetto"]):
        context.bot.send_message(chat_id=chat_id, text="✅ Preventivo confermato, grazie!")
        log_confirmation(chat_id, nome_utente)  # scrive su Google Sheet (opzionale)


# === AVVIO ===
if __name__ == '__main__':
    from telegram.ext import Updater, MessageHandler, Filters

    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, gestisci_risposte))

    updater.start_polling()
    print("🚀 BOT avviato e in ascolto...")

    while True:
        try:
            scan_and_send()
            invia_solleciti()
        except Exception as e:
            print(f"❌ Errore: {e}")
        time.sleep(CHECK_INTERVAL)
