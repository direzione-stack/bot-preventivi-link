import os
import time
import json
import base64
import re
import datetime as dt
import telegram
import traceback
from html import escape
from threading import Lock

from telegram.ext import Updater, MessageHandler, Filters, CommandHandler
from googleapiclient.discovery import build
from google.oauth2 import service_account

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

# offset orario (per i report/statistiche). 0 = UTC, 1 = UTC+1, ecc.
TZ_OFFSET_HOURS = int(os.getenv("TZ_OFFSET_HOURS", "0"))
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "20"))  # ora del report giornaliero (0-23, nel fuso TZ_OFFSET_HOURS)

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
            "❌ Manca GOOGLE_CREDENTIALS_JSON (o GOOGLE_CREDENTIALS_B64) e non trovo credentials.json in locale."
        )
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)

drive = build("drive", "v3", credentials=creds)

# === CACHE (thread-safe + persistente) ===
# key = (gruppo_id:int, preventivo_folder_id:str)
lock = Lock()
sent_cache = set()
reminder_cache = {}   # key -> {"t0": float, "count": int, "link": str, "nome": str}
confirmed_cache = set()
# stats_by_day[YYYY-MM-DD] = {"sent": int, "confirmed": int, "expired": int}
stats_by_day = {}


def _now_local():
    """Ritorna datetime 'locale' rispetto a TZ_OFFSET_HOURS (di default UTC)."""
    return dt.datetime.utcnow() + dt.timedelta(hours=TZ_OFFSET_HOURS)


def _day_key_for(d: dt.datetime = None) -> str:
    if d is None:
        d = _now_local()
    return d.strftime("%Y-%m-%d")


