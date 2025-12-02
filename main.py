import os
import logging
import time
import gspread
from datetime import datetime, timedelta
from telegram import Bot, ParseMode
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Variabili ambiente
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

bot = Bot(token=BOT_TOKEN)
gs_client = gspread.service_account_from_dict(eval(os.getenv("GOOGLE_CREDENTIALS")))
sheet = gs_client.open_by_key(SPREADSHEET_ID).sheet1

def parse_row(row):
    try:
        chat_id = int(row[0])
        message = row[1]
        date_str = row[2]
        time_str = row[3]
        sent_flag = row[4].strip().lower() == 'yes'
        return chat_id, message, date_str, time_str, sent_flag
    except Exception as e:
        logger.error(f"Errore parsing riga: {row} - {e}")
        return None

def send_message(chat_id, message):
    try:
        bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
        logger.info(f"Messaggio inviato a {chat_id}")
    except Exception as e:
        logger.error(f"Errore invio a {chat_id}: {e}")

def check_and_send():
    rows = sheet.get_all_values()[1:]  # salta intestazione
    now = datetime.now()

    for idx, row in enumerate(rows, start=2):
        parsed = parse_row(row)
        if not parsed:
            continue

        chat_id, message, date_str, time_str, sent_flag = parsed

        try:
            scheduled_time = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
        except ValueError:
            logger.warning(f"Formato data non valido nella riga {idx}: {date_str} {time_str}")
            continue

        elapsed = now - scheduled_time

        if not sent_flag:
            if elapsed >= timedelta(minutes=0):
                send_message(chat_id, message)
                sheet.update_cell(idx, 5, 'YES')
                sheet.update_cell(idx, 6, now.isoformat())  # colonna 6: prima ora invio

        else:
            try:
                first_sent_time = datetime.fromisoformat(row[5])
            except:
                continue

            reminders_sent = int(row[6]) if len(row) > 6 and row[6].isdigit() else 0
            next_reminder_due = first_sent_time + timedelta(hours=5 * (reminders_sent + 1))

            if now >= next_reminder_due and elapsed <= timedelta(hours=48):
                send_message(chat_id, f"🔔 <b>Gentile partner, ti ricordiamo di confermare:</b>\n{message}")
                sheet.update_cell(idx, 7, str(reminders_sent + 1))
            elif elapsed > timedelta(hours=48) and (len(row) < 8 or row[7].strip().upper() != "YES"):
                send_message(chat_id, "❌ Ci dispiace, il lavoro sarà dato ad un altro nostro partner.")
                sheet.update_cell(idx, 8, 'YES')  # colonna 8 = sollecito finale inviato

if __name__ == "__main__":
    while True:
        try:
            check_and_send()
        except Exception as e:
            logger.error(f"Errore nel ciclo: {e}")
        time.sleep(60)  # ogni minuto
