import os
import logging
import threading
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

# --- 2. SERVIDOR DE SALUD ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is active")
    # Para evitar el error 501 que veíamos en Render
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"✅ Servidor de salud en puerto {port}")
    server.serve_forever()

# --- 3. LÓGICA DEL BOT ---
sanitizer = DataSanitizer()
brain = SentinelBrain()
try:
    sheets = SheetsConnector()
    logger.info("✅ Conexión con Google Sheets inicializada.")
except Exception as e:
    logger.error(f"⚠️ Error Sheets: {e}")
    sheets = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ *Sentinel Online*", parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    clean_text = sanitizer.clean(raw_text)
    # Aquí la IA procesa el texto
    analysis_text, items = brain.process_transaction(clean_text)
    
    status_msg = ""
    # IMPORTANTE: Usamos "concepto", "categoria" e "importe" si tu IA devuelve español
    if items != "DOUBT" and sheets and isinstance(items, list):
        for item in items:
            # Intentamos ambos idiomas por si acaso
            c = item.get("concepto") or item.get("concept")
            cat = item.get("categoria") or item.get("category")
            imp = item.get("importe") or item.get("amount")
            
            if sheets.log_expense(c, cat, imp):
                status_msg = "\n\n📊 *Sincronizado con éxito.*"
            else:
                status_msg = "\n\n⚠️ *Error al guardar en Excel.*"
    
    await update.message.reply_text(f"{analysis_text}{status_msg}", parse_mode=ParseMode.MARKDOWN)

# --- 4. ARRANQUE ---
if __name__ == "__main__":
    # Arrancamos salud
    threading.Thread(target=run_health_check, daemon=True).start()

    logger.info("🚀 Sentinel arrancando...")
    
    # Creamos la app (sin bucles manuales, run_polling ya es estable por sí solo)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    app.run_polling(drop_pending_updates=True)