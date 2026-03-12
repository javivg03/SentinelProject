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

# --- 1. SERVIDOR WEB Y DEPENDENCIAS GLOBALES ---
import asyncio
from aiohttp import web

# Necesitamos acceso global a estas instancias para que el webhook aiohttp pueda usarlas
# (se inicializarán abajo, antes de arrancar los servidores)
global_bank = None
global_persistence = None

async def health_check(request):
    return web.Response(text="Sentinel is alive")

async def tink_callback(request):
    """Este endpoint recibe la redirección de Tink tras autorizar el banco (code)."""
    code = request.query.get('code')
    error = request.query.get('error')
    
    if error:
        return web.Response(text=f"❌ Error Tink: {error}", status=400)
    if code:
        # 1. Intercambiamos el código interceptado por un Token Permanente
        token_data, error_msg = global_bank.exchange_code_for_token(code)
        
        if token_data and token_data.get('access_token'):
            # 2. Inyectamos silenciosamente el token en la memoria persistente del Bot
            # para no tener que usar variables globales y aprovechar el fichero .pickle de Telegram
            await global_persistence.update_bot_data({
                'tink_access_token': token_data.get('access_token'),
                'tink_refresh_token': token_data.get('refresh_token')
            })
            
            success_html = "<html><body><h1>✅ ¡Banco conectado de forma segura!</h1><p>El token de Tink se ha guardado encriptado en tu servidor. Ya puedes volver a Telegram.</p></body></html>"
            return web.Response(text=success_html, content_type='text/html')
        else:
            return web.Response(text=f"❌ Error canjeando el código por el Token: {error_msg}", status=500)
            
    return web.Response(text="Falta el parámetro 'code'.", status=400)

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/callback', tink_callback)
    
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
bank = BankConnector()
sheets = SheetsConnector()

# --- 3. LÓGICA DE COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero Online*\n\n"
        "Comandos:\n"
        "1. /conectar - Vincular banco (PSD2).\n"
        "2. /sincronizar - Descargar últimos movimientos.\n"
        "3. /activar\_asesor - Activar vigilancia proactiva de gastos.\n"
        "O simplemente escríbeme: '20€ en cena'.",
        parse_mode=ParseMode.MARKDOWN
    )

