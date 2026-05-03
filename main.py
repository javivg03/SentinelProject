import os
import sys
import logging
import threading

# Fijar UTF-8 para la consola de Windows para evitar crasheos con los emojis de los logs
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, PicklePersistence
)
from telegram.constants import ParseMode
from dotenv import load_dotenv

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector
from document_parser import parse_document

# --- 1. SERVIDOR WEB Y DEPENDENCIAS GLOBALES ---
import asyncio
from aiohttp import web

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

# Importe mínimo para pedir confirmación manual de transacciones en "Otros"
REVIEW_THRESHOLD = 5.0

# Teclado de categorías para la revisión manual — filas de 3 para buena legibilidad en móvil
REVIEW_KEYBOARD_ROWS = [
    ["Supermercado", "Comer fuera", "Desayuno"],
    ["Antojos", "Ropa", "Tecnología"],
    ["Alcohol", "Tabaco", "Fiesta"],
    ["Viajes", "Cine", "Transporte"],
    ["Gasolina", "Coche", "Gimnasio"],
    ["Farmacia", "Peluquero", "Efectivo"],
    ["Alquiler", "Electricidad + Gas", "Regalos"],
    ["Nómina", "Suscripción Disney", "Otros"],
    ["⏭️ Ignorar (no registrar)"],
]


# --- 3. LÓGICA DE REVISIÓN MANUAL ---

def build_review_keyboard():
    """Construye el teclado inline con todas las categorías."""
    keyboard = []
    for row in REVIEW_KEYBOARD_ROWS:
        keyboard.append([
            InlineKeyboardButton(cat, callback_data=f"CAT:{cat}")
            for cat in row
        ])
    return InlineKeyboardMarkup(keyboard)


