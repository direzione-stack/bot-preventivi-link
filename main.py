import os
import time
import json
import telegram
import gspread
import traceback
from google.oauth2 import service_account
from googleapiclient.discovery import build
from telegram.ext import Updater, MessageHandler, Filters

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")
SHEET_ID = os.getenv("SPREADSHEET_ID")  # ID del Google Sheet per loggare le conferme
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60  # ogni 60 secondi
SOLLECITO_INTERVALLO = 5 * 60 * 60  # ogni 5 ore
FINE_SOLLECITI = 48 * 60 * 60  # 48 ore

if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

bot = telegram.Bot(token=BOT_TOKEN)
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)
gc = gspread.authorize(creds)
drive_service = creds.with_scopes(['https://www.googleapis.com/auth/drive'])
drive = build('drive', 'v3', credentials=drive_service)
sheet = gc.open_by_key(SHEET_ID).sheet1

# === CACHE ===
cache = {}
solleciti = {}  # chat_id: [timestamp_invio, numero_solleciti]

# === FUNZIONI GOOGLE DRIVE ===
def get_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        print(f"Errore durante recupero sottocartelle: {e}")
        return []

def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get('files', [])
        return folders[0]['id'] if folders else None
    except Exception as e:
        print(f"Errore durante ricerca cartella principale: {e}")
        return None

def generate_share_link(folder_id):
    try:
        permission = {"type": "anyone", "role": "reader"}
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass  # Permesso potrebbe essere già esistente
    return f"https://drive.google.com/drive/folders/{folder_id}"

# === SCAN + INVIO ===
def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("❌ Cartella PreventiviTelegram non trovata.")
        return

    gruppi = get_subfolders(root_id)
    for gruppo in gruppi:
        gruppo_id = gruppo['name'].replace("gruppo_", "")
        gruppo_folder_id = gruppo['id']
        preventivi = get_subfolders(gruppo_folder_id)

        for p in preventivi:
            key = f"{gruppo_id}_{p['id']}"
            if key in cache:
                continue

            link = generate_share_link(p['id'])
            nome_file = p['name']
            messaggio = f"📁 <b>Nuovo preventivo disponibile:</b>\n{nome_file}\n{link}"
            try:
                bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.HTML)
                cache[key] = True
                ora_attuale = time.time()
                solleciti[gruppo_id] = [ora_attuale, 0]
                print(f"✅ Inviato: {nome_file} al gruppo {gruppo_id}")
            except Exception as e:
                print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")

# === GESTIONE SOLLECITI ===
def invia_solleciti():
    ora_attuale = time.time()
    for chat_id, (ts_invio, numero_solleciti) in list(solleciti.items()):
        tempo_trascorso = ora_attuale - ts_invio

        if tempo_trascorso > FINE_SOLLECITI:
            try:
                bot.send_message(chat_id=int(chat_id), text="🚫 Il preventivo non è stato confermato: sarà assegnato ad un altro partner.")
                del solleciti[chat_id]
            except:
                pass
            continue

        if tempo_trascorso >= SOLLECITO_INTERVALLO * (numero_solleciti + 1):
            try:
                numero_solleciti += 1
                bot.send_message(chat_id=int(chat_id), text=f"🔔 Sollecito #{numero_solleciti} per confermare il preventivo.")
                solleciti[chat_id][1] = numero_solleciti
            except Exception as e:
                print(f"❌ Errore invio sollecito: {e}")

# === GESTIONE CONFERME ===
def conferma(update, context):
    chat_id = str(update.message.chat_id)
    testo = update.message.text.lower()

    if any(x in testo for x in ["ok", "confermo", "va bene", "accetto"]):
        if chat_id in solleciti:
            try:
                bot.send_message(chat_id=int(chat_id), text="✅ Preventivo confermato. Grazie!")
                del solleciti[chat_id]

                # Scrivi su Google Sheet
                rows = sheet.get_all_records()
                for idx, r in enumerate(rows):
                    if str(r.get("chat_id")) == chat_id and r.get("stato") != "confermato":
                        sheet.update_cell(idx+2, 4, "confermato")
                        break
                print(f"✅ Conferma registrata per chat {chat_id}")
            except Exception as e:
                print(f"❌ Errore conferma: {e}")

# === AVVIO ===
if __name__ == '__main__':
    print("🤖 BOT avviato e in ascolto di nuovi preventivi...")
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), conferma))
    updater.start_polling()

    while True:
        try:
            scan_and_send()
            invia_solleciti()
        except Exception as e:
            print(f"❌ Errore nel ciclo principale:\n{traceback.format_exc()}")
        time.sleep(CHECK_INTERVAL)K_INTERVAL)
