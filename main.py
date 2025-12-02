from telegram.ext import Application, CommandHandler, MessageHandler, filters
import logging
import os

# --- CONFIGURAZIONE ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
RAILWAY_URL = "https://believable-flow-production.up.railway.app"  # <--- aggiorna se diverso

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- HANDLER DI COMANDO ---
async def start(update, context):
    await update.message.reply_text("✅ Bot attivo e funzionante!")

async def echo(update, context):
    await update.message.reply_text(f"Hai detto: {update.message.text}")

# --- MAIN ---
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Start con webhook
    await app.run_webhook(
        listen="0.0.0.0",
        port=8000,
        webhook_url=f"{RAILWAY_URL}/webhook",
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
