from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

application = Application.builder().token(BOT_TOKEN).build()

# Comando base
def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == OWNER_ID:
        return update.message.reply_text("Bot attivo e pronto! ✅")
    else:
        return update.message.reply_text("Non sei autorizzato a usare questo bot.")

application.add_handler(CommandHandler("start", start_command))

# Avvio tramite webhook
application.run_webhook(
    listen="0.0.0.0",
    port=8000,
    webhook_url="https://believable-flow-production.up.railway.app/webhook"
)
