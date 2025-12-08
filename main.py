import os
import time
import json
import telegram
import traceback
from html import escape
from threading import Lock

from googleapiclient.discovery import build
from google.oauth2 import service_account

from telegram.ext import Updater, MessageHandler, Filters

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN non impostato nelle variabili d'ambiente.")

FOLDER_NAME = "PreventiviTelegram"
CONFIRMATION_GROUP_ID = -5071236492

CHECK_INTERVAL = 60               # ogni 60 secondi
SOLLECITO_INTERVAL = 4 * 3600     # ogni 4 ore
SOLLECITO_MAX = 12                # max 12 solleciti (48 ore)

CREDENTIALS_FILE = "credentials.json"
CACHE_FILE = "bot_cache.json"     # cache persistente (evita reinvii dopo restart)

# === BOT ===
bot = telegram.Bot(token=BOT_TOKEN)

# === GOOGLE DRIVE ===
if not os.path.exists(CREDENTIALS_FILE):
    raise RuntimeError(f"❌ File credenziali mancante: {CREDENTIALS_FILE}")

SCOPES = ["https://www.googleapis.com/auth/drive"]
creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
drive = build("drive", "v3", credentials=creds)

# === CACHE (thread-safe + persistente) ===
# key = (gruppo_id:int, preventivo_folder_id:str)
cache_lock = Lock()
sent_cache = set()
reminder_cache = {}     # key -> {"t0": float, "count": int, "link": str, "nome": str}
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

    with cache_lock:
        sent_cache.clear()
        reminder_cache.clear()
        confirmed_cache.clear()

        for entry in data.get("sent", []):
            if isinstance(entry, list) and len(entry) == 2:
                try:
                    sent_cache.add((int(entry[0]), str(entry[1])))
                except Exception:
                    pass

        for entry in data.get("confirmed", []):
            if isinstance(entry, list) and len(entry) == 2:
                try:
                    confirmed_cache.add((int(entry[0]), str(entry[1])))
                except Exception:
                    pass

        for r in data.get("reminders", []):
            try:
                gid = int(r["gruppo_id"])
                fid = str(r["folder_id"])
                reminder_cache[(gid, fid)] = {
                    "t0": float(r["t0"]),
                    "count": int(r["count"]),
                    "link": str(r.get("link", "")),
                    "nome": str(r.get("nome", "")),
                }
            except Exception:
                pass

    print(f"📦 Cache caricata: sent={len(sent_cache)}, pending={len(reminder_cache)}, confirmed={len(confirmed_cache)}")


def save_cache():
    # snapshot veloce (niente I/O sotto lock)
    with cache_lock:
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
    """Lista cartelle con paginazione + supporto Shared Drives."""
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


