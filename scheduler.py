import time
import threading

# Stato globale dei preventivi per ogni gruppo
current_states = {}

def avvia_solleciti(bot, owner_id):
    def ciclo():
        while True:
            now = time.time()
            for chat_id, preventivi in current_states.items():
                for nome, stato in preventivi.items():
                    if not stato["confermato"]:
                        elapsed = now - stato["timestamp"]
                        if 14400 <= elapsed < 14460:
                            bot.send_message(chat_id=chat_id, text=f"🔔 Primo sollecito: conferma il preventivo *{nome}*", parse_mode='Markdown')
                        elif 28800 <= elapsed < 28860:
                            bot.send_message(chat_id=chat_id, text=f"🔔 Secondo sollecito per il preventivo *{nome}*", parse_mode='Markdown')
                        elif 86400 <= elapsed < 86460:
                            bot.send_message(chat_id=chat_id, text=f"❌ Nessuna conferma per il preventivo *{nome}*. Verrà riassegnato.", parse_mode='Markdown')
                            stato["confermato"] = True
                            bot.send_message(chat_id=owner_id, text=f"❌ Il gruppo {chat_id} NON ha confermato il preventivo: {nome}")
            time.sleep(60)
    threading.Thread(target=ciclo, daemon=True).start()
