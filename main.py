# --- LA LÍNEA 1 ES SAGRADA: EL HACK VA AQUÍ ---
import socket
import httpx
import logging

# 1. Forzamos la obtención de la IP de Telegram vía Google HTTPS
def get_ip():
    try:
        resp = httpx.get("https://dns.google/resolve?name=api.telegram.org", timeout=5).json()
        return resp["Answer"][0]["data"]
    except:
        return "149.154.167.220" # IP de emergencia de Telegram

TARGET_IP = get_ip()

# 2. EL MONKEY PATCH (Antes de cualquier otro import)
original_getaddrinfo = socket.getaddrinfo
def hacked_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host == 'api.telegram.org':
        # Forzamos la IP y obligamos a usar IPv4 (AF_INET)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (TARGET_IP, port))]
    return original_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = hacked_getaddrinfo
# ------------------------------------------------

import os
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

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"🎯 Redirección crítica: api.telegram.org -> {TARGET_IP}")

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Servidor de salud
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is active")

def run_health_check():
    server = HTTPServer(('0.0.0.0', 7860), HealthCheckHandler)
    server.serve_forever()

# Lógica
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

if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    
    # Creamos la app con tiempos de espera muy largos
    app = ApplicationBuilder().token(TOKEN).connect_timeout(60).read_timeout(60).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("🚀 Sentinel arrancando en modo bypass...")
    app.run_polling(drop_pending_updates=True)