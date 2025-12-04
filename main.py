import os
import time
import json
import telegram
import gspread
import traceback
from google.oauth2 import service_account

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE / SHEETS ===
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
gc = gspread.authorize(creds)
sheet = gc.open("Report Preventivi").sheet1

# === CONFIG ===
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # ogni 60 secondi
SOLLECITO_INTERVALLO = 4 * 60 * 60  # ogni 4 ore

# === TRACKING ===
cache = {}
solleciti = {}

# === UTILS ===
def aggiorna_stato(chat_id, stato):
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row.get("chat_id")) == str(chat_id):
            cell = f"D{i+2}"
            sheet.update(cell, stato)
            return

def aggiorna_timestamp(chat_id):
    ora = time.strftime("%Y-%m-%d %H:%M:%S")
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row.get("chat_id")) == str(chat_id):
            cell = f"C{i+2}"
            sheet.update(cell, ora)
            return

def check_conferma(messaggio):
    testo = messaggio.text.strip().lower()
    return testo in ["ok", "confermo", "va bene", "accetto"]

# === FUNZIONE INVIO ===
def invia_preventivi():
    rows = sheet.get_all_records()
    ora_attuale = time.time()

    for row in rows:
        chat_id = row.get("chat_id")
        folder = row.get("cartella")
        timestamp = row.get("timestamp_invio")
        stato = row.get("stato", "").lower()

        if stato == "completato":
            continue

        if not timestamp:
            try:
                messaggio = f"📁 *Nuovo preventivo disponibile:*
{folder}"
                bot.send_message(chat_id=chat_id, text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                aggiorna_timestamp(chat_id)
                solleciti[chat_id] = (ora_attuale, 0)
            except Exception as e:
                print(f"Errore invio a {chat_id}: {e}")
            continue

        ts_inizio = time.mktime(time.strptime(timestamp, "%Y-%m-%d %H:%M:%S"))
        tempo_trascorso = ora_attuale - ts_inizio

        if tempo_trascorso >= SOLLECITO_INTERVALLO:
            ultimo, numero = solleciti.get(chat_id, (ts_inizio, 0))
            if ora_attuale - ultimo >= SOLLECITO_INTERVALLO:
                try:
                    messaggio = f"⚠️ *Sollecito #{numero+1}:* conferma il preventivo {folder}"
                    bot.send_message(chat_id=chat_id, text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                    solleciti[chat_id] = (ora_attuale, numero+1)
                except Exception as e:
                    print(f"Errore sollecito a {chat_id}: {e}")

# === HANDLER MESSAGGI ===
def gestisci_messaggi(update, context):
    msg = update.message
    chat_id = msg.chat_id

    if check_conferma(msg):
        try:
            bot.send_message(chat_id=chat_id, text="✅ Preventivo confermato. Grazie!", parse_mode=telegram.ParseMode.MARKDOWN)
            aggiorna_stato(chat_id, "completato")
        except Exception as e:
            print(f"Errore risposta conferma: {e}")

# === MAIN ===
if __name__ == "__main__":
    print("✅ BOT avviato e in ascolto di nuovi preventivi...")

    from telegram.ext import Updater, MessageHandler, Filters
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), gestisci_messaggi))
    updater.start_polling()

    while True:
        try:
            invia_preventivi()
        except Exception as e:
            print(f"Errore generale:", traceback.format_exc())
        time.sleep(CHECK_INTERVAL)
