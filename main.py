# main.py
from telegram.ext import Updater
from bot_link_preventivi_drive import main as preventivo_main
from scheduler import start_scheduler

if __name__ == '__main__':
    # Avvia il bot per la gestione dei preventivi
    preventivo_main()
    
    # Avvia il sistema di sollecito (scheduler)
    start_scheduler()
