import os
import logging
import threading
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector

# --- 1. CONFIGURACIÓN DE RED PARA RENDER (Obligatorio) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is active")
    def do_HEAD(self): # Evita errores 501 en los logs de Render
        self.send_response(200)
        self.end_headers()

def run_health_check():
    # Render asigna un puerto dinámico; si no lo usamos, el bot se apaga
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- 2. LOGGING Y CARGA ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Instancias globales
sanitizer = DataSanitizer()
brain = SentinelBrain()

try:
    sheets = SheetsConnector()
    logger.info("✅ Conexión con Google Sheets establecida correctamente.")
except Exception as e:
    logger.error(f"⚠️ Google Sheets NO disponible: {e}")
    sheets = None

# --- 3. LÓGICA DE TELEGRAM (Tu estructura original) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero Activado*\n\n"
        "Estoy listo para procesar tus finanzas. Registrare todo automáticamente.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    clean_text = sanitizer.clean(raw_text)
    analysis_text, items = brain.process_transaction(clean_text)

    status_msg = ""
    
    # CASO A: La IA tiene dudas
    if items == "DOUBT":
        status_msg = "\n\n🤔 *Necesito confirmación:* No he registrado nada. ¿Podrías ser más específico?"

    # CASO B: Hay movimientos para registrar
    elif sheets and isinstance(items, list) and len(items) > 0:
        exitos = 0
        for item in items:
            try:
                # Soporte para llaves en español o inglés por si Gemini cambia de humor
                c = item.get("concepto") or item.get("concept")
                cat = item.get("categoria") or item.get("category")
                imp = str(item.get("importe") or item.get("amount")).replace(',', '.')
                
                if sheets.log_expense(c, cat, imp):
                    exitos += 1
            except Exception as e:
                logger.error(f"Fallo al registrar item {item}: {e}")

        if exitos > 0:
            status_msg = f"\n\n📊 *{exitos} movimiento(s) sincronizado(s).* "
        else:
            status_msg = "\n\n❌ *Error al escribir en el Excel.*"

    # CASO C: No se detectó nada
    elif not items or len(items) == 0:
        status_msg = "\n\n⚠️ *No he detectado ningún gasto válido.*"

    # ENVÍO FINAL (Con el fix para el error "BadRequest" de Markdown)
    final_response = f"{analysis_text}{status_msg}"
    try:
        await update.message.reply_text(final_response, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # Si Gemini manda caracteres raros que rompen el Markdown, enviamos texto plano
        await update.message.reply_text(final_response)

# --- 4. ARRANQUE ---
if __name__ == '__main__':
    if not TOKEN:
        exit(1)

    # Iniciar servidor de salud en segundo plano
    threading.Thread(target=run_health_check, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logger.info("🚀 Sentinel Operativo en la nube.")
    app.run_polling(drop_pending_updates=True)