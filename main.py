import os
import time
import json
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext
from google.oauth2 import service_account
from googleapiclient.discovery import build

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
GOOGLE_CREDENTIALS = eval(os.getenv("GOOGLE_CREDENTIALS"))

bot = Bot(token=BOT_TOKEN)
updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

MAIN_FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60
SOLLECITI_ORE = [4, 8, 24, 48]
STATO_FILE = "stato.json"

def salva_stato(data):
    with open(STATO_FILE, "w") as f:
        json.dump(data, f)

def carica_stato():
    if os.path.exists(STATO_FILE):
        with open(STATO_FILE, "r") as f:
            return json.load(f)
    return {}

stato_preventivi = carica_stato()

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
        ore_passate = (now - datetime.fromisoformat(stato["timestamp"])).total_seconds() / 3600
        step = stato["solleciti"]
        if step < len(SOLLECITI_ORE) and ore_passate >= SOLLECITI_ORE[step]:
            if step < 3:
                invia_sollecito(stato["chat_id"], stato["nome"], step)
                stato["solleciti"] += 1
            else:
                invia_rifiuto(stato["chat_id"], stato["nome"])
                stato["confermato"] = True

def gestore_messaggi(update: Update, context: CallbackContext):
    msg = update.message.text.lower()
    chat_id = update.effective_chat.id
    conferme = ["ok", "confermo", "ricevuto", "va bene"]

    if any(c in msg for c in conferme):
        for key in stato_preventivi:
            if str(chat_id) in key and not stato_preventivi[key]["confermato"]:
                stato_preventivi[key]["confermato"] = True
                bot.send_message(chat_id=chat_id, text=f"✅ Confermato: {stato_preventivi[key]['nome']}")
                bot.send_message(chat_id=OWNER_ID, text=f"✅ Confermato da gruppo {chat_id}: {stato_preventivi[key]['nome']}")

def gestisci_migrazione(update: Update, context: CallbackContext):
    if update.message and update.message.migrate_to_chat_id:
        old_id = update.message.chat.id
        new_id = update.message.migrate_to_chat_id
        bot.send_message(chat_id=new_id, text="✅ Gruppo migrato a supergruppo. ID aggiornato automaticamente.")
        nuove_chiavi = {}
        for key in list(stato_preventivi):
            if str(old_id) in key:
                nuovo_key = key.replace(str(old_id), str(new_id))
                stato = stato_preventivi.pop(key)
                stato["chat_id"] = new_id
                nuove_chiavi[nuovo_key] = stato
        stato_preventivi.update(nuove_chiavi)

dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, gestore_messaggi))
dispatcher.add_handler(MessageHandler(Filters.status_update.migrate, gestisci_migrazione))

if __name__ == "__main__":
    updater.start_polling()
    print("🤖 Bot autoreattivo avviato...")
    while True:
        try:
            esegui_scansione()
            controlla_solleciti()
            salva_stato(stato_preventivi)
        except Exception as e:
            print("Errore:", e)
        time.sleep(CHECK_INTERVAL)
