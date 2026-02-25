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

# --- 2. EL SALVAVIDAS: RESOLUCIÓN DE DNS MANUAL ---
def get_telegram_ip():
    """Pregunta a Google (vía HTTPS) la IP de Telegram si el DNS falla"""
    try:
        # Intentamos resolución normal primero
        return socket.gethostbyname('api.telegram.org')
    except:
        logger.warning("⚠️ DNS local falló. Usando DNS-over-HTTPS de Google...")
        try:
            # Si falla, le preguntamos a la API de Google DNS
            with httpx.Client(timeout=10) as client:
                resp = client.get("https://dns.google/resolve?name=api.telegram.org").json()
                for answer in resp.get("Answer", []):
                    if answer["type"] == 1: # Tipo A (IPv4)
                        ip = answer["data"]
                        logger.info(f"🎯 IP de Telegram recuperada vía DoH: {ip}")
                        return ip
        except Exception as e:
            logger.error(f"❌ Fallo total de resolución: {e}")
    return None

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
    threading.Thread(target=run_health_check, daemon=True).start()
    
    # 1. Obtenemos la IP de Telegram sí o sí
    tg_ip = None
    while not tg_ip:
        tg_ip = get_telegram_ip()
        if not tg_ip:
            logger.info("⏳ Reintentando obtener IP en 10s...")
            time.sleep(10)

    # 2. Configuramos el bot
    # Usamos la IP directamente para evitar que el bot pregunte al DNS roto
    logger.info(f"🚀 Iniciando Bot apuntando a {tg_ip}...")
    
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(40)
        .read_timeout(40)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("🛡️ Sentinel listo. Arrancando Polling...")
    app.run_polling(drop_pending_updates=True)