import os
import logging
import threading
import time
import socket
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

# --- 2. DIAGNÓSTICO DE RED (Para saber qué pasa realmente) ---
def diagnostic_network():
    logger.info("🕵️ Ejecutando diagnóstico de red...")
    hosts = ['google.com', 'api.telegram.org']
    for host in hosts:
        try:
            ip = socket.gethostbyname(host)
            logger.info(f"✅ DNS OK: {host} -> {ip}")
        except Exception as e:
            logger.error(f"❌ DNS FALLO: {host} no se puede resolver. Error: {e}")

# --- 3. SERVIDOR DE SALUD ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is active")

def run_health_check():
    server = HTTPServer(('0.0.0.0', 7860), HealthCheckHandler)
    server.serve_forever()

# --- 4. LÓGICA DEL BOT ---
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
        status_msg = f"\n\n📊 *Sincronizado.*"
    await update.message.reply_text(f"{analysis_text}{status_msg}", parse_mode=ParseMode.MARKDOWN)

# --- 5. ARRANQUE MAESTRO ---
if __name__ == "__main__":
    # Arrancamos el servidor de salud inmediatamente
    threading.Thread(target=run_health_check, daemon=True).start()
    
    # 1. Ver qué está pasando con el DNS
    diagnostic_network()

    # 2. Configurar HTTPX para que sea más agresivo y use IPv4 si es posible
    # Forzamos un cliente con tiempos de espera largos
    logger.info("🚀 Iniciando ApplicationBuilder...")
    
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .proxy_url(None) # Aseguramos que no intente usar proxys raros
        .get_updates_connect_timeout(30)
        .connect_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("🛡️ Sentinel listo. Arrancando Polling...")
    
    # run_polling gestiona su propio bucle interno de reintentos
    app.run_polling(drop_pending_updates=True)