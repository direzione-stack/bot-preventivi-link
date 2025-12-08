import os
import time
import json
import base64
import re
import telegram
import traceback
from html import escape
from threading import Lock

from googleapiclient.discovery import build
from google.oauth2 import service_account

from telegram.ext import Updater, MessageHandler, Filters

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("❌ Manca BOT_TOKEN nelle variabili d'ambiente.")

FOLDER_NAME = os.getenv("FOLDER_NAME", "PreventiviTelegram")
CONFIRMATION_GROUP_ID = int(os.getenv("CONFIRMATION_GROUP_ID", "-5071236492"))

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))                 # secondi
SOLLECITO_INTERVAL = int(os.getenv("SOLLECITO_INTERVAL", str(4 * 3600)))  # 4 ore
SOLLECITO_MAX = int(os.getenv("SOLLECITO_MAX", "12"))                  # 48 ore

CACHE_FILE = os.getenv("CACHE_FILE", "bot_cache.json")

bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE CREDENTIALS (da Railway Variables) ===
SCOPES = ["https://www.googleapis.com/auth/drive"]

creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64", "").strip()

if creds_json:
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
elif creds_b64:
    raw = base64.b64decode(creds_b64).decode("utf-8")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
else:
    # fallback SOLO per locale se hai il file (sconsigliato su Railway)
    CREDENTIALS_FILE = "credentials.json"
    if not os.path.exists(CREDENTIALS_FILE):
        raise RuntimeError(
            "❌ Manca GOOGLE_CREDENTIALS_JSON (o GOOGLE_CREDENTIALS_B64) su Railway "
            "e non trovo credentials.json in locale."
        )
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)

drive = build("drive", "v3", credentials=creds)

# === CACHE (thread-safe + persistente) ===
# key = (gruppo_id:int, preventivo_folder_id:str)
lock = Lock()
sent_cache = set()
reminder_cache = {}   # key -> {"t0": float, "count": int, "link": str, "nome": str}
confirmed_cache = set()


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️ Cache non leggibile ({CACHE_FILE}), la ignoro: {e}")
        return

    with lock:
        sent_cache.clear()
        reminder_cache.clear()
        confirmed_cache.clear()

        for gid, fid in data.get("sent", []):
            try:
                sent_cache.add((int(gid), str(fid)))
            except Exception:
                pass

        for gid, fid in data.get("confirmed", []):
            try:
                confirmed_cache.add((int(gid), str(fid)))
            except Exception:
                pass

        for r in data.get("reminders", []):
            try:
                gid = int(r["gruppo_id"])
                fid = str(r["folder_id"])
                reminder_cache[(gid, fid)] = {
                    "t0": float(r.get("t0", time.time())),
                    "count": int(r.get("count", 0)),
                    "link": str(r.get("link", "")),
                    "nome": str(r.get("nome", "")),
                }
            except Exception:
                pass

    print(f"📦 Cache: sent={len(sent_cache)} pending={len(reminder_cache)} confirmed={len(confirmed_cache)}")


def save_cache():
    with lock:
        payload = {
            "sent": [[gid, fid] for (gid, fid) in sent_cache],
            "confirmed": [[gid, fid] for (gid, fid) in confirmed_cache],
            "reminders": [
                {
                    "gruppo_id": gid,
                    "folder_id": fid,
                    "t0": info.get("t0", 0),
                    "count": info.get("count", 0),
                    "link": info.get("link", ""),
                    "nome": info.get("nome", ""),
                }
                for (gid, fid), info in reminder_cache.items()
            ],
        }

    try:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, CACHE_FILE)
    except Exception as e:
        print(f"⚠️ Impossibile salvare cache: {e}")


