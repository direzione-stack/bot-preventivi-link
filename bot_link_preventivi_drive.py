import os
import time
import json
from datetime import datetime, timedelta
from telegram import Bot, Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext
from google.oauth2 import service_account
from googleapiclient.discovery import build

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
GOOGLE_CREDENTIALS = eval(os.getenv("GOOGLE_CREDENTIALS"))
CHECK_INTERVAL = 60  # ogni 60 secondi
SOLLECITI_ORE = [4, 8, 24, 48]

bot = Bot(token=BOT_TOKEN)
updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

MAIN_FOLDER_NAME = "PreventiviTelegram"
stato_preventivi = {}

def trova_cartella_principale():
    res = drive_service.files().list(
        q=f"name='{MAIN_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()
    return res.get('files', [None])[0]['id'] if res.get('files') else None

def trova_sottocartelle(folder_id):
    res = drive_service.files().list(
        q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()
    return res.get('files', [])

def crea_link_pubblico(folder_id):
    drive_service.permissions().create(
        fileId=folder_id,
        body={"role": "reader", "type": "anyone"},
        fields="id"
    ).execute()
    return f"https://drive.google.com/drive/folders/{folder_id}"

def invia_messaggio_iniziale(chat_id, nome, link):
    testo = f"📩 *Nuovo preventivo da confermare:*\n[{nome}]({link})"
    bot.send_message(chat_id=chat_id, text=testo, parse_mode="Markdown")

def invia_sollecito(chat_id, nome, step):
    testo = f"⏰ *Sollecito {step + 1}* - In attesa della conferma del preventivo: {nome}"
    bot.send_message(chat_id=chat_id, text=testo, parse_mode="Markdown")

def invia_rifiuto(chat_id, nome):
    testo = f"⚠️ Nessuna risposta ricevuta. Il preventivo '{nome}' verrà assegnato ad un'altra impresa."
    bot.send_message(chat_id=chat_id, text=testo)

def esegui_scansione():
    principale = trova_cartella_principale()
    if not principale:
        print("Cartella principale non trovata")
        return

    gruppi = trova_sottocartelle(principale)
    for gruppo in gruppi:
        if not gruppo['name'].startswith("gruppo_"):
            continue

        chat_id = int(gruppo['name'].replace("gruppo_", ""))
        preventivi = trova_sottocartelle(gruppo['id'])

        for p in preventivi:
            key = f"{chat_id}-{p['id']}"
            if key not in stato_preventivi:
                link = crea_link_pubblico(p['id'])
                invia_messaggio_iniziale(chat_id, p['name'], link)
                stato_preventivi[key] = {
                    "chat_id": chat_id,
                    "nome": p["name"],
                    "link": link,
                    "timestamp": datetime.now().isoformat(),
                    "solleciti": 0,
                    "confermato": False
                }

def controlla_solleciti():
    now = datetime.now()
    for key, stato in stato_preventivi.items():
        if stato["confermato"]:
            continue
        tempo_trascorso = now - datetime.fromisoformat(stato["timestamp"])
        ore = tempo_trascorso.total_seconds() / 3600
        step = stato["solleciti"]

        if step < len(SOLLECITI_ORE) and ore >= SOLLECITI_ORE[step]:
            if step < 3:
                invia_sollecito(stato["chat_id"], stato["nome"], step)
                stato_preventivi[key]["solleciti"] += 1
            else:
                invia_rifiuto(stato["chat_id"], stato["nome"])
                stato_preventivi[key]["confermato"] = True

def gestore_messaggi(update: Update, context: CallbackContext):
    msg = update.message.text.lower()
    chat_id = update.effective_chat.id
    parole_conferma = ["ok", "confermo", "ricevuto", "va bene"]

    if any(p in msg for p in parole_conferma):
        for key in list(stato_preventivi):
            if str(chat_id) in key and not stato_preventivi[key]["confermato"]:
                bot.send_message(chat_id=chat_id, text=f"✅ Conferma ricevuta per: {stato_preventivi[key]['nome']}")
                stato_preventivi[key]["confermato"] = True
                bot.send_message(chat_id=OWNER_ID, text=f"✅ Confermato: {stato_preventivi[key]['nome']} dal gruppo {chat_id}")

dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, gestore_messaggi))

if __name__ == "__main__":
    updater.start_polling()
    print("🤖 Bot in ascolto con solleciti attivi...")
    while True:
        try:
            esegui_scansione()
            controlla_solleciti()
        except Exception as e:
            print("Errore:", e)
        time.sleep(CHECK_INTERVAL)
