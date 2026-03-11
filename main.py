import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, PicklePersistence
from telegram.constants import ParseMode
from dotenv import load_dotenv

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector
from bank_connector import BankConnector 

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

TOKEN = os.getenv("TELEGRAM_TOKEN")
sanitizer = DataSanitizer()
brain = SentinelBrain()
bank = BankConnector()
sheets = SheetsConnector()

# --- 3. LÓGICA DE COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero Online*\n\n"
        "Comandos:\n"
        "1. /conectar - Vincular banco (PSD2).\n"
        "2. /sincronizar - Descargar últimos movimientos.\n"
        "3. O simplemente escríbeme: '20€ en cena'.",
        parse_mode=ParseMode.MARKDOWN
    )

async def conectar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    link = bank.create_connect_session(BASE_URL)
    if link:
        await update.message.reply_text(f"🔗 [Vincular mi banco]({link})", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Error en la conexión. Revisa los logs.")

async def sincronizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proceso automático de descarga y análisis bancario."""
    status_msg = await update.message.reply_text("🔄 *Sentinel: Escaneando bancos...*", parse_mode=ParseMode.MARKDOWN)
    
    connections = bank.list_connections()
    if not connections:
        await status_msg.edit_text("⚠️ No hay bancos vinculados. Usa /conectar.")
        return

    exitos = 0
    for conn in connections:
        accounts = bank.list_accounts(conn['id'])
        for acc in accounts:
            txs = bank.fetch_transactions(conn['id'], acc['id'])
            for tx in txs:
                # Transformamos el movimiento en lenguaje natural para la IA
                prompt = f"{tx['amount']} {tx['currency_code']} en {tx['description']}"
                res, status = brain.process_transaction(prompt)
                
                if status == "SUCCESS":
                    for item in res:
                        if sheets.log_expense(item['concepto'], item['categoria'], str(item['importe'])):
                            exitos += 1

    await status_msg.edit_text(f"📊 *Sincronización completa*\nSe han registrado {exitos} movimientos nuevos en tu Sheets.", parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mantenemos tu lógica original de historial y dudas."""
    raw_text = update.message.text
    if 'history' not in context.user_data:
        context.user_data['history'] = []

    clean_text = sanitizer.clean(raw_text)
    history_str = "\n".join(context.user_data['history'])
    
    resultado, status = brain.process_transaction(clean_text, history=history_str)

    if status == "DOUBT":
        context.user_data['history'].append(f"Usuario: {clean_text}")
        context.user_data['history'] = context.user_data['history'][-4:]
        await update.message.reply_text(resultado, parse_mode=ParseMode.MARKDOWN)

    elif status == "SUCCESS":
        final_response = "🛡️ *Análisis de Sentinel*\n\n"
        registrados = 0
        for item in resultado:
            if sheets and sheets.log_expense(item['concepto'], item['categoria'], str(item['importe'])):
                registrados += 1
                final_response += f"💰 *{item['concepto']}*\n🏷️ {item['categoria']}\n📉 {item['importe']}€\n\n"
        
        if registrados > 0:
            context.user_data['history'] = [] 
            await update.message.reply_text(final_response + "✅ Registrado.", parse_mode=ParseMode.MARKDOWN)

# --- 4. ARRANQUE ---
if __name__ == '__main__':
    threading.Thread(target=run_health_check, daemon=True).start()
    
    # Inicializando PicklePersistence para manejo de estado (dudas) persistente entre reinicios
    persistence = PicklePersistence(filepath="sentinel_data.pickle")
    
    app = ApplicationBuilder().token(TOKEN).persistence(persistence).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("conectar", conectar))
    app.add_handler(CommandHandler("sincronizar", sincronizar))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling(drop_pending_updates=True)