def _drive_list_folders(query: str):
    files = []
    page_token = None
    while True:
        resp = drive.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageSize=1000,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def get_folder_id_by_name(name: str):
    query = (
        f"name = '{name}' and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    results = drive.files().list(
        q=query,
        fields="files(id, name)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    folders = results.get("files", [])
    return folders[0]["id"] if folders else None


def get_subfolders(parent_id: str):
    query = (
        f"'{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    return _drive_list_folders(query)


def generate_share_link(folder_id: str) -> str:
    permission = {"type": "anyone", "role": "reader", "allowFileDiscovery": False}
    try:
        drive.permissions().create(
            fileId=folder_id,
            body=permission,
            supportsAllDrives=True,
            fields="id",
        ).execute()
    except Exception:
        # se fallisce per policy/perms già presenti, ok
        pass
    return f"https://drive.google.com/drive/folders/{folder_id}"


def extract_group_id(folder_name: str):
    cleaned = folder_name.replace("gruppo_", "").replace("_g", "")
    try:
        return int(cleaned)
    except Exception:
        m = re.search(r"-?\d+", folder_name)
        return int(m.group(0)) if m else None


def invia_preventivo(gruppo_id: int, nome_preventivo: str, link: str, key):
    msg = f"✉️ <b>Nuovo preventivo disponibile:</b>\n<b>{escape(nome_preventivo)}</b>\n{escape(link)}"
    try:
        bot.send_message(chat_id=gruppo_id, text=msg, parse_mode="HTML")
        bot.send_message(
            chat_id=CONFIRMATION_GROUP_ID,
            text=f"✅ Inviato al gruppo <code>{gruppo_id}</code>: {escape(nome_preventivo)}",
            parse_mode="HTML",
        )

        with lock:
            sent_cache.add(key)
            reminder_cache[key] = {"t0": time.time(), "count": 0, "link": link, "nome": nome_preventivo}

        save_cache()
        print(f"✅ Inviato: {nome_preventivo} → gruppo {gruppo_id}")
    except Exception as e:
        print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")


def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print(f"❌ Cartella '{FOLDER_NAME}' non trovata su Drive (o non condivisa col service account).")
        return

    gruppi = get_subfolders(root_id)
    for gruppo in gruppi:
        gruppo_name = gruppo.get("name", "")
        gruppo_id = extract_group_id(gruppo_name)
        if gruppo_id is None:
            print(f"❌ Cartella gruppo non valida: {gruppo_name}")
            continue

        preventivi = get_subfolders(gruppo["id"])
        for p in preventivi:
            key = (gruppo_id, p["id"])
            with lock:
                if key in sent_cache:
                    continue

            link = generate_share_link(p["id"])
            invia_preventivo(gruppo_id, p.get("name", "Preventivo"), link, key)


def invia_sollecito():
    now = time.time()

    with lock:
        items = list(reminder_cache.items())

    changed = False

    for key, _ in items:
        gruppo_id, _folder_id = key

        with lock:
            if key not in reminder_cache:
                continue
            if key in confirmed_cache:
                reminder_cache.pop(key, None)
                changed = True
                continue

            info = reminder_cache[key]
            t0 = info["t0"]
            count = info["count"]
            link = info["link"]

        if count >= SOLLECITO_MAX:
            try:
                bot.send_message(
                    chat_id=gruppo_id,
                    text="❌ Ci dispiace che tu non abbia risposto. Il lavoro verrà assegnato a un'altra azienda."
                )
                bot.send_message(
                    chat_id=CONFIRMATION_GROUP_ID,
                    text=f"⛔ Nessuna risposta dal gruppo <code>{gruppo_id}</code>. Lavoro riassegnato.",
                    parse_mode="HTML",
                )
            except Exception as e:
                print(f"Errore messaggio finale a {gruppo_id}: {e}")

            with lock:
                reminder_cache.pop(key, None)
            changed = True
            continue

        if now - t0 >= (count + 1) * SOLLECITO_INTERVAL:
            try:
                bot.send_message(
                    chat_id=gruppo_id,
                    text=f"🔔 <b>Promemoria: preventivo da confermare</b>\n{escape(link)}",
                    parse_mode="HTML",
                )
                with lock:
                    if key in reminder_cache:
                        reminder_cache[key]["count"] += 1
                changed = True
                print(f"🔁 Sollecito → gruppo {gruppo_id}")
            except Exception as e:
                print(f"Errore sollecito a {gruppo_id}: {e}")

    if changed:
        save_cache()


def conferma(update, context):
    msg = update.effective_message
    testo = (msg.text or "").strip().lower()

    if testo not in {"ok", "confermo", "va bene", "accetto"}:
        return

    gruppo_id = msg.chat.id
    user = msg.from_user.full_name if msg.from_user else "Utente"

    with lock:
        pending = [k for k in reminder_cache.keys() if k[0] == gruppo_id]
        if not pending:
            return

        nomi = ", ".join(escape(reminder_cache[k].get("nome", "")) for k in pending)

        for k in pending:
            confirmed_cache.add(k)
            reminder_cache.pop(k, None)

    save_cache()

    try:
        bot.send_message(
            chat_id=CONFIRMATION_GROUP_ID,
            text=f"✅ Conferma ricevuta da <b>{escape(user)}</b> nel gruppo <code>{gruppo_id}</code> per: {nomi}",
            parse_mode="HTML",
        )
        print(f"✅ Conferma → gruppo {gruppo_id} da {user}")
    except Exception as e:
        print(f"Errore invio conferma: {e}")


def tick(context):
    try:
        scan_and_send()
        invia_sollecito()
    except Exception:
        print(f"❌ Errore tick:\n{traceback.format_exc()}")


def main():
    load_cache()

    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), conferma))

    updater.job_queue.run_repeating(tick, interval=CHECK_INTERVAL, first=1)

    print("🚀 BOT preventivi avviato...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