async def activar_asesor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activa el sistema de alertas proactivas usando JobQueue."""
    chat_id = update.effective_chat.id
    # Ejecutará routine_bank_check cada 60 segundos (para pruebas)
    context.job_queue.run_repeating(routine_bank_check, interval=60, first=5, chat_id=chat_id)
    await update.message.reply_text("🤖 *Asesor Proactivo Activado*\nHe calculado tus medias mensuales según tu histórico. Vigilaré tu banco en background y te alertaré si te acercas al límite.", parse_mode=ParseMode.MARKDOWN)

async def routine_bank_check(context: ContextTypes.DEFAULT_TYPE):
    """Job que se ejecuta en background sin intervención del usuario."""
    job = context.job
    chat_id = job.chat_id
    
    # Memoria para no duplicar alertas
    if 'alerted_txs' not in context.bot_data:
        context.bot_data['alerted_txs'] = set()
    
    print("⏳ [CRON] Ejecutando rutina de vigilancia...")
    
    # 1. Obtener perfil dinámico de Google Sheets (Aprendizaje Continuo)
    profile = sheets.calculate_dynamic_thresholds()
    if not profile: return
    
    # 2. Obtener últimos gastos desde el banco conectado
    connections = bank.list_connections()
    if not connections: return
    
    for conn in connections:
        accounts = bank.list_accounts(conn['id'])
        for acc in accounts:
            txs = bank.fetch_transactions(conn['id'], acc['id'])
            
            # Filtramos transacciones ya alertadas basándonos en una clave única (descripcion + importe)
            # (En Producción usaremos el transaction_id real de Tink)
            new_txs = []
            for tx in txs:
                tx_hash = f"{tx.get('description', '')}_{tx.get('amount', 0)}"
                if tx_hash not in context.bot_data['alerted_txs']:
                    new_txs.append(tx)
            
            if not new_txs:
                continue # Nada nuevo que analizar
                
            # 3. Evaluar usando la IA y el perfil matemático
            alerta, motivo = brain.evaluate_spending(new_txs, profile)
            
            if alerta:
                await context.bot.send_message(chat_id, f"🚨 <b>Alerta Financiera de Sentinel</b>\n\n{motivo}", parse_mode=ParseMode.HTML)
                # Guardamos las analizadas como alertadas
                for tx in new_txs:
                    tx_hash = f"{tx.get('description', '')}_{tx.get('amount', 0)}"
                    context.bot_data['alerted_txs'].add(tx_hash)
                
                # Sólo lanzamos una alerta a la vez por ejecución para no hacer spam.
                return

async def conectar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    link = bank.create_connect_session(BASE_URL)
    if link:
        await update.message.reply_text(f"🔗 [Vincular mi banco]({link})", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Error en la conexión. Revisa los logs.")

async def sincronizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proceso automático de descarga y análisis bancario masivo."""
    status_msg = await update.message.reply_text("🔄 *Sentinel: Escaneando bancos...*", parse_mode=ParseMode.MARKDOWN)
    
    connections = bank.list_connections()
    if not connections:
        await status_msg.edit_text("⚠️ No hay bancos vinculados. Usa /conectar.")
        return

    # 1. Memoria de Estado (Deduplicación)
    if 'synced_txs' not in context.bot_data:
        context.bot_data['synced_txs'] = set()

    exitos = 0
    total_nuevas = 0
    
    for conn in connections:
        accounts = bank.list_accounts(conn['id'])
        for acc in accounts:
            txs = bank.fetch_transactions(conn['id'], acc['id'])
            
            # 2. Filtrar ya leídas por su ID único del banco
            new_txs = [tx for tx in txs if tx.get('id') not in context.bot_data['synced_txs']]
            total_nuevas += len(new_txs)
            
            if not new_txs:
                continue
                
            # 3. Batching (Lotes de 30 para no saturar a Gemini)
            BATCH_SIZE = 30
            for i in range(0, len(new_txs), BATCH_SIZE):
                batch = new_txs[i:i+BATCH_SIZE]
                lote_actual = (i // BATCH_SIZE) + 1
                total_lotes = (len(new_txs) + BATCH_SIZE - 1) // BATCH_SIZE
                
                await status_msg.edit_text(
                    f"🔄 *Sentinel: Procesando Lote {lote_actual}/{total_lotes} ({len(batch)} txs)...*\n\n"
                    f"Esto tomará unos segundos usando Gemini AI.", 
                    parse_mode=ParseMode.MARKDOWN
                )
                
                prompts_batch = []
                for tx in batch:
                    # Empaquetamos compacto para IA
                    prompts_batch.append(f"Importe: {tx['amount']} {tx['currency_code']} | Concepto: {tx['description']}")
                
                # 4. Solicitud masiva Atómica a Gemini
                res, status = brain.process_batch_transactions(prompts_batch)
                
                if status == "SUCCESS" and res:
                    # 5. Inserción matemática masiva (1 sola escritura HTTP a Google Sheets por Lote)
                    escritos = sheets.batch_log_expenses(res)
                    exitos += escritos
                    
                    # 6. Guardar en memoria para no volver a descargar
                    for tx in batch:
                        if tx.get('id'):
                            context.bot_data['synced_txs'].add(tx['id'])
                elif "429" in str(res): # Rate Limit
                    await status_msg.edit_text("⚠️ *Sentinel Limits:* Google AI limitó las consultas gratuitas. Inténtalo de nuevo en 2 minutos.", parse_mode=ParseMode.MARKDOWN)
                    return
                
                # Pausa anti-bombardeo de 5 segundos entre Lote y Lote para respetar Tiempos de Gracia de Google
                import asyncio
                await asyncio.sleep(5)

    if total_nuevas == 0:
        await status_msg.edit_text("📊 *Sincronización completa*\nNo hay movimientos bancarios nuevos.", parse_mode=ParseMode.MARKDOWN)
    else:
        await status_msg.edit_text(f"📊 *Sincronización completa*\nSe han clasificado y registrado {exitos} gastos en un tiempo récord.", parse_mode=ParseMode.MARKDOWN)

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
    global global_bank, global_persistence
    
    # Inicializando PicklePersistence para manejo de estado persistente
    persistence = PicklePersistence(filepath="sentinel_data.pickle")
    global_persistence = persistence
    
    # Asignamos el bank_connector actual y guardamos referencia global
    global_bank = bank
    
    # Recargamos el token si ya fue guardado en alguna sesión previa
    bot_data = await persistence.get_bot_data()
    if bot_data:
        if 'tink_access_token' in bot_data:
            global_bank.access_token = bot_data['tink_access_token']
        if 'tink_refresh_token' in bot_data:
            global_bank.refresh_token = bot_data['tink_refresh_token']
            
        print(f"🔑 [Tink] Tokens recuperados de la base de datos local.")
        
    app.persistence = persistence
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("conectar", conectar))
    app.add_handler(CommandHandler("sincronizar", sincronizar))
    app.add_handler(CommandHandler("activar_asesor", activar_asesor))
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