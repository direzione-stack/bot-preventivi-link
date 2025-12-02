import os
import time
import logging
import gspread
from datetime import datetime, timedelta
from telegram import Bot
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

# Carica variabili ambiente
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup bot
bot = Bot(token=BOT_TOKEN)

# Setup Google Sheets API
google_creds = os.getenv("GOOGLE_CREDENTIALS")
if not google_creds:
    raise Exception("Google credentials not found")

import json
creds_dict = json.loads(google_creds)
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gspread_client = gspread.authorize(creds)
sheet = gspread_client.open_by_key(SPREADSHEET_ID).sheet1

# Constants
SOLLECITO_INTERVAL = timedelta(hours=5)
FINE_SOLLECITI = timedelta(hours=48)
SOLLECITO_MASSIMO = 9
MESSAGGIO_FINE = "Ci dispiace il lavoro sarà dato ad un altro nostro partner"

# Funzione di parsing della data
def parse_datetime(data_str, ora_str):
    return datetime.strptime(f"{data_str} {ora_str}", "%d/%m/%Y %H:%M")

# Main loop
def invia_messaggi():
    rows = sheet.get_all_records()
    now = datetime.now()
    aggiornamenti = []

    for i, row in enumerate(rows, start=2):  # Riga 2 = prima riga dati
        chat_id = row['chat_id']
        messaggio = row['messaggio_da_inviare']
        data = row['data']
        ora = row['ora']
        inviato = row.get('inviato', '')

        try:
            ora_invio = parse_datetime(data, ora)
        except:
            logger.warning(f"Formato orario errato alla riga {i}")
            continue

        if not inviato:
            if now >= ora_invio:
                bot.send_message(chat_id=chat_id, text=messaggio)
                sheet.update_cell(i, 6, f"1|{now.strftime('%d/%m/%Y %H:%M')}")
        else:
            split = inviato.split("|")
            count = int(split[0])
            ultima = datetime.strptime(split[1], "%d/%m/%Y %H:%M")
            if now - ora_invio > FINE_SOLLECITI:
                if count < SOLLECITO_MASSIMO:
                    bot.send_message(chat_id=chat_id, text=MESSAGGIO_FINE)
                    sheet.update_cell(i, 6, f"{count+1}|{now.strftime('%d/%m/%Y %H:%M')}")
            elif now - ultima >= SOLLECITO_INTERVAL:
                bot.send_message(chat_id=chat_id, text=messaggio)
                sheet.update_cell(i, 6, f"{count+1}|{now.strftime('%d/%m/%Y %H:%M')}")

if __name__ == "__main__":
    while True:
        try:
            invia_messaggi()
        except Exception as e:
            logger.error(f"Errore: {e}")
        time.sleep(60 * 5)  # Controlla ogni 5 minuti
