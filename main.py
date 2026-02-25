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

# --- 1. CONFIGURACIÓN Y LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- 2. SERVIDOR DE SALUD ---
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
    logger.info("✅ Conexión con Google Sheets establecida.")
except Exception as e:
    logger.error(f"⚠️ Sheets no disponible: {e}")
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
        status_msg = f"\n\n📊 *Sincronizado con Sheets.*"
    await update.message.reply_text(f"{analysis_text}{status_msg}", parse_mode=ParseMode.MARKDOWN)

# --- 4. CONSTRUCCIÓN DE LA APP ---
# Quitamos los reintentos manuales y dejamos que la librería maneje su loop
app = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(30)
    .read_timeout(30)
    .get_updates_connect_timeout(30)
    .pool_timeout(30)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

if __name__ == "__main__":
    # Arrancamos el servidor de salud (Hugging Face lo necesita)
    threading.Thread(target=run_health_check, daemon=True).start()
    
    # IMPORTANTE: Espera generosa de 20 segundos para que la red de HF esté 100% lista
    logger.info("⏳ Esperando 20s para estabilización de red...")
    time.sleep(20)

    logger.info("🚀 Sentinel intentando conectar con Telegram...")
    # Ejecutamos SIN bucle. Si falla, Hugging Face reiniciará el contenedor.
    app.run_polling(drop_pending_updates=True)