def _inc_stat(field: str, n: int = 1):
    """Incrementa una statistica del giorno corrente."""
    if n <= 0:
        return
    day = _day_key_for()
    with lock:
        day_stats = stats_by_day.setdefault(day, {"sent": 0, "confirmed": 0, "expired": 0})
        day_stats[field] = int(day_stats.get(field, 0)) + n


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
        stats_by_day.clear()

        for entry in data.get("sent", []):
            try:
                gid, fid = entry
                sent_cache.add((int(gid), str(fid)))
            except Exception:
                pass

        for entry in data.get("confirmed", []):
            try:
                gid, fid = entry
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

        raw_stats = data.get("stats_by_day", {})
        if isinstance(raw_stats, dict):
            for day, stats in raw_stats.items():
                try:
                    stats_by_day[str(day)] = {
                        "sent": int(stats.get("sent", 0)),
                        "confirmed": int(stats.get("confirmed", 0)),
                        "expired": int(stats.get("expired", 0)),
                    }
                except Exception:
                    pass

    print(
        f"📦 Cache: sent={len(sent_cache)} pending={len(reminder_cache)} "
        f"confirmed={len(confirmed_cache)} days_stats={len(stats_by_day)}"
    )


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
            "stats_by_day": stats_by_day,
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
        _inc_stat("sent", 1)
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

    for key, info in items:
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
            _inc_stat("expired", 1)
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
    # normalizza gli spazi: "ok   confermo" -> "ok confermo"
    testo = re.sub(r"\s+", " ", testo)

    # frasi base accettate (esattamente uguali)
    BASE = {"ok", "confermo", "va bene", "accetto"}
    # frasi più lunghe che vogliamo considerare conferma
    EXTRA = ["ok confermo", "ok, confermo", "ok va bene", "ok, va bene"]

    matched = False
    if testo in BASE:
        matched = True
    elif any(phrase in testo for phrase in EXTRA):
        matched = True

    if not matched:
        # non è un messaggio di conferma, ignora
        return

    gruppo_id = msg.chat.id
    user = msg.from_user.full_name if msg.from_user else "Utente"

    with lock:
        # tutti i preventivi ancora pendenti per questo gruppo
        pending = [k for k in reminder_cache.keys() if k[0] == gruppo_id]
        if not pending:
            # se arriva una conferma ma non abbiamo nulla in attesa, mandiamo un avviso nel gruppo di controllo
            try:
                context.bot.send_message(
                    chat_id=CONFIRMATION_GROUP_ID,
                    text=(
                        f"ℹ️ Messaggio di conferma rilevato da <b>{escape(user)}</b> "
                        f"nel gruppo <code>{gruppo_id}</code> ma non ci sono preventivi pendenti "
                        f"(forse già scaduti o già confermati)."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return

        nomi = ", ".join(escape(reminder_cache[k].get("nome", "")) for k in pending)

        for k in pending:
            confirmed_cache.add(k)
            reminder_cache.pop(k, None)

    _inc_stat("confirmed", len(pending))
    save_cache()

    try:
        context.bot.send_message(
            chat_id=CONFIRMATION_GROUP_ID,
            text=f"✅ Conferma ricevuta da <b>{escape(user)}</b> nel gruppo <code>{gruppo_id}</code> per: {nomi}",
            parse_mode="HTML",
        )
        print(f"✅ Conferma → gruppo {gruppo_id} da {user}")
    except Exception as e:
        print(f"Errore invio conferma: {e}")


# === COMANDI ADMIN ===

def cmd_stato(update, context):
    """Mostra lo stato del bot: pendenti e statistiche di oggi/ieri."""
    now = _now_local()
    today = _day_key_for(now)
    yesterday = _day_key_for(now - dt.timedelta(days=1))

    with lock:
        today_stats = stats_by_day.get(today, {"sent": 0, "confirmed": 0, "expired": 0})
        y_stats = stats_by_day.get(yesterday, {"sent": 0, "confirmed": 0, "expired": 0})
        pendenti = len(reminder_cache)

    text = (
        f"📊 <b>Stato bot preventivi</b>\n"
        f"Oggi ({today}):\n"
        f"• Inviati: <b>{today_stats['sent']}</b>\n"
        f"• Confermati: <b>{today_stats['confirmed']}</b>\n"
        f"• Scaduti (nessuna risposta): <b>{today_stats['expired']}</b>\n"
        f"• Attualmente in attesa: <b>{pendenti}</b>\n\n"
        f"Ieri ({yesterday}):\n"
        f"• Inviati: <b>{y_stats['sent']}</b>\n"
        f"• Confermati: <b>{y_stats['confirmed']}</b>\n"
        f"• Scaduti: <b>{y_stats['expired']}</b>\n"
    )

    update.effective_message.reply_text(text, parse_mode="HTML")


def cmd_stop_solleciti(update, context):
    """Ferma tutti i solleciti per il gruppo da cui viene lanciato il comando."""
    chat = update.effective_chat
    gruppo_id = chat.id
    user = update.effective_user.full_name if update.effective_user else "Utente"

    with lock:
        keys = [k for k in reminder_cache.keys() if k[0] == gruppo_id]
        for k in keys:
            reminder_cache.pop(k, None)
            confirmed_cache.add(k)

    if keys:
        save_cache()
        update.effective_message.reply_text(
            "⏹ Solleciti disattivati per i preventivi pendenti in questo gruppo."
        )
        try:
            bot.send_message(
                chat_id=CONFIRMATION_GROUP_ID,
                text=f"⏹ Solleciti disattivati per il gruppo <code>{gruppo_id}</code> da <b>{escape(user)}</b>",
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"Errore notifica stop_solleciti: {e}")
    else:
        update.effective_message.reply_text(
            "Non ci sono preventivi pendenti per questo gruppo."
        )


# === REPORT GIORNALIERO ===

def report_giornaliero(context):
    now = _now_local()
    today = _day_key_for(now)
    yesterday = _day_key_for(now - dt.timedelta(days=1))

    with lock:
        today_stats = stats_by_day.get(today, {"sent": 0, "confirmed": 0, "expired": 0})
        y_stats = stats_by_day.get(yesterday, {"sent": 0, "confirmed": 0, "expired": 0})
        pendenti = len(reminder_cache)

    text = (
        f"📈 <b>Report giornaliero preventivi</b>\n"
        f"Data (oggi): <b>{today}</b>\n\n"
        f"Oggi:\n"
        f"• Inviati: <b>{today_stats['sent']}</b>\n"
        f"• Confermati: <b>{today_stats['confirmed']}</b>\n"
        f"• Scaduti (nessuna risposta): <b>{today_stats['expired']}</b>\n"
        f"• Attualmente in attesa: <b>{pendenti}</b>\n\n"
        f"Ieri ({yesterday}):\n"
        f"• Inviati: <b>{y_stats['sent']}</b>\n"
        f"• Confermati: <b>{y_stats['confirmed']}</b>\n"
        f"• Scaduti: <b>{y_stats['expired']}</b>\n"
    )

    try:
        context.bot.send_message(chat_id=CONFIRMATION_GROUP_ID, text=text, parse_mode="HTML")
        print("📨 Report giornaliero inviato.")
    except Exception as e:
        print(f"Errore invio report giornaliero: {e}")


def tick(context):
    try:
        scan_and_send()
        invia_sollecito()
    except Exception:
        print(f"❌ Errore tick:\n{traceback.format_exc()}")


def main():
    load_cache()

    # assicurati che non ci siano webhook pendenti
    try:
        bot.delete_webhook()
    except Exception:
        pass

    updater = Updater(token=BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # conferme (solo messaggi di testo NON comandi)
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), conferma))

    # comandi admin
    dp.add_handler(CommandHandler("stato", cmd_stato))
    dp.add_handler(CommandHandler("stop_solleciti", cmd_stop_solleciti))

    # job periodico per scan + solleciti
    updater.job_queue.run_repeating(tick, interval=CHECK_INTERVAL, first=1)

    # job giornaliero per report (ora locale definita da TZ_OFFSET_HOURS + DAILY_REPORT_HOUR)
    report_hour_utc = (DAILY_REPORT_HOUR - TZ_OFFSET_HOURS) % 24
    report_time_utc = dt.time(hour=report_hour_utc, minute=0)
    updater.job_queue.run_daily(report_giornaliero, time=report_time_utc)

    print("🚀 BOT preventivi avviato...")
    updater.start_polling(drop_pending_updates=True)
    updater.idle()


if __name__ == "__main__":
    main()
