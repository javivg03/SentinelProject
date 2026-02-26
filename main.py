import os
import logging
import threading  # Necesario para el servidor de salud
from http.server import HTTPServer, BaseHTTPRequestHandler # Para que Render esté contento
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector

# --- 1. SERVIDOR DE SALUD (Lo que Render exige para no matar al bot) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is alive")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_health_check():
    # Render nos asigna un puerto en la variable PORT, si no existe usamos el 10000
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- 2. CONFIGURACIÓN ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

sanitizer = DataSanitizer()
brain = SentinelBrain()

try:
    sheets = SheetsConnector()
    logger.info("✅ Conexión con Google Sheets establecida correctamente.")
except Exception as e:
    logger.error(f"⚠️ Google Sheets NO disponible: {e}")
    sheets = None

# --- 3. TU LÓGICA ORIGINAL (Mantenida intacta) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero Activado*\n\n"
        "Estoy listo para procesar tus finanzas. Registraré todo automáticamente.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    clean_text = sanitizer.clean(raw_text)
    analysis_text, items = brain.process_transaction(clean_text)

    status_msg = ""
    
    if items == "DOUBT":
        status_msg = "" # La IA ya explica la duda en analysis_text
        logger.info("Sentinel (IA) solicitó aclaración.")

    elif sheets and isinstance(items, list) and len(items) > 0:
        exitos = 0
        for item in items:
            try:
                # Usamos get para evitar que el bot pete si una llave falta
                conc = item.get("concepto") or item.get("concept")
                cat = item.get("categoria") or item.get("category")
                amo = str(item.get("importe") or item.get("amount")).replace(',', '.')
                
                if sheets.log_expense(conc, cat, amo):
                    exitos += 1
            except Exception as e:
                logger.error(f"Error registrando item: {e}")

        if exitos > 0:
            status_msg = f"\n\n📊 *{exitos} movimiento(s) sincronizado(s).*"

    else:
        status_msg = "" 
        logger.info("Mensaje de cortesía o sin datos.")

    final_response = f"{analysis_text}{status_msg}"
    
    try:
        await update.message.reply_text(final_response, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"Error Markdown: {e}")
        await update.message.reply_text(final_response)

# --- 4. ARRANQUE HÍBRIDO ---
if __name__ == '__main__':
    if not TOKEN:
        logger.error("No se encontró TELEGRAM_TOKEN.")
        exit(1)

    # Lanzamos el servidor de salud en un hilo separado
    # Esto permite que Render vea el puerto abierto mientras el bot escucha Telegram
    threading.Thread(target=run_health_check, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Sentinel Operativo en Cloud. Escuchando...")
    app.run_polling(drop_pending_updates=True)