import os
import time
import datetime
import telegram
from google.oauth2 import service_account
import gspread

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE / SHEETS ===
creds_dict = eval(os.getenv("GOOGLE_CREDENTIALS"))
creds = service_account.Credentials.from_service_account_info(creds_dict)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)
sheet = sh.sheet1

# === COSTANTI ===
SOLLECITO_INTERVALLO = 5 * 60 * 60  # ogni 5 ore in secondi
FINE_SOLLECITI = 48 * 60 * 60       # durata massima 48 ore in secondi

# === TRACKING STATO ===
solleciti = {}

# === FUNZIONE INVIO MESSAGGIO ===
def invia_messaggio(chat_id, testo):
    try:
        bot.send_message(chat_id=chat_id, text=testo)
    except Exception as e:
        print(f"Errore invio messaggio: {e}")

# === MAIN LOOP ===
print("Bot avviato...")
while True:
    try:
        righe = sheet.get_all_records()
        ora_attuale = datetime.datetime.utcnow()

        for riga in righe:
            chat_id = int(riga['chat_id'])
            nome_cartella = riga['cartella']
            timestamp_invio = riga.get('timestamp_invio')
            stato = riga.get('stato', '').lower()

            # Salta se già completato
            if stato == 'completato':
                continue

            # Gestione timestamp
            if not timestamp_invio:
                timestamp_invio = ora_attuale.isoformat()
                idx = righe.index(riga) + 2
                sheet.update_cell(idx, list(riga.keys()).index('timestamp_invio') + 1, timestamp_invio)
                invia_messaggio(chat_id, f"Nuovo preventivo da confermare: {nome_cartella}")
                solleciti[chat_id] = [ora_attuale, 0]  # salva primo invio
                continue

            # Gestione solleciti
            ts_inizio = datetime.datetime.fromisoformat(timestamp_invio)
            tempo_trascorso = (ora_attuale - ts_inizio).total_seconds()

            if tempo_trascorso > FINE_SOLLECITI:
                invia_messaggio(chat_id, "⛔ Ci dispiace, il lavoro sarà dato ad un altro nostro partner.")
                idx = righe.index(riga) + 2
                sheet.update_cell(idx, list(riga.keys()).index('stato') + 1, 'scaduto')
                continue

            if chat_id in solleciti:
                ultimo_sollecito, numero_solleciti = solleciti[chat_id]
                if (ora_attuale - ultimo_sollecito).total_seconds() >= SOLLECITO_INTERVALLO:
                    numero_solleciti += 1
                    invia_messaggio(chat_id, f"🔁 Sollecito #{numero_solleciti} per confermare il preventivo: {nome_cartella}")
                    solleciti[chat_id] = [ora_attuale, numero_solleciti]
            else:
                solleciti[chat_id] = [ts_inizio, 0]

    except Exception as e:
        print(f"Errore nel ciclo principale: {e}")

    time.sleep(60)  # attesa 1 minuto
