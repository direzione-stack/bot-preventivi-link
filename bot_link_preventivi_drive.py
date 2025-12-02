import os
import time
import json
import logging
import gspread
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO)

# Variabili ambiente
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

# Converti JSON stringa in dizionario
if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

# Setup bot
bot = Bot(token=BOT_TOKEN)

# Google Sheets auth
gc = gspread.service_account_from_dict(GOOGLE_CREDS_JSON)
sheet = gc.open_by_key(SPREADSHEET_ID).sheet1

# Gruppi Telegram
GRUPPI = {
    "-1003418284764": "Mustafa",
    "-100xxxxxxxxxx": "GruppoB",
    "-100yyyyyyyyyy": "GruppoC"
}

# Prevenzione doppio invio
cache = {}

# Tempo massimo attesa (in secondi) prima del sollecito
MAX_ATTESA = 4 * 3600  # 4 ore

# 🔁 Controlla nuovi preventivi
def check_nuovi_preventivi():
    rows = sheet.get_all_records()
    now = time.time()

    for row in rows:
        preventivo = row.get("Nome Preventivo")
        gruppo_id = str(row.get("ID Gruppo"))
        confermato = row.get("Confermato", "").strip().lower()
        timestamp = row.get("Timestamp", "")

        if confermato == "sì":
            continue

        if not preventivo or gruppo_id not in GRUPPI:
            continue

        if preventivo in cache:
            continue

        messaggio = f"📄 <b>Nuovo preventivo da confermare</b>:\n<b>{preventivo}</b>"
        try:
            bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode=ParseMode.HTML)
            cache[preventivo] = {
                "sent_time": now,
                "gruppo": gruppo_id
            }
        except Exception as e:
            logging.error(f"Errore invio messaggio: {e}")

# 🔁 Invia solleciti
def invia_solleciti():
    now = time.time()
    rows = sheet.get_all_records()

    for row in rows:
        preventivo = row.get("Nome Preventivo")
        gruppo_id = str(row.get("ID Gruppo"))
        confermato = row.get("Confermato", "").strip().lower()

        if confermato == "sì" or preventivo not in cache:
            continue

        tempo_passato = now - cache[preventivo]["sent_time"]

        if tempo_passato >= MAX_ATTESA:
            try:
                bot.send_message(chat_id=gruppo_id, text=f"🔔 <b>Promemoria:</b> il preventivo <b>{preventivo}</b> è ancora in attesa di conferma.", parse_mode=ParseMode.HTML)
                cache[preventivo]["sent_time"] = now
            except Exception as e:
                logging.error(f"Errore sollecito: {e}")
