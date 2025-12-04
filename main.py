import os
import time
import json
import telegram
import gspread
import traceback
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

if isinstance(GOOGLE_CREDS_JSON, str):
    GOOGLE_CREDS_JSON = json.loads(GOOGLE_CREDS_JSON)

# === TELEGRAM ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE + SHEETS ===
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON)

gc = gspread.authorize(creds)

drive_service = creds.with_scopes(['https://www.googleapis.com/auth/drive'])
drive = build('drive', 'v3', credentials=drive_service)

# Foglio Google Sheets per report
SHEET_ID = os.getenv("SPREADSHEET_ID")
sheet = gc.open_by_key(SHEET_ID).sheet1

# === CONFIG ===
FOLDER_NAME = "PreventiviTelegram"
CHECK_INTERVAL = 60       # ogni 60 secondi
SOLLECITO_INTERVALLO = 4 * 60 * 60      # 4 ore
SCADENZA = 48 * 60 * 60                 # 48 ore

# tracking preventivi
cache = {}  # { "idpreventivo": { "timestamp": ..., "chat_id": ..., "nome": ... } }

# PAROLE CHIAVE DI CONFERMA
PAROLE_CONFERMA = ["ok", "confermo", "va bene", "accetto"]


# ===== FUNZIONI GOOGLE DRIVE =====

def get_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        print(f"❌ Errore recupero sottocartelle: {e}")
        return []


def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get('files', [])
        return folders[0]['id'] if folders else None
    except Exception as e:
        print(f"❌ Errore ricerca cartella principale: {e}")
        return None


def genera_link(folder_id):
    try:
        permission = {'type': 'anyone', 'role': 'reader'}
        drive.permissions().create(fileId=folder_id, body=permission).execute()
    except:
        pass
    return f"https://drive.google.com/drive/folders/{folder_id}"


# ===== INVIO PREVENTIVI =====

def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("❌ Cartella PreventiviTelegram non trovata.")
        return

    gruppi = get_subfolders(root_id)

    for gruppo in gruppi:
        gruppo_id = gruppo['name'].replace("gruppo_", "")
        gruppo_folder = gruppo['id']

        preventivi = get_subfolders(gruppo_folder)

        for p in preventivi:
            key = f"{gruppo_id}_{p['id']}"

            if key in cache:  # già inviato
                continue

            link = genera_link(p['id'])
            messaggio = f"📄 *Nuovo preventivo disponibile:*\n{p['name']}\n🔗 {link}"

            try:
                bot.send_message(chat_id=int(gruppo_id), text=messaggio, parse_mode=telegram.ParseMode.MARKDOWN)
                cache[key] = {
                    "timestamp": time.time(),
                    "chat_id": gruppo_id,
                    "nome": p["name"]
                }
                print(f"✅ Inviato {p['name']} al gruppo {gruppo_id}")
            except Exception as e:
                print(f"❌ Errore invio {gruppo_id}: {e}")


# ===== GESTIONE SOLLECITI =====

def gestisci_solleciti():
    now = time.time()

    for key, info in list(cache.items()):
        tempo_passato = now - info["timestamp"]

        if tempo_passato >= SCADENZA:
            try:
                bot.send_message(
                    chat_id=int(info["chat_id"]),
                    text=f"⛔ Il preventivo *{info['nome']}* è scaduto. Verrà assegnato ad un altro partner."
                )
                print(f"⚠️ Scaduto: {info['nome']}")
                del cache[key]
            except:
                pass
            continue

        if tempo_passato >= SOLLECITO_INTERVALLO:
            try:
                bot.send_message(
                    chat_id=int(info["chat_id"]),
                    text=f"🔔 *Sollecito:* Manca conferma per il preventivo *{info['nome']}*"
                )
                cache[key]["timestamp"] = now
                print(f"🔔 Sollecito inviato: {info['nome']}")
            except:
                pass


# ===== GESTIONE MESSAGGI DI CONFERMA =====

def ascolta_conferme(update, context):
    try:
        chat_id = update.message.chat_id
        testo = update.message.text.lower()

        if not any(parola in testo for parola in PAROLE_CONFERMA):
            return

        # trova preventivo collegato a questo gruppo
        for key, info in list(cache.items()):
            if str(chat_id) == str(info["chat_id"]):
                nome = info["nome"]

                # conferma su Telegram
                bot.send_message(chat_id, f"✅ Preventivo *{nome}* confermato!")

                # scrivi su Google Sheets
                try:
                    sheet.append_row([chat_id, nome, "confermato", time.strftime("%d/%m/%Y %H:%M:%S")])
                except Exception as e:
                    print("❌ Errore scrittura Google Sheet:", e)

                # rimuovi dalla lista solleciti
                del cache[key]
                print(f"🟢 Confermato: {nome}")
                break

    except Exception as e:
        print("❌ Errore gestione conferma:", e)


# ===== AVVIO BOT =====

from telegram.ext import Updater, MessageHandler, Filters

def main():
    print("🤖 BOT AVVIATO – monitoraggio preventivi attivo...")

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # ascolta conferme
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), ascolta_conferme))

    updater.start_polling()

    while True:
        try:
            scan_and_send()
            gestisci_solleciti()
        except Exception as e:
            print("❌ Errore generale ciclo:", e)
            print(traceback.format_exc())
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
