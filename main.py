import os
import time
import json
import telegram
import gspread
import traceback
from google.oauth2 import service_account

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE ===
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID).sheet1

# === STATO ===
cache = {}
SOLLECITO_INTERVALLO = 4 * 3600  # 4 ore
ultima_verifica = 0

print("✅ BOT avviato e in ascolto di nuovi preventivi...")

def invia_messaggio(chat_id, testo):
    try:
        bot.send_message(chat_id=chat_id, text=testo, parse_mode=telegram.ParseMode.MARKDOWN)
        return True
    except Exception as e:
        print(f"❌ Errore invio a gruppo {chat_id}: {e}")
        return False

def controlla_nuovi_preventivi():
    global cache
    righe = sheet.get_all_records()
    ora = time.time()

    for i, riga in enumerate(righe, start=2):
        preventivo = riga.get("Nome Preventivo")
        chat_id = str(riga.get("ID Gruppo"))
        stato = str(riga.get("Stato", "")).strip().lower()

        if stato == "completato":
            continue

        if preventivo not in cache:
            messaggio = f"*📂 Nuovo preventivo disponibile:*
{preventivo}"
            if invia_messaggio(chat_id, messaggio):
                cache[preventivo] = {
                    "time": ora,
                    "chat_id": chat_id,
                    "row": i
                }
                sheet.update_cell(i, list(riga.keys()).index("Timestamp Invio") + 1, time.strftime('%Y-%m-%d %H:%M:%S'))


def invia_solleciti():
    ora = time.time()
    for preventivo, info in cache.items():
        if ora - info["time"] > SOLLECITO_INTERVALLO:
            messaggio = f"*🔔 Sollecito:* Confermare il preventivo: *{preventivo}*"
            if invia_messaggio(info["chat_id"], messaggio):
                cache[preventivo]["time"] = ora


def ascolta_conferme():
    updates = bot.get_updates(limit=100, timeout=5)

    for update in updates:
        if update.message:
            testo = update.message.text.lower()
            chat_id = str(update.message.chat_id)

            if any(k in testo for k in ["ok", "confermo", "va bene", "accetto"]):
                righe = sheet.get_all_records()
                for i, riga in enumerate(righe, start=2):
                    if str(riga.get("ID Gruppo")) == chat_id and riga.get("Stato", "").lower() != "completato":
                        preventivo = riga.get("Nome Preventivo")
                        sheet.update_cell(i, list(riga.keys()).index("Stato") + 1, "completato")
                        invia_messaggio(chat_id, f"✅ Preventivo *{preventivo}* confermato. Grazie!")
                        if preventivo in cache:
                            del cache[preventivo]


while True:
    try:
        ascolta_conferme()

        if time.time() - ultima_verifica >= 60:
            controlla_nuovi_preventivi()
            invia_solleciti()
            ultima_verifica = time.time()

    except Exception as e:
        print(f"❌ Errore generale:\n{traceback.format_exc()}")

    time.sleep(10)
