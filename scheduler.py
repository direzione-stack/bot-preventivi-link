import time
from bot_link_preventivi_drive import check_nuovi_preventivi, invia_solleciti

# === INTERVALLI IN SECONDI ===
INTERVALLO_CONTROLLI = 300            # ogni 5 minuti
INTERVALLO_SOLLECITI = 3600           # ogni 1 ora

# === STATO INIZIALE ===
ultimo_controllo = 0
ultimo_sollecito = 0

print("\U0001F7E2 BOT preventivi avviato e in esecuzione...")

while True:
    ora = time.time()

    # Controlla nuovi preventivi ogni 5 minuti
    if ora - ultimo_controllo >= INTERVALLO_CONTROLLI:
        print("\U0001F50D Controllo nuovi preventivi...")
        try:
            check_nuovi_preventivi()
        except Exception as e:
            print(f"❌ Errore durante controllo preventivi: {e}")
        ultimo_controllo = ora

    # Invia solleciti ogni 1 ora
    if ora - ultimo_sollecito >= INTERVALLO_SOLLECITI:
        print("\U0001F4A1 Invio solleciti in corso...")
        try:
            invia_solleciti()
        except Exception as e:
            print(f"❌ Errore durante invio solleciti: {e}")
        ultimo_sollecito = ora

    time.sleep(10)  # breve attesa per non sovraccaricare il sistema
