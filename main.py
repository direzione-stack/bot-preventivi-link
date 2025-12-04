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
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE / SHEETS ===
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)
sheet = sh.sheet1

# === COSTANTI ===
SOLLECITO_INTERVALLO = 4 * 60 * 60  # ogni 4 ore
FINE_SOLLECITI = 48 * 60 * 60       # max 48 ore

# === TRACKING ===
solleciti = {}
cache = {}

# === FUNZIONE INVIO MESSAGGI ===
def invia_messaggio(chat_id, testo):
    try:
        bot.send_message(chat_id=chat_id, text=testo, parse_mode=telegram.ParseMode.MARKDOWN)
    except Exception as e:
        print(f"❌ Errore invio a gruppo {chat_id}: {e}")

# === FUNZIONE PRINCIPALE ===
def ciclo():
    righe = sheet.get_all_records()
    ora_attuale = datetime.utcnow()

    for idx, riga in enumerate(righe):
        chat_id = int(riga.get("chat_id", 0))
        nome_cartella = riga.get("cartella", "")
        timestamp_str = riga.get("timestamp_invio", "")
        stato = riga.get("stato", "").lower()

        if stato == "completato":
            continue

        # Se non ancora inviato
        if not timestamp_str:
            timestamp_invio = ora_attuale.isoformat()
            sheet.update_cell(idx + 2, list(riga.keys()).index("timestamp_invio") + 1, timestamp_invio)
            invia_messaggio(chat_id, f"*📁 Nuovo preventivo disponibile:*\n{nome_cartella}")
            solleciti[chat_id] = [ora_attuale, 0]
            continue

        # Se già inviato, gestisci solleciti
        ts_inizio = datetime.fromisoformat(timestamp_str)
        tempo_trascorso = (ora_attuale - ts_inizio).total_seconds()

        if tempo_trascorso > FINE_SOLLECITI:
            idx_col_stato = list(riga.keys()).index("stato") + 1
            sheet.update_cell(idx + 2, idx_col_stato, "scaduto")
            invia_messaggio(chat_id, "❌ Tempo scaduto. Il lavoro verrà assegnato ad altri partner.")
            continue

        if chat_id in solleciti:
            ultimo, n = solleciti[chat_id]
            if (ora_attuale - ultimo).total_seconds() >= SOLLECITO_INTERVALLO:
                invia_messaggio(chat_id, f"*⏰ Sollecito #{n + 1}* per confermare il preventivo: {nome_cartella}")
                solleciti[chat_id] = [ora_attuale, n + 1]
        else:
            solleciti[chat_id] = [ts_inizio, 0]

# === LISTENER RISPOSTE ===
def listener():
    updates = bot.get_updates(offset=-1, timeout=1)
    righe = sheet.get_all_records()

    for update in updates:
        if not update.message:
            continue

        chat_id = update.message.chat_id
        testo = update.message.text.lower()
        if testo in ["ok", "confermo", "va bene", "accetto"]:
            for i, riga in enumerate(righe):
                if int(riga.get("chat_id", 0)) == chat_id and riga.get("stato", "").lower() != "completato":
                    idx_col_stato = list(riga.keys()).index("stato") + 1
                    sheet.update_cell(i + 2, idx_col_stato, "completato")
                    invia_messaggio(chat_id, "✅ Preventivo confermato! Grazie.")
                    break

# === LOOP ===
print("✅ BOT avviato e in ascolto di nuovi preventivi...")

while True:
    try:
        ciclo()
        listener()
    except Exception as e:
        print(f"❌ Errore nel ciclo principale:\n{traceback.format_exc()}")
    time.sleep(60)
