import os
import time
from telegram import Bot
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURAZIONE ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # opzionale
GOOGLE_CREDENTIALS = eval(os.getenv("GOOGLE_CREDENTIALS"))

bot = Bot(token=BOT_TOKEN)

# === AUTH GOOGLE DRIVE ===
SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

MAIN_FOLDER_NAME = "PreventiviTelegram"
gestiti = set()

# === FUNZIONI GOOGLE DRIVE ===
def trova_cartella_principale():
    results = drive_service.files().list(
        q=f"name='{MAIN_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])
    return files[0]['id'] if files else None

def trova_sottocartelle(folder_id):
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()
    return results.get('files', [])

# === INVIA MESSAGGIO CON LINK CARTELLA ===
def crea_link_pubblico_e_invia(folder_id, folder_name, chat_id):
    # Rende la cartella pubblica in sola lettura
    drive_service.permissions().create(
        fileId=folder_id,
        body={"role": "reader", "type": "anyone"},
        fields="id"
    ).execute()

    # Crea link e invia
    folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
    testo = f"📩 *Nuovo preventivo da confermare:*\n[{folder_name}]({folder_link})"

    bot.send_message(chat_id=chat_id, text=testo, parse_mode="Markdown")
    print(f"Inviato link per {folder_name} al gruppo {chat_id}")

# === LOOP PRINCIPALE ===
def esegui():
    folder_id = trova_cartella_principale()
    if not folder_id:
        print("❌ Cartella PreventiviTelegram non trovata.")
        return

    gruppi = trova_sottocartelle(folder_id)
    for gruppo in gruppi:
        if not gruppo['name'].startswith("gruppo_"):
            continue

        chat_id = int(gruppo['name'].replace("gruppo_", ""))
        sottocartelle = trova_sottocartelle(gruppo['id'])

        for sotto in sottocartelle:
            unique_key = f"{chat_id}-{sotto['id']}"
            if unique_key not in gestiti:
                crea_link_pubblico_e_invia(sotto['id'], sotto['name'], chat_id)
                gestiti.add(unique_key)

# === AVVIO ===
if __name__ == "__main__":
    while True:
        try:
            esegui()
        except Exception as e:
            print(f"Errore: {e}")
        time.sleep(60)
