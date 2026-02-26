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

# --- 1. SERVIDOR DE SALUD (Render Compatibility) ---
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

# --- 2. CONFIGURACIÓN Y CARGA ---
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
    logger.info("✅ Conexión con Google Sheets establecida.")
except Exception as e:
    logger.error(f"⚠️ Google Sheets NO disponible: {e}")
    sheets = None

# --- 3. LÓGICA DE NEGOCIO ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero con Memoria Activado*\n\n"
        "Ahora puedo recordar el contexto. Si olvidas el importe, puedes enviármelo en el siguiente mensaje.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    
    # Inicializar historial del usuario si no existe
    if 'history' not in context.user_data:
        context.user_data['history'] = []

    # Sanitizar y recuperar contexto previo
    clean_text = sanitizer.clean(raw_text)
    history_str = "\n".join(context.user_data['history'])
    
    # Procesar con el motor de IA (Brain) enviando el historial
    analysis_text, items = brain.process_transaction(clean_text, history=history_str)

    if items == "DOUBT":
        # Guardamos en memoria para completar en el siguiente mensaje
        context.user_data['history'].append(f"Usuario: {clean_text}")
        # Mantenemos solo los últimos 4 mensajes para optimizar
        context.user_data['history'] = context.user_data['history'][-4:]
        
        logger.info("Sentinel solicitó aclaración (Duda guardada en contexto).")
        await update.message.reply_text(analysis_text, parse_mode=ParseMode.MARKDOWN)

    elif items == "ERROR":
        await update.message.reply_text("❌ Lo siento, he tenido un error interno procesando tus datos.")

    elif sheets and isinstance(items, list) and len(items) > 0:
        exitos = 0
        response_msg = "🛡️ *Análisis de Sentinel*\n\n"
        
        for item in items:
            try:
                # Extracción desde el JSON estructurado de la IA
                conc = item.get("concepto")
                cat = item.get("categoria")
                amo = item.get("importe")
                insight = item.get("analisis_ia", "Gasto registrado correctamente.")
                
                if sheets.log_expense(conc, cat, str(amo)):
                    exitos += 1
                    response_msg += f"💰 *{conc}*\n🏷️ {cat}\n📉 {amo}€\n🤖 _{insight}_\n\n"
            except Exception as e:
                logger.error(f"Error registrando item: {e}")

        if exitos > 0:
            # ¡ÉXITO! Limpiamos la memoria para evitar mezclar con futuros gastos
            context.user_data['history'] = []
            response_msg += f"📊 *{exitos} movimiento(s) sincronizado(s). Memoria liberada.*"
            await update.message.reply_text(response_msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("No he podido sincronizar los datos con la hoja de cálculo.")

    else:
        # Mensajes de cortesía o sin datos financieros detectados
        logger.info("Mensaje sin datos financieros.")
        await update.message.reply_text(analysis_text)

# --- 4. ARRANQUE DEL SISTEMA ---
if __name__ == '__main__':
    if not TOKEN:
        logger.error("No se encontró TELEGRAM_TOKEN.")
        exit(1)

    # Hilo para Health Check (Render)
    threading.Thread(target=run_health_check, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Sentinel Operativo con Memoria Contextual. Escuchando...")
    app.run_polling(drop_pending_updates=True)