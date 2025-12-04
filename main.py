# ✅ BOT CONFERMA PREVENTIVI con solleciti ogni 4 ore fino a 48 ore

import os
import time
import threading
from datetime import datetime, timedelta
from telegram import Bot, Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- CONFIGURAZIONE ---
BOT_TOKEN = "8405573823:AAHcPQEGQIgchdtC-N7MIsakmrQk-gJ8KAw"
CONFIRMATION_GROUP_ID = -5071236492
DRIVE_FOLDER_ID = "1ZvMpmFyAJlosq0hHTKD4NPFmEAaHiLsn"
SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"

# --- GOOGLE DRIVE SETUP ---
creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=creds)

# --- GESTIONE STATO PREVENTIVI ---
stati_preventivi = {}  # {chat_id: {"nome": str, "confermato": bool, "timestamp": datetime, "folder_id": str}}

# --- FUNZIONI ---
def get_group_folders():
    results = drive_service.files().list(q=f"'{DRIVE_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder'",
                                         fields="files(id, name)").execute()
    return results.get('files', [])

def crea_link_condivisibile(file_id):
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()
    except:
        pass
    return f"https://drive.google.com/drive/folders/{file_id}"

def invia_preventivo(bot, chat_id, nome, folder_id):
    link = crea_link_condivisibile(folder_id)
    messaggio = f"📂 Nuovo preventivo da confermare: *{nome}*\n{link}"
    bot.send_message(chat_id=chat_id, text=messaggio, parse_mode='Markdown')
    stati_preventivi[chat_id] = {
        "nome": nome,
        "confermato": False,
        "timestamp": datetime.now(),
        "folder_id": folder_id
    }
    avvia_solleciti(bot, chat_id)

def avvia_solleciti(bot, chat_id):
    def sollecita():
        for i in range(1, 13):  # max 12 solleciti ogni 4h (48h)
            time.sleep(4 * 60 * 60)  # 4 ore
            stato = stati_preventivi.get(chat_id)
            if not stato or stato.get("confermato"):
                break
            if i < 12:
                bot.send_message(chat_id=chat_id,
                                 text=f"⏰ Ricordiamo di confermare il preventivo: {stato['nome']}")
            else:
                bot.send_message(chat_id=chat_id,
                                 text=f"❗ Nessuna conferma ricevuta per: {stato['nome']}. Il lavoro verrà affidato ad un altro partner.")
    threading.Thread(target=sollecita).start()

def handle_message(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    if chat_id in stati_preventivi and not stati_preventivi[chat_id]["confermato"]:
        if any(k in text for k in ["ok", "confermo", "va bene", "accetto"]):
            stati_preventivi[chat_id]["confermato"] = True
            nome = stati_preventivi[chat_id]["nome"]
            context.bot.send_message(chat_id=chat_id,
                                     text=f"✅ Conferma ricevuta per il preventivo: {nome}")
            context.bot.send_message(chat_id=CONFIRMATION_GROUP_ID,
                                     text=f"📩 Il gruppo {chat_id} ha confermato il preventivo: {nome}")

def avvia_bot():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    updater.start_polling()
    print("🤖 Bot avviato con solleciti attivi...")
    return updater.bot

def monitora_drive(bot):
    gia_inviati = set()
    while True:
        try:
            gruppi = get_group_folders()
            for gruppo in gruppi:
                gruppo_id = gruppo['id']
                sottocartelle = drive_service.files().list(q=f"'{gruppo_id}' in parents and mimeType = 'application/vnd.google-apps.folder'",
                                                         fields="files(id, name)").execute().get('files', [])
                for sotto in sottocartelle:
                    unique_id = f"{gruppo_id}_{sotto['id']}"
                    if unique_id not in gia_inviati:
                        try:
                            chat_id = int(gruppo['name'].replace("gruppo_", ""))
                            invia_preventivo(bot, chat_id, sotto['name'], sotto['id'])
                            gia_inviati.add(unique_id)
                        except Exception as e:
                            print("Errore:", e)
            time.sleep(60)
        except Exception as e:
            print("Errore monitoraggio drive:", e)
            time.sleep(60)

if __name__ == '__main__':
    bot = avvia_bot()
    monitora_drive(bot)
