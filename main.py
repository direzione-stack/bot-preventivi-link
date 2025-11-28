import os
import json
import time
import logging
from telegram import Bot, Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext
from google.oauth2 import service_account
from googleapiclient.discovery import build
from scheduler import avvia_solleciti, current_states

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_CREDS = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

bot = Bot(token=BOT_TOKEN)
updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

credentials = service_account.Credentials.from_service_account_info(
    GOOGLE_CREDS, scopes=["https://www.googleapis.com/auth/drive"]
)
drive_service = build("drive", "v3", credentials=credentials)

def lista_cartelle_gruppo():
    res = drive_service.files().list(
        q=f"'{DRIVE_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder'",
        fields="files(id, name)"
    ).execute()
    return res.get("files", [])

def lista_cartelle_preventivo(group_id):
    res = drive_service.files().list(
        q=f"'{group_id}' in parents and mimeType = 'application/vnd.google-apps.folder'",
        fields="files(id, name)"
    ).execute()
    return res.get("files", [])
    def invia_preventivo(chat_id, nome, folder_id):
    link = f"https://drive.google.com/drive/folders/{folder_id}"
    msg = f"📂 Nuovo preventivo da confermare: *{nome}*\n🔗 {link}"
    bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

def monitora():
    while True:
        gruppi = lista_cartelle_gruppo()
        for gruppo in gruppi:
            try:
                chat_id = int(gruppo['name'].replace("gruppo_", ""))
                sottocartelle = lista_cartelle_preventivo(gruppo['id'])
                for cartella in sottocartelle:
                    nome = cartella['name']
                    if chat_id not in current_states:
                        current_states[chat_id] = {}
                    if nome not in current_states[chat_id]:
                        current_states[chat_id][nome] = {
                            "confermato": False,
                            "timestamp": time.time(),
                            "id": cartella['id']
                        }
                        invia_preventivo(chat_id, nome, cartella['id'])
            except Exception as e:
                logger.warning(f"Errore nel gruppo {gruppo['name']}: {e}")
        time.sleep(60)
        def gestisci_risposta(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    parole_conferma = ["ok", "confermo", "va bene", "ricevuto"]

    if chat_id in current_states:
        for nome, stato in current_states[chat_id].items():
            if not stato["confermato"]:
                if any(p in text for p in parole_conferma):
                    current_states[chat_id][nome]["confermato"] = True
                    bot.send_message(chat_id=chat_id, text=f"✅ Confermato: {nome}")
                    bot.send_message(chat_id=OWNER_ID, text=f"✅ Il gruppo {chat_id} ha confermato il preventivo: {nome}")

# Gestione messaggi di testo
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, gestisci_risposta))

if __name__ == '__main__':
    logger.info("🤖 Bot avviato. In ascolto...")
    avvia_solleciti(bot, OWNER_ID)
    updater.start_polling()
    monitora()
