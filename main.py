import os
import time
import json
import telegram
import gspread
import traceback
from google.oauth2 import service_account
from datetime import datetime

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE SHEET ===
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
gc = gspread.authorize(creds)
sheet = gc.open("Report Preventivi").sheet1

# === CONFIGURAZIONI ===
FREQUENZA_CONTROLLO = 60         # Ogni 60 secondi
FREQUENZA_SOLLECITI = 4 * 3600  # Ogni 4 ore
CONFERME = ["ok", "confermo", "va bene", "accetto"]

# === STATO ===
cache_inviati = {}
tempi_solleciti = {}

# === FUNZIONI ===
def invia_preventivi():
    righe = sheet.get_all_records()
    ora = time.time()

    for i, riga in enumerate(righe, start=2):
        chat_id = riga.get("chat_id")
        cartella = riga.get("cartella")
        stato = riga.get("stato", "").lower()
        timestamp = riga.get("timestamp_invio")

        if stato == "completato":
            continue

        chiave = f"{chat_id}_{cartella}"
        tempo_ultimo = cache_inviati.get(chiave)

        if not timestamp:
            messaggio = f"📂 *Nuovo preventivo disponibile:*\n`{cartella}`"
            try:
                bot.send_message(chat_id=chat_id, text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                now_str = datetime.utcnow().isoformat()
                sheet.update_cell(i, 3, now_str)
                cache_inviati[chiave] = ora
                tempi_solleciti[chiave] = [ora, 0]  # timestamp, n solleciti
            except Exception as e:
                print(f"❌ Errore invio a {chat_id}: {e}")
            continue

        # Sollecito
        if chiave in tempi_solleciti:
            ts_inizio, num_solleciti = tempi_solleciti[chiave]
            tempo_passato = ora - ts_inizio

            if tempo_passato >= FREQUENZA_SOLLECITI:
                try:
                    testo = f"🔔 *Sollecito #{num_solleciti + 1}* per confermare il preventivo:\n`{cartella}`"
                    bot.send_message(chat_id=chat_id, text=testo, parse_mode=telegram.ParseMode.MARKDOWN)
                    tempi_solleciti[chiave] = [ora, num_solleciti + 1]
                except Exception as e:
                    print(f"❌ Errore sollecito {chat_id}: {e}")


def ascolta_risposte():
    updates = bot.get_updates(timeout=10)
    for update in updates:
        msg = update.message
        if not msg or not msg.text:
            continue

        testo = msg.text.strip().lower()
        chat_id = str(msg.chat_id)
        if any(r in testo for r in CONFERME):
            righe = sheet.get_all_records()
            for i, riga in enumerate(righe, start=2):
                if str(riga.get("chat_id")) == chat_id and riga.get("stato", "").lower() != "completato":
                    sheet.update_cell(i, 4, "completato")
                    bot.send_message(chat_id=chat_id, text="✅ Preventivo confermato! Grazie.")
                    break


# === MAIN ===
print("✅ BOT avviato. In ascolto...")
while True:
    try:
        invia_preventivi()
        ascolta_risposte()
    except Exception as e:
        print(f"❌ Errore generale:\n{traceback.format_exc()}")
    time.sleep(FREQUENZA_CONTROLLO)
