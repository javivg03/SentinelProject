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

# --- 2. EL HACK DEFINITIVO: MONKEY PATCHING DEL SOCKET ---
# Guardamos la función original de buscar direcciones
original_getaddrinfo = socket.getaddrinfo

def get_telegram_ip_doh():
    """Consigue la IP de Telegram usando Google DNS sobre HTTPS"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get("https://dns.google/resolve?name=api.telegram.org").json()
            for answer in resp.get("Answer", []):
                if answer["type"] == 1: # IPv4
                    return answer["data"]
    except Exception as e:
        logger.error(f"❌ No se pudo obtener IP vía DoH: {e}")
    return "149.154.167.220" # IP de respaldo por si Google fallara

# Obtenemos la IP real
TARGET_IP = get_telegram_ip_doh()
logger.info(f"🎯 IP de Telegram fijada en: {TARGET_IP}")

def hacked_getaddrinfo(*args):
    """Engaña al sistema: si preguntan por Telegram, devuelve la IP fija"""
    if args[0] == 'api.telegram.org':
        # Devolvemos la estructura que espera Python para una conexión exitosa
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (TARGET_IP, args[1]))]
    return original_getaddrinfo(*args)

# Inyectamos nuestro hack en el corazón de Python
socket.getaddrinfo = hacked_getaddrinfo

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

# --- 5. ARRANQUE ---
if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("🛡️ Sentinel listo (DNS Hackeado). Arrancando...")
    app.run_polling(drop_pending_updates=True)