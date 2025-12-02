import time
from bot_link_preventivi_drive import check_nuovi_preventivi, invia_solleciti

# Intervalli in secondi
INTERVALLO_CONTROLLI = 300           # Ogni 5 minuti
INTERVALLO_SOLLECITI = 3600          # Ogni 1 ora

# Timestamp iniziali
ultimo_controllo = 0
ultimo_sollecito = 0

print("✅ BOT preventivi avviato e in esecuzione...")

while True:
    ora = time.time()

    # 🔎 Controllo nuovi preventivi
    if ora - ultimo_controllo >= INTERVALLO_CONTROLLI:
        print("🔎 Controllo nuovi preventivi...")
        try:
            check_nuovi_preventivi()
        except Exception as e:
            print(f"❌ Errore nel controllo preventivi: {e}")
        ultimo_controllo = ora

    # 🔔 Invio solleciti
    if ora - ultimo_sollecito >= INTERVALLO_SOLLECITI:
        print("🔔 Invio solleciti in corso...")
        try:
            invia_solleciti()
        except Exception as e:
            print(f"❌ Errore nell'invio solleciti: {e}")
        ultimo_sollecito = ora

    time.sleep(10)  # Piccola attesa per non sovraccaricare il sistema
