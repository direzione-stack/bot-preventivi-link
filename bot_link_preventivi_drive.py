import os
import json
import datetime
import time
import threading
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from telegram import Bot, Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext
import gspread

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDS_JSON = json.loads(os.getenv("GOOGLE_CREDENTIALS"))

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets"
]
creds = Credentials.from_service_account_info(GOOGLE_CREDS_JSON, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=creds)
gspread_client = gspread.authorize(creds)
sheet = gspread_client.open_by_key(SPREADSHEET_ID).sheet1

bot = Bot(token=BOT_TOKEN)
updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher
parole_conferma = ["ok", "confermo", "va bene", "ricevuto"]
current_states = {}

def get_folder_id(name, parent=None):
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent:
        q += f" and '{parent}' in parents"
    res = drive_service.files().list(q=q, fields="files(id, name)").execute().get("files", [])
    return res[0]["id"] if res else None

def share_folder(folder_id):
    perm = { "type": "anyone", "role": "reader" }
    drive_service.permissions().create(fileId=folder_id, body=perm).execute()

def log_to_sheet(gruppo_id, nome, link, stato):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([str(gruppo_id), nome, link, stato, now])

def invia_link(gruppo_id, nome, folder_id):
    link = f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"
    msg = f"📩 Nuovo preventivo:\n<b>{nome}</b>\n🔗 {link}"
    bot.send_message(chat_id=gruppo_id, text=msg, parse_mode="HTML")
    log_to_sheet(gruppo_id, nome, link, "🟡 In attesa")
    current_states[gruppo_id] = {
        "nome": nome,
        "link": link,
        "confermato": False,
        "solleciti": 0
    }

def solleciti(gruppo_id):
    stato = current_states[gruppo_id]
    while not stato["confermato"] and stato["solleciti"] < 12:
        time.sleep(4 * 60 * 60)
        stato["solleciti"] += 1
        if not stato["confermato"]:
            bot.send_message(chat_id=gruppo_id, text=f"⏰ Sollecito #{stato['solleciti']} per conferma:\n{stato['link']}")
    if not stato["confermato"]:
        bot.send_message(chat_id=gruppo_id, text="⚠️ Nessuna conferma ricevuta. Passiamo ad altra impresa.")
        bot.send_message(chat_id=OWNER_ID, text=f"❌ Nessuna conferma da gruppo {gruppo_id} per: {stato['nome']}")
        log_to_sheet(gruppo_id, stato["nome"], stato["link"], "❌ Nessuna risposta")

def handle(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    if chat_id in current_states and any(p in text for p in parole_conferma):
        stato = current_states[chat_id]
        context.bot.send_message(chat_id=chat_id, text=f"✅ Conferma ricevuta per: {stato['nome']}")
        context.bot.send_message(chat_id=OWNER_ID, text=f"✅ Confermato da gruppo {chat_id}: {stato['nome']}")
        stato["confermato"] = True
        log_to_sheet(chat_id, stato["nome"], stato["link"], "✅ Confermato")

dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle))

def main():
    root_id = get_folder_id("PreventiviTelegram")
    if not root_id:
        print("❌ Cartella principale non trovata.")
        return
    gruppi = drive_service.files().list(
        q=f"'{root_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()

    for g in gruppi.get("files", []):
        try:
            gid = int(g["name"].replace("gruppo_", ""))
        except:
            continue
        preventivi = drive_service.files().list(
            q=f"'{g['id']}' in parents and mimeType='application/vnd.google-apps.folder'",
            fields="files(id, name)"
        ).execute()

        for p in preventivi.get("files", []):
            if gid in current_states:
                continue
            share_folder(p["id"])
            invia_link(gid, p["name"], p["id"])
            threading.Thread(target=solleciti, args=(gid,), daemon=True).start()

    print("🤖 Bot attivo - invia solo link cartelle Drive.")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