def get_subfolders(parent_id):
    try:
        query = (
            f"'{parent_id}' in parents and "
            "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        return _drive_list_folders(query)
    except Exception as e:
        print(f"❌ Errore recupero sottocartelle: {e}")
        return []


def get_folder_id_by_name(name):
    try:
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive.files().list(
            q=query,
            fields="files(id, name)",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        folders = results.get("files", [])
        return folders[0]["id"] if folders else None
    except Exception as e:
        print(f"❌ Errore ricerca cartella principale: {e}")
        return None


def generate_share_link(folder_id):
    """Rende la cartella 'chiunque con link può vedere' (se possibile) e ritorna il link."""
    permission = {"type": "anyone", "role": "reader", "allowFileDiscovery": False}
    try:
        drive.permissions().create(
            fileId=folder_id,
            body=permission,
            supportsAllDrives=True,
            fields="id",
        ).execute()
    except Exception:
        # può fallire per policy/permessi già presenti: ok, il link resta valido per chi ha accesso
        pass

    return f"https://drive.google.com/drive/folders/{folder_id}"


def extract_group_id(folder_name: str):
    # formato atteso: gruppo_-123456_g
    cleaned = folder_name.replace("gruppo_", "").replace("_g", "")
    try:
        return int(cleaned)
    except ValueError:
        # fallback: prova a trovare un intero dentro la stringa
        import re
        m = re.search(r"-?\d+", folder_name)
        return int(m.group(0)) if m else None


def invia_preventivo(gruppo_id, nome_folder_preventivo, link, key):
    messaggio = f"✉️ <b>Nuovo preventivo disponibile:</b>\n<b>{escape(nome_folder_preventivo)}</b>\n{escape(link)}"
    try:
        bot.send_message(chat_id=gruppo_id, text=messaggio, parse_mode="HTML")
        bot.send_message(
            chat_id=CONFIRMATION_GROUP_ID,
            text=f"✅ Inviato al gruppo <code>{gruppo_id}</code>: {escape(nome_folder_preventivo)}",
            parse_mode="HTML",
        )

        with cache_lock:
            sent_cache.add(key)
            reminder_cache[key] = {"t0": time.time(), "count": 0, "link": link, "nome": nome_folder_preventivo}

        save_cache()
        print(f"✅ Inviato: {nome_folder_preventivo} al gruppo {gruppo_id}")

    except Exception as e:
        print(f"❌ Errore invio a gruppo {gruppo_id}: {e}")


def scan_and_send():
    root_id = get_folder_id_by_name(FOLDER_NAME)
    if not root_id:
        print("❌ Cartella PreventiviTelegram non trovata.")
        return

    gruppi = get_subfolders(root_id)

    for gruppo in gruppi:
        gruppo_name = gruppo.get("name", "")
        gruppo_id = extract_group_id(gruppo_name)

        if gruppo_id is None:
            print(f"❌ ID gruppo non valido nella cartella: {gruppo_name}")
            continue

        gruppo_folder_id = gruppo["id"]
        preventivi = get_subfolders(gruppo_folder_id)

        for p in preventivi:
            key = (gruppo_id, p["id"])

            with cache_lock:
                if key in sent_cache:
                    continue

            link = generate_share_link(p["id"])
            invia_preventivo(gruppo_id, p["name"], link, key)


def invia_sollecito():
    ora = time.time()

    with cache_lock:
        items = list(reminder_cache.items())

    changed = False

    for key, info in items:
        gruppo_id, folder_id = key

        # ricarico stato attuale (potrebbe essere cambiato per conferma)
        with cache_lock:
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
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Errore invio messaggio finale a {gruppo_id}: {e}")

            with cache_lock:
                reminder_cache.pop(key, None)
            changed = True
            continue

        if ora - t0 >= (count + 1) * SOLLECITO_INTERVAL:
            try:
                bot.send_message(
                    chat_id=gruppo_id,
                    text=f"🔔 <b>Gentile collaboratore, ti ricordiamo il preventivo ancora da confermare:</b>\n{escape(link)}",
                    parse_mode="HTML",
                )
                with cache_lock:
                    if key in reminder_cache:  # può essere stato confermato mentre inviavi
                        reminder_cache[key]["count"] += 1
                changed = True
                print(f"🔁 Sollecito inviato a gruppo {gruppo_id}")
            except Exception as e:
                print(f"Errore sollecito a gruppo {gruppo_id}: {e}")

    if changed:
        save_cache()


def conferma(update, context):
    msg = update.effective_message
    testo = (msg.text or "").strip().lower()

    if testo not in {"ok", "confermo", "va bene", "accetto"}:
        return

    gruppo_id = msg.chat.id
    user = msg.from_user.full_name if msg.from_user else "Utente"

    with cache_lock:
        pending_keys = [k for k in reminder_cache.keys() if k[0] == gruppo_id]
        if not pending_keys:
            return
        nomi = ", ".join(escape(reminder_cache[k]["nome"]) for k in pending_keys)

        for k in pending_keys:
            confirmed_cache.add(k)
            reminder_cache.pop(k, None)

    save_cache()

    try:
        bot.send_message(
            chat_id=CONFIRMATION_GROUP_ID,
            text=f"✅ Conferma ricevuta da <b>{escape(user)}</b> nel gruppo <code>{gruppo_id}</code> per: {nomi}",
            parse_mode="HTML",
        )
        print(f"✅ Conferma registrata per {gruppo_id} da {user}")
    except Exception as e:
        print(f"Errore invio conferma: {e}")


def main():
    load_cache()

    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), conferma))
    updater.start_polling()

    print("🚀 BOT preventivi avviato...")

    try:
        while True:
            try:
                scan_and_send()
                invia_sollecito()
            except Exception:
                print(f"❌ Errore ciclo:\n{traceback.format_exc()}")
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print("🛑 Stop richiesto da tastiera.")
    finally:
        try:
            updater.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
