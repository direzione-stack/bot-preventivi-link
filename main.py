import os
import time
import json
import telegram
import traceback
from google.oauth2 import service_account
from googleapiclient.discovery import build

# CONFIG
BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

bot = telegram.Bot(token=BOT_TOKEN)

# Setup Google Drive API
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
drive = build('drive', 'v3', credentials=creds)

# Config
ROOT_FOLDER_NAME = "PreventiviTelegram"  # la cartella principale su Drive
CHECK_INTERVAL = 60        # ogni 60 secondi
SOLLECITO_INTERVALO = 4 * 3600  # ogni 4 ore
SCADENZA = 48 * 3600       # dopo 48 ore dal primo invio

# Tracciamento in memoria
cache = {}  # {folder_id: {chat_id, nome, timestamp_invio}}

def get_subfolders(parent_id):
    q = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    resp = drive.files().list(q=q, fields="files(id, name)").execute()
    return resp.get('files', [])

def get_folder_id_by_name(name):
    q = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    resp = drive.files().list(q=q, fields="files(id, name)").execute()
    folders = resp.get('files', [])
    return folders[0]['id'] if folders else None

def share_folder_public(folder_id):
    try:
        drive.permissions().create(
            fileId=folder_id,
            body={"type":"anyone", "role":"reader"},
        ).execute()
    except Exception:
        pass
    return f"https://drive.google.com/drive/folders/{folder_id}"

def scan_and_send():
    root_id = get_folder_id_by_name(ROOT_FOLDER_NAME)
    if not root_id:
        print("⚠️ Cartella principale non trovata:", ROOT_FOLDER_NAME)
        return

    gruppi = get_subfolders(root_id)
    for g in gruppi:
        gruppo_folder_id = g['id']
        gruppo_id = g['name'].replace("gruppo_", "")
        subfolders = get_subfolders(gruppo_folder_id)
        for p in subfolders:
            folder_id = p['id']
            key = folder_id
            if key in cache:
                continue  # già inviato

            link = share_folder_public(folder_id)
            nome = p['name']
            text = f"📄 *Nuovo preventivo disponibile*\n{nome}\n🔗 {link}"
            try:
                bot.send_message(chat_id=int(gruppo_id), text=text, parse_mode=telegram.ParseMode.MARKDOWN)
                cache[key] = {
                    "chat_id": gruppo_id,
                    "nome": nome,
                    "timestamp": time.time()
                }
                print("📬 Inviato:", nome, "-> gruppo", gruppo_id)
            except Exception as e:
                print("❌ Errore invio:", e)

def gestisci_solleciti_e_scadenze():
    now = time.time()
    for key, info in list(cache.items()):
        elapsed = now - info["timestamp"]
        if elapsed > SCADENZA:
            try:
                bot.send_message(chat_id=int(info["chat_id"]),
                                 text=f"⛔ Il preventivo *{info['nome']}* non è stato confermato. Termine scaduto.")
            except Exception:
                pass
            del cache[key]
        elif elapsed > SOLLECITO_INTERVALO:
            try:
                bot.send_message(chat_id=int(info["chat_id"]),
                                 text=f"🔔 Sollecito: manca conferma per il preventivo *{info['nome']}*")
                cache[key]["timestamp"] = now
            except Exception:
                pass

def handle_confirm(update, context):
    chat_id = update.message.chat_id
    testo = update.message.text.lower()
    if any(w in testo for w in ["ok", "confermo", "va bene", "accetto"]):
        for key, info in list(cache.items()):
            if str(info["chat_id"]) == str(chat_id):
                nome = info["nome"]
                bot.send_message(chat_id, f"✅ Preventivo *{nome}* confermato! Grazie.")
                print("✅ Confermato:", nome, "dal gruppo", chat_id)
                del cache[key]
                break

def main():
    from telegram.ext import Updater, MessageHandler, Filters
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_confirm))

    updater.start_polling()
    print("🤖 Bot attivo (solo Google Drive + Telegram)")

    while True:
        try:
            scan_and_send()
            gestisci_solleciti_e_scadenze()
        except Exception as e:
            print("❌ Errore ciclo:", traceback.format_exc())
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
