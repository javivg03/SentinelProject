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
from bank_connector import BankConnector 

# --- 1. SERVIDOR DE SALUD (Compatibilidad con Render) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is alive")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_health_check():
    # Render usa el puerto 10000 por defecto
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- 2. CONFIGURACIÓN E INICIALIZACIÓN ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
sanitizer = DataSanitizer()
brain = SentinelBrain()
bank = BankConnector() # Inicialización limpia de Salt Edge v6

try:
    sheets = SheetsConnector()
    logger.info("✅ Conexión con Google Sheets establecida.")
except Exception as e:
    logger.error(f"⚠️ Google Sheets NO disponible: {e}")
    sheets = None

# --- 3. LÓGICA DE COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida profesional."""
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero Online*\n\n"
        "Puedo registrar tus gastos de dos formas:\n"
        "1. Escríbeme un mensaje (ej: '30€ en cena con amigos').\n"
        "2. Usa /conectar para sincronizar tu banco automáticamente.\n\n"
        "¿Qué prefieres hacer ahora?",
        parse_mode=ParseMode.MARKDOWN
    )

async def conectar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera el enlace de vinculación bancaria mediante Salt Edge v6."""
    # Limpiamos la URL de posibles espacios invisibles que causan el error 400
    BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    
    if not BASE_URL:
        await update.message.reply_text(
            "❌ *Error de Configuración*\n\n"
            "No se ha detectado la variable `RENDER_EXTERNAL_URL` en Render.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Llamada al conector v6
    link = bank.create_connect_session(BASE_URL)
    
    if link:
        await update.message.reply_text(
            "🛡️ *Sentinel: Vinculación Bancaria (PSD2)*\n\n"
            "Haz clic en el botón para autorizar el acceso de lectura a tus movimientos. "
            "Es un proceso cifrado y seguro bajo normativa europea:\n\n"
            f"[🔗 Conectar mi banco de forma segura]({link})",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Si esto falla, el motivo aparecerá en los Logs de Render gracias al print en bank_connector.py
        await update.message.reply_text(
            "❌ *Error de Conexión (400)*\n\n"
            "Salt Edge ha rechazado la petición. Por favor, revisa los Logs en Render para ver el detalle del error."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesamiento de gastos enviados por texto plano."""
    raw_text = update.message.text
    if 'history' not in context.user_data:
        context.user_data['history'] = []

    clean_text = sanitizer.clean(raw_text)
    history_str = "\n".join(context.user_data['history'])
    
    # Procesamos con la IA
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
            
            if sheets and sheets.log_expense(conc, cat, str(amo)):
                exitos += 1
                final_response += f"💰 *{conc}*\n🏷️ {cat}\n📉 {amo}€\n🤖 _{insight}_\n\n"

        if exitos > 0:
            context.user_data['history'] = [] 
            final_response += f"📊 *{exitos} movimiento(s) sincronizado(s).*"
            await update.message.reply_text(final_response, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ No he podido registrar los datos en la hoja.")
    else:
        await update.message.reply_text("⚠️ No he entendido bien ese gasto. ¿Podrías repetirlo?")

# --- 4. ARRANQUE DEL SISTEMA ---
if __name__ == '__main__':
    if not TOKEN:
        logger.error("No se encontró TELEGRAM_TOKEN en el entorno.")
        exit(1)
        
    threading.Thread(target=run_health_check, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("conectar", conectar))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Sentinel Operativo con Salt Edge v6. Escuchando...")
    app.run_polling(drop_pending_updates=True)