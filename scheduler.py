import time
from bot_link_preventivi_drive import check_nuovi_preventivi, invia_solleciti

# Intervalli in secondi
INTERVALLO_CONTROLLI = 300          # Ogni 5 minuti
INTERVALLO_SOLLECITI = 5 * 60 * 60  # Ogni 5 ore

ultimo_controllo = 0
ultimo_sollecito = 0

print("✅ TEST AVVIO: scheduler.py è stato eseguito correttamente!")

while True:
    ora = time.time()

    # Controllo nuovi preventivi
    if ora - ultimo_controllo >= INTERVALLO_CONTROLLI:
        print("🔍 Controllo nuovi preventivi in corso...")
        check_nuovi_preventivi()
        ultimo_controllo = ora

    # Invio solleciti
    if ora - ultimo_sollecito >= INTERVALLO_SOLLECITI:
        print("
