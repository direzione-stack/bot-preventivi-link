import time
from bot_link_preventivi_drive import check_nuovi_preventivi, invia_solleciti

INTERVALLO_CONTROLLI = 300    # ogni 5 minuti
INTERVALLO_SOLLECITI = 3600   # ogni 1 ora

ultimo_controllo = 0
ultimo_sollecito = 0

print("✅ BOT preventivi avviato e in esecuzione...")

while True:
    ora = time.time()

    # Controlla nuovi preventivi
    if ora - ultimo_controllo >= INTERVALLO_CONTROLLI:
        print("🔎 Controllo nuovi preventivi...")
        check_nuovi_preventivi()
        ultimo_controllo = ora
        print("✅ Controllo completato.")

    # Invia solleciti
    if ora - ultimo_sollecito >= INTERVALLO_SOLLECITI:
        print("📢 Invio solleciti in corso...")
        invia_solleciti()
        ultimo_sollecito = ora
        print("✅ Solleciti completati.")

    time.sleep(10)  # breve attesa
