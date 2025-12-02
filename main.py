import logging
import os
import time
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from telegram import Bot, ParseMode
from telegram.error import TelegramError

# Imposta logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Imposta credenziali Google Drive
GOOGLE_CREDS = os.getenv("GOOGLE_CREDENTIALS")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
OWNER_ID = int(os.getenv("OWNER_ID"))
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not all([GOOGLE_CREDS, SPREADSHEET_ID, BOT_TOKEN]):
    logger.error("Missing required environment variables.")
    exit(1)

creds = Credentials.from_service_account_info(eval(GOOGLE_CREDS))
gspread_client = gspread.authorize(creds)
sheet = gspread_client.open_by_key(SPREADSHEET_ID).sheet1

bot = Bot(token=BOT_TOKEN)

def read_sheet():
    try:
        return sheet.get_all_records()
    except Exception as e:
        logger.error(f"Errore nel leggere il foglio: {e}")
        return []

def send_reminder(row):
    try:
        group_id = int(row['chat_id'])
        message = row['messaggio_da_inviare']
        if message:
            bot.send_message(chat_id=group_id, text=message, parse_mode=ParseMode.HTML)
            logger.info(f"Messaggio inviato al gruppo {group_id}")
    except TelegramError as e:
        logger.error(f"Errore Telegram: {e}")
    except Exception as e:
        logger.error(f"Errore generico nell'invio: {e}")

def update_sent_flag(index):
    try:
        sheet.update_cell(index + 2, 5, "SI")
    except Exception as e:
        logger.warning(f"Errore aggiornamento flag su riga {index+2}: {e}")

def check_and_send():
    logger.info("Controllo nuovi messaggi da inviare...")
    rows = read_sheet()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    for i, row in enumerate(rows):
        if row.get("inviato", "") != "SI":
            data = row.get("data")
            ora = row.get("ora")
            if not data or not ora:
                continue
            scheduled_time = f"{data} {ora}"
            if now >= scheduled_time:
                send_reminder(row)
                update_sent_flag(i)

if __name__ == '__main__':
    logger.info("Bot avviato.")
    while True:
        try:
            check_and_send()
            time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Interrotto manualmente.")
            break
        except Exception as e:
            logger.error(f"Errore inaspettato: {e}")
            time.sleep(30)
