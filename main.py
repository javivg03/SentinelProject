import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from dotenv import load_dotenv

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector

# --- 1. SERVIDOR DE SALUD ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is alive")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- 2. CONFIGURACIÓN ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

sanitizer = DataSanitizer()
brain = SentinelBrain()
try:
    sheets = SheetsConnector()
except Exception as e:
    logger.error(f"⚠️ Sheets error: {e}")
    sheets = None

# --- 3. LÓGICA ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ *Sentinel Online*")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    if 'history' not in context.user_data:
        context.user_data['history'] = []

    clean_text = sanitizer.clean(raw_text)
    history_str = "\n".join(context.user_data['history'])
    
    # RESULTADO es la lista (o texto de duda), STATUS es el estado
    resultado, status = brain.process_transaction(clean_text, history=history_str)

    if status == "DOUBT":
        context.user_data['history'].append(f"Usuario: {clean_text}")
        context.user_data['history'] = context.user_data['history'][-4:]
        await update.message.reply_text(resultado, parse_mode=ParseMode.MARKDOWN)

    elif status == "SUCCESS":
        if not isinstance(resultado, list) or len(resultado) == 0:
            await update.message.reply_text("No he detectado movimientos claros.")
            return

        exitos = 0
        final_response = "🛡️ *Análisis de Sentinel*\n\n"
        
        for item in resultado:
            conc = item.get("concepto")
            cat = item.get("categoria")
            amo = item.get("importe")
            insight = item.get("analisis_ia", "Registrado correctamente.")
            
            # Registro en Sheets
            if sheets and sheets.log_expense(conc, cat, str(amo)):
                exitos += 1
                final_response += f"💰 *{conc}*\n🏷️ {cat}\n📉 {amo}€\n🤖 _{insight}_\n\n"

        if exitos > 0:
            context.user_data['history'] = [] # Limpiamos memoria tras el éxito
            final_response += f"📊 *{exitos} movimiento(s) sincronizado(s).*"
            await update.message.reply_text(final_response, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ No he podido registrar los datos en la hoja.")

    else:
        await update.message.reply_text("⚠️ Error procesando el mensaje.")

# --- 4. ARRANQUE ---
if __name__ == '__main__':
    threading.Thread(target=run_health_check, daemon=True).start()
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling(drop_pending_updates=True)