async def ask_next_pending(target, context: ContextTypes.DEFAULT_TYPE):
    """
    Envía la siguiente transacción pendiente de revisión al usuario.
    'target' puede ser un Update (primera pregunta) o un CallbackQuery (siguientes).
    """
    pending = context.user_data.get('pending_review', [])

    if not pending:
        text = "✅ ¡Revisión completada! Todas las transacciones pendientes han sido procesadas."
        if hasattr(target, 'message') and target.message:
            await target.message.reply_text(text)
        else:
            await target.edit_message_text(text)
        return

    item = pending[0]
    total_pending = len(pending)
    text = (
        f"❓ <b>Transacción sin categorizar ({total_pending} pendiente{'s' if total_pending > 1 else ''}):</b>\n\n"
        f"📝 <b>{item['concepto']}</b>\n"
        f"💸 {item['importe']}€\n"
        f"📅 {item.get('fecha', 'Sin fecha')}\n\n"
        "Selecciona la categoría correcta o ignórala:"
    )
    keyboard = build_review_keyboard()

    if hasattr(target, 'message') and target.message:
        await target.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await target.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def handle_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa la selección de categoría del usuario para una transacción pendiente."""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("CAT:"):
        return

    chosen_category = query.data[4:]  # Eliminar el prefijo "CAT:"
    pending = context.user_data.get('pending_review', [])

    if not pending:
        await query.edit_message_text("✅ No hay más transacciones pendientes.")
        return

    # Sacamos la primera transacción de la cola
    item = pending.pop(0)
    context.user_data['pending_review'] = pending

    if chosen_category == "⏭️ Ignorar (no registrar)":
        logger.info(f"Transacción ignorada manualmente: {item['concepto']} ({item['importe']}€)")
    else:
        # Registramos con la categoría elegida por el usuario
        item['categoria'] = chosen_category
        sheets.log_expense(
            item['concepto'],
            chosen_category,
            str(item['importe']),
            item.get('fecha')
        )
        logger.info(f"Registrado manualmente: {item['concepto']} → {chosen_category} ({item['importe']}€)")

    # Preguntamos por la siguiente pendiente
    await ask_next_pending(query, context)


# --- 4. HANDLERS PRINCIPALES ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ <b>Sentinel: Auditor Financiero Personal</b>\n\n"
        "Puedo ayudarte de dos formas:\n\n"
        "📝 <b>Texto natural</b>: Escríbeme un gasto y lo registro.\n"
        "    Ejemplo: <i>'Me he gastado 20€ en cena'</i>\n\n"
        "📎 <b>Extracto bancario</b>: Adjunta tu Excel o PDF del banco y proceso todos los movimientos de golpe.\n"
        "    Formatos: <code>.xls, .xlsx, .csv, .pdf</code>",
        parse_mode=ParseMode.HTML
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa mensajes de texto natural del usuario."""
    raw_text = update.message.text
    if 'history' not in context.user_data:
        context.user_data['history'] = []

    clean_text = sanitizer.clean(raw_text)
    history_str = "\n".join(context.user_data['history'])

    resultado, status = brain.process_transaction(clean_text, history=history_str)

    if status == "DOUBT":
        context.user_data['history'].append(f"Usuario: {clean_text}")
        context.user_data['history'] = context.user_data['history'][-4:]
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


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la recepción de archivos Excel (.xls, .xlsx, .csv) y PDF."""
    document = update.message.document

    ext = document.file_name.split('.')[-1].lower()
    if ext not in ['xls', 'xlsx', 'csv', 'pdf']:
        await update.message.reply_text("❌ Formato no soportado. Por favor, sube un Excel (.xls, .xlsx, .csv) o PDF.")
        return

    msg = await update.message.reply_text("📥 Descargando y procesando documento...")

    try:
        file_obj = await context.bot.get_file(document.file_id)
        local_path = f"temp_{document.file_name}"
        await file_obj.download_to_drive(local_path)

        raw_text = parse_document(local_path)

        # Sanitizamos datos sensibles ANTES de enviar a la IA (Zero-Trust)
        raw_text = sanitizer.clean(raw_text)

        if len(raw_text) > 15000:
            raw_text = raw_text[:15000] + "\n[... documento truncado ...]"

        await msg.edit_text("🧠 Analizando transacciones con IA...")

        resultado, status = brain.process_raw_document(raw_text)

        # Borramos el archivo local inmediatamente por seguridad (Zero-Trust)
        if os.path.exists(local_path):
            os.remove(local_path)

        if status != "SUCCESS" or not resultado:
            await msg.edit_text(
                "⚠️ La IA no encontró transacciones procesables en el documento.\n"
                f"Status: {status}. Comprueba los logs en Render para más detalle."
            )
            return

        # Separar transacciones confirmadas de las que necesitan revisión manual:
        # - Las de categoría "Otros" con importe > REVIEW_THRESHOLD van a la cola de revisión
        # - El resto se registran directamente en Sheets
        to_review = [
            m for m in resultado
            if m.get('categoria', '').lower() == 'otros'
            and float(m.get('importe', 0)) > REVIEW_THRESHOLD
        ]
        to_register = [m for m in resultado if m not in to_review]

        await msg.edit_text(f"📦 Registrando {len(to_register)} transacciones en Google Sheets...")
        total_insertados = sheets.batch_log_expenses(to_register)

        # Guardamos la cola de revisión en el estado persistente del usuario
        if to_review:
            context.user_data['pending_review'] = to_review
            await msg.edit_text(
                f"✅ Registradas <b>{total_insertados}</b> transacciones automáticamente.\n\n"
                f"❓ Hay <b>{len(to_review)}</b> transacciones en categoría 'Otros' (>{REVIEW_THRESHOLD}€) "
                f"que necesitan tu confirmación. Vamos a revisarlas una a una:",
                parse_mode=ParseMode.HTML
            )
            await ask_next_pending(update, context)
        else:
            await msg.edit_text(f"✅ ¡Éxito! Se han registrado {total_insertados} transacciones en tu presupuesto.")

    except Exception as e:
        logger.error(f"Error en handle_document: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error técnico: <code>{str(e)}</code>", parse_mode=ParseMode.HTML)
        if os.path.exists(f"temp_{document.file_name}"):
            os.remove(f"temp_{document.file_name}")


# --- 5. ARRANQUE ---
async def start_services(app):
    global global_persistence

    persistence = PicklePersistence(filepath="sentinel_data.pickle")
    global_persistence = persistence
    app.persistence = persistence

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    # Handler para los botones de categorización manual (debe registrarse DESPUÉS de los MessageHandlers)
    app.add_handler(CallbackQueryHandler(handle_category_callback, pattern="^CAT:"))

    if os.environ.get("RENDER_EXTERNAL_URL"):
        asyncio.create_task(run_web_server())
        print("🌐 Servidor Web de salud iniciado (modo Render).")
    else:
        print("💻 Modo local detectado: servidor web de salud desactivado.")
    print("🚀 Sentinel iniciado correctamente.")


if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.post_init = start_services

    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        pass