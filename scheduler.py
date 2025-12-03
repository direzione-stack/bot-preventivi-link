import os
import time
import json
import logging
import pickle
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from telegram import Bot, ParseMode

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")  # ID cartella PreventiviTelegram
GOOGLE_CREDS_JSON = json.loads(os.getenv("GOOGLE_CREDENTIALS"))

# === INIZIALIZZA ===
bot = Bot(token=BOT_TOKEN)
logging.basicConfig(level=logging.INFO)

# === AUTENTICAZIONE GOOGLE ===
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
drive = build("drive", "v3", credentials=creds)

# === COSTANTI ===
SOLLECITO_INTERVALLO = 5 * 60 * 60       # 5 ore
SCADENZA_PREVENTIVO = 48 * 60 * 60       # 48 ore

CACHE_FILE = "cache.json"

# === CARICA CACHE ===
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        cache = json.load(f)
else:
    cache = {}


def salva_cache():
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def lista_cartelle_padre(folder_id):
    query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive.files().list(q=query, fields="files(id, name)").execute()
    return results.get("files", [])


def lista_file_cartella(folder_id):
    query = f"'{folder_id}' in parents and trashed = false"
    results = drive.files().list(q=query, fields="files(id, name, webViewLink)").execute()
    return results.get("files", [])


def invia_messaggio(chat_id, testo):
    try:
        bot.send_message(chat_id=chat_id, text=testo, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Errore invio a {chat_id}: {e}")


# === MAPPING cartelle => ID gruppi ===
GRUPPI = {
    "gruppo_-5026311462": -5026311462,
    "gruppo_-3359753434": -3359753434,
    "gruppo_-3418284764": -3418284764,
    "gruppo_-5014038776": -5014038776
}

while True:
    logging.info("\U0001F4C2 Controllo nuovi preventivi...")
    cartelle_gruppi = lista_cartelle_padre(FOLDER_ID)
    now = time.time()

    for gruppo in cartelle_gruppi:
        nome_cartella = gruppo['name']
        gruppo_id = GRUPPI.get(nome_cartella)
        if not gruppo_id:
            continue  # cartella non mappata

        sottocartelle = lista_cartelle_padre(gruppo['id'])

        for preventivo in sottocartelle:
            p_id = preventivo['id']
            p_nome = preventivo['name']

            if p_id not in cache:
                # Nuovo preventivo: invia messaggio con i file
                file_list = lista_file_cartella(p_id)
                testo = f"<b>✉️ Nuovo preventivo da confermare:</b>\n<b>{p_nome}</b>"
                for f in file_list:
                    testo += f"\n- <a href='{f['webViewLink']}'>{f['name']}</a>"

                invia_messaggio(gruppo_id, testo)
                cache[p_id] = {
                    "inviato": now,
                    "solleciti": 0,
                    "gruppo_id": gruppo_id
                }
                salva_cache()

            else:
                tempo_passato = now - cache[p_id]['inviato']
                if tempo_passato > SCADENZA_PREVENTIVO:
                    invia_messaggio(gruppo_id, "❌ Ci dispiace, il lavoro sarà dato ad un altro nostro partner.")
                    del cache[p_id]
                    salva_cache()
                elif tempo_passato > (cache[p_id]['solleciti'] + 1) * SOLLECITO_INTERVALLO:
                    n = cache[p_id]['solleciti'] + 1
                    invia_messaggio(gruppo_id, f"\u26a0\ufe0f Sollecito #{n}: per confermare il preventivo <b>{p_nome}</b> rispondi qui nel gruppo.")
                    cache[p_id]['solleciti'] = n
                    salva_cache()

    time.sleep(60)  # attesa 1 minuto
