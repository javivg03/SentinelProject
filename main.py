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
# --- 1. SERVIDOR WEB Y DEPENDENCIAS GLOBALES ---
import asyncio
from aiohttp import web

# Necesitamos acceso global a estas instancias para que el webhook aiohttp pueda usarlas
# (se inicializarán abajo, antes de arrancar los servidores)
global_persistence = None

async def health_check(request):
    return web.Response(text="Sentinel is alive")

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    print(f"🌐 Servidor Web iniciado en puerto {port}")
    await site.start()

# --- 2. CONFIGURACIÓN ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
sanitizer = DataSanitizer()
brain = SentinelBrain()
sheets = SheetsConnector()

# --- 3. LÓGICA DE COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero Online*\n\n"
        "Actualmente puedes registrar gastos escribiéndome.\n"
        "Próximamente: Sincronización masiva subiendo archivos Excel/CSV de tu banco.\n\n"
        "Ejemplo: 'Me he gastado 20€ en cena'.",
        parse_mode=ParseMode.MARKDOWN
    )


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
        # Enviamos como texto plano para evitar que fallos de la IA rompan el bot
        await update.message.reply_text(resultado)

    elif status == "SUCCESS":
        final_response = "🛡️ <b>Análisis de Sentinel</b>\n\n"
        registrados = 0
        for item in resultado:
            if sheets and sheets.log_expense(item['concepto'], item['categoria'], str(item['importe'])):
                registrados += 1
                final_response += f"💰 <b>{item['concepto']}</b>\n🏷️ {item['categoria']}\n📉 {item['importe']}€\n\n"
        
        if registrados > 0:
            context.user_data['history'] = [] 
            await update.message.reply_text(final_response + "✅ Registrado.", parse_mode=ParseMode.HTML)

# --- 4. ARRANQUE ---
async def start_services(app):
    global global_persistence
    
    # Inicializando PicklePersistence para manejo de estado persistente
    persistence = PicklePersistence(filepath="sentinel_data.pickle")
    global_persistence = persistence
    
    app.persistence = persistence
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Iniciar servidor aiohttp en background como una Task de asyncio
    asyncio.create_task(run_web_server())
    print("🚀 Sentinel iniciado correctamente con JobQueue y Servidor Web.")

if __name__ == '__main__':
    # Usamos la gestión de ciclo de vida nativo de PTB (Python Telegram Bot) 20+
    # que cierra automáticamente el event loop al pulsar CTRL+C
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Enganchamos nuestra inicialización y el mini-servidor web a la fase de arranque (Post-Init)
    app.post_init = start_services
    
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        pass