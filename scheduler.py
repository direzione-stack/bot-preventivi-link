import time
from bot_link_preventivi_drive import check_nuovi_preventivi, invia_solleciti

# === CONFIG ===

INTERVALLO_CONTROLLI = 5 * 60         # ogni 5 minuti = 300 secondi
INTERVALLO_SOLLECITI = 5 * 60 * 60    # ogni 5 ore = 18000 secondi

ultimo_controllo = 0
ultimo_sollecito = 0

print("✅ BOT preventivi avviato e in esecuzione...")

# === MAIN LOOP ===

while True:
    ora = time.time()

    # Controllo nuovi preventivi
    if ora - ultimo_controllo >= INTERVALLO_CONTROLLI:
        print("🔎 Controllo nuovi preventivi...")
        try:
            check_nuovi_preventivi()
        except Exception as e:
            print(f"❌ Errore nel controllo preventivi: {e}")
        ultimo_controllo = ora

    # Invio solleciti ogni 5 ore
    if ora - ultimo_sollecito >= INTERVALLO_SOLLECITI:
        print("🔔 Invio solleciti...")
        try:
            invia_solleciti()
        except Exception as e:
            print(f"❌ Errore nell'invio solleciti: {e}")
        ultimo_sollecito = ora

    time.sleep(10)  # Attesa per non sovraccaricare il sistema
