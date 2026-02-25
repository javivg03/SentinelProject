import os
import logging
import threading
import time
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector

# --- 1. CONFIGURACIÓN DE LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 2. CARGA DE VARIABLES Y COMPROBACIÓN ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TOKEN:
    logger.error("❌ ERROR: No se encontró TELEGRAM_TOKEN en las variables de entorno.")
else:
    logger.info(f"✅ Token detectado correctamente (empieza por: {TOKEN[:5]}...)")

# --- 3. SERVIDOR DE SALUD (Hugging Face) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is active")

def run_health_check():
    server = HTTPServer(('0.0.0.0', 7860), HealthCheckHandler)
    server.serve_forever()

# --- 4. INICIALIZACIÓN DE INSTANCIAS ---
sanitizer = DataSanitizer()
brain = SentinelBrain()

try:
    sheets = SheetsConnector()
    logger.info("✅ Conexión con Google Sheets establecida correctamente.")
except Exception as e:
    logger.error(f"⚠️ Google Sheets NO disponible: {e}")
    sheets = None

# --- 5. LÓGICA DE HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Respuesta al comando /start"""
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero Activado*\n\n"
        "Estoy listo. Envíame mensajes como:\n"
        "• _'15€ en Gasolina y 40€ en Supermercado'_\n"
        "Registraré todo en tu Google Sheets automáticamente.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesamiento de mensajes de texto"""
    raw_text = update.message.text
    clean_text = sanitizer.clean(raw_text)
    analysis_text, items = brain.process_transaction(clean_text)

    status_msg = ""
    if items == "DOUBT":
        status_msg = "" 
    elif sheets and isinstance(items, list) and len(items) > 0:
        exitos = 0
        for item in items:
            try:
                clean_amount = item["importe"].replace(',', '.')
                if sheets.log_expense(item["concepto"], item["categoria"], clean_amount):
                    exitos += 1
            except Exception as e:
                logger.error(f"Error registrando en Sheets: {e}")
        
        if exitos > 0:
            status_msg = f"\n\n📊 *{exitos} movimiento(s) sincronizado(s).*"
    
    final_response = f"{analysis_text}{status_msg}"
    try:
        await update.message.reply_text(final_response, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(final_response)

# --- 6. CONSTRUCCIÓN DE LA APP (Tiempos de espera optimizados) ---
app = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(60)
    .read_timeout(60)
    .write_timeout(60)
    .pool_timeout(60)
    .get_updates_connect_timeout(60)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

# --- 7. ARRANQUE PRINCIPAL CON RETRY LOOP ---
if __name__ == "__main__":
    # Arrancamos el servidor web en segundo plano
    threading.Thread(target=run_health_check, daemon=True).start()

    logger.info("⏳ Preparando motores (5s de espera para red)...")
    time.sleep(5)

    while True:
        try:
            logger.info("🚀 Sentinel intentando conectar con Telegram...")
            app.run_polling(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"❌ Error de conexión: {e}. Reintentando en 15 segundos...")
            time.sleep(15)