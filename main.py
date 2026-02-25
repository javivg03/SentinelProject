import os
import logging
import threading
import time
import httpx
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

# --- 2. SERVIDOR DE SALUD (Obligatorio en Hugging Face) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is active")

def run_health_check():
    server = HTTPServer(('0.0.0.0', 7860), HealthCheckHandler)
    server.serve_forever()

# --- 3. LÓGICA DEL BOT ---
sanitizer = DataSanitizer()
brain = SentinelBrain()
try:
    sheets = SheetsConnector()
    logger.info("✅ Google Sheets conectado.")
except Exception as e:
    logger.error(f"⚠️ Sheets error: {e}")
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
            sheets.log_expense(item["concepto"], item["categoria"], item["importe"].replace(',', '.'))
        status_msg = f"\n\n📊 *Sincronizado.*"
    await update.message.reply_text(f"{analysis_text}{status_msg}", parse_mode=ParseMode.MARKDOWN)

# --- 4. ARRANQUE ROBUSTO ---
if __name__ == "__main__":
    # Arrancamos el servidor de salud
    threading.Thread(target=run_health_check, daemon=True).start()

    # LA CLAVE: Configuramos un cliente HTTP con reintentos y límites de tiempo generosos
    # Esto es lo que recomienda la comunidad para entornos como Hugging Face o Railway
    logger.info("🚀 Configurando motor de red...")
    
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .get_updates_connect_timeout(40.0)
        # Esto permite que la librería maneje los reintentos de conexión por sí sola
        .connection_pool_size(8) 
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("🛡️ Sentinel listo. Arrancando...")
    
    # Usamos un bucle simple de reintento en caso de fallo de red inicial
    # Esta es la forma más normal de manejar nubes con red inestable al arranque
    while True:
        try:
            app.run_polling(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"Fallo de conexión: {e}. Reintentando en 15s...")
            time.sleep(15)