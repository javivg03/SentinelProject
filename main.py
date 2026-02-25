import os
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector

# --- 1. CONFIGURACIÓN ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- 2. SERVIDOR DE SALUD (Render lo usa para saber que el bot vive) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is active")

def run_health_check():
    # Render usa el puerto que le da la gana, lo leemos de la variable PORT
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"✅ Servidor de salud escuchando en el puerto {port}")
    server.serve_forever()

# --- 3. LÓGICA DEL BOT ---
sanitizer = DataSanitizer()
brain = SentinelBrain()
try:
    sheets = SheetsConnector()
    logger.info("✅ Conexión con Google Sheets lista.")
except Exception as e:
    logger.error(f"⚠️ Error Sheets: {e}")
    sheets = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ *Sentinel Online*", parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    clean_text = sanitizer.clean(raw_text)
    analysis_text, items = brain.process_transaction(clean_text)
    
    status_msg = ""
    if items != "DOUBT" and sheets and isinstance(items, list):
        for item in items:
            sheets.log_expense(item["concept"], item["category"], item["amount"])
        status_msg = "\n\n📊 *Sincronizado con éxito.*"
    
    await update.message.reply_text(f"{analysis_text}{status_msg}", parse_mode=ParseMode.MARKDOWN)

# --- 4. ARRANQUE ---
def main():
    # Lanzamos el servidor de salud en un hilo
    threading.Thread(target=run_health_check, daemon=True).start()

    while True:
        try:
            logger.info("🚀 Sentinel intentando conectar con Telegram...")
            app = ApplicationBuilder().token(TOKEN).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
            
            # Esto bloquea el programa mientras el bot esté vivo
            app.run_polling(drop_pending_updates=True)
            
        except Exception as e:
            logger.error(f"❌ Error de red: {e}. Reiniciando en 15s...")
            time.sleep(15)

if __name__ == "__main__":
    main()