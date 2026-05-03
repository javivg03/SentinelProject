import os
import sys
import logging

# Fijar UTF-8 para la consola de Windows para evitar crasheos con los emojis de los logs
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
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

import asyncio

# --- 1. CONFIGURACIÓN ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

sanitizer = DataSanitizer()
brain = SentinelBrain()
sheets = SheetsConnector()

# Importe mínimo (€) para pedir confirmación manual en transacciones "Otros"
REVIEW_THRESHOLD = 5.0

# Teclado de categorías para revisión manual — filas de 3 para buena legibilidad en móvil
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


# --- 2. LÓGICA DE REVISIÓN MANUAL ---

def build_review_keyboard():
    """Construye el teclado inline con todas las categorías disponibles."""
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
    - Si 'target' es un CallbackQuery: edita el mensaje existente (flujo de revisión).
    - Si 'target' es un Update: envía un mensaje nuevo (primera pregunta tras procesar el documento).
    """
    pending = context.user_data.get('pending_review', [])

    if not pending:
        text = "✅ ¡Revisión completada! Todas las transacciones pendientes han sido procesadas."
        if isinstance(target, CallbackQuery):
            await target.edit_message_text(text)
        else:
            await target.message.reply_text(text)
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

    if isinstance(target, CallbackQuery):
        # Editamos el mensaje existente para que sea un flujo limpio sin spam
        await target.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        # Primera llamada desde handle_document: enviamos mensaje nuevo
        await target.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def handle_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa la pulsación de un botón de categoría para una transacción pendiente."""
    query = update.callback_query
    await query.answer()  # Elimina el spinner de carga del botón

    if not query.data.startswith("CAT:"):
        return

    chosen_category = query.data[4:]  # Eliminar el prefijo "CAT:"
    pending = context.user_data.get('pending_review', [])

    if not pending:
        await query.edit_message_text("✅ No hay más transacciones pendientes de revisión.")
        return

    # Extraemos la primera transacción de la cola y actualizamos el estado
    item = pending.pop(0)
    context.user_data['pending_review'] = pending

    if chosen_category == "⏭️ Ignorar (no registrar)":
        logger.info(f"Transacción ignorada por el usuario: {item['concepto']} ({item['importe']}€)")
    else:
        # Registramos con la categoría corregida manualmente por el usuario
        sheets.log_expense(
            item['concepto'],
            chosen_category,
            str(item['importe']),
            item.get('fecha')
        )
        logger.info(f"Registrado manualmente: {item['concepto']} → {chosen_category} ({item['importe']}€)")

    # Pasamos a la siguiente transacción pendiente
    await ask_next_pending(query, context)


# --- 3. HANDLERS PRINCIPALES ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start — presenta las funcionalidades del bot."""
    await update.message.reply_text(
        "🛡️ <b>Sentinel: Auditor Financiero Personal</b>\n\n"
        "Puedo ayudarte de dos formas:\n\n"
        "📝 <b>Texto natural</b>: Escríbeme un gasto y lo registro.\n"
        "    Ejemplo: <i>'Me he gastado 20€ en cena'</i>\n\n"
        "📎 <b>Extracto bancario</b>: Adjunta tu Excel o PDF del banco y proceso todos los movimientos de golpe.\n"
        "    Formatos soportados: <code>.xls, .xlsx, .csv, .pdf</code>",
        parse_mode=ParseMode.HTML
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa mensajes de texto natural del usuario para registro de gastos individuales."""
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
        fallidos = 0
        for item in resultado:
            if sheets and sheets.log_expense(item['concepto'], item['categoria'], str(item['importe'])):
                registrados += 1
                final_response += (
                    f"💰 <b>{item['concepto']}</b>\n"
                    f"🏷️ {item['categoria']}\n"
                    f"📉 {item['importe']}€\n\n"
                )
            else:
                fallidos += 1
                final_response += (
                    f"❌ <b>Fallo al registrar:</b> {item['concepto']}\n"
                    f"🏷️ {item['categoria']} (Categoría no encontrada o error de Sheets)\n"
                    f"📉 {item['importe']}€\n\n"
                )

        context.user_data['history'] = []
        if registrados > 0 and fallidos == 0:
            await update.message.reply_text(final_response + "✅ Todo registrado correctamente.", parse_mode=ParseMode.HTML)
        elif registrados > 0 and fallidos > 0:
            await update.message.reply_text(final_response + "⚠️ Registrado parcialmente. Revisa los errores.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(final_response + "❌ No se pudo registrar ningún movimiento.", parse_mode=ParseMode.HTML)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la recepción de extractos bancarios (Excel o PDF) para procesamiento masivo."""
    document = update.message.document

    ext = document.file_name.split('.')[-1].lower()
    if ext not in ['xls', 'xlsx', 'csv', 'pdf']:
        await update.message.reply_text(
            "❌ Formato no soportado.\n"
            "Formatos aceptados: <code>.xls, .xlsx, .csv, .pdf</code>",
            parse_mode=ParseMode.HTML
        )
        return

    msg = await update.message.reply_text("📥 Descargando y procesando documento...")

    try:
        file_obj = await context.bot.get_file(document.file_id)
        local_path = f"temp_{document.file_name}"
        await file_obj.download_to_drive(local_path)

        raw_text = parse_document(local_path)

        # Sanitizamos datos sensibles ANTES de enviar a la IA (Zero-Trust)
        # Elimina IBANs, DNIs, tarjetas de crédito y teléfonos del texto
        raw_text = sanitizer.clean(raw_text)

        # Limitamos a 15.000 chars para robustez ante documentos inusualmente largos
        if len(raw_text) > 15000:
            raw_text = raw_text[:15000] + "\n[... documento truncado ...]"

        await msg.edit_text("🧠 Analizando transacciones con IA...")

        resultado, status = brain.process_raw_document(raw_text)

        # Borramos el archivo temporal inmediatamente por seguridad (Zero-Trust)
        if os.path.exists(local_path):
            os.remove(local_path)

        if status != "SUCCESS" or not resultado:
            await msg.edit_text(
                "⚠️ La IA no encontró transacciones procesables en el documento.\n"
                f"Status: {status}. Comprueba los logs en Render para más detalle."
            )
            return

        # Separar transacciones por flujo:
        # - "Otros" con importe > REVIEW_THRESHOLD → cola de revisión manual
        # - Resto → registro automático en Sheets
        to_review = [
            m for m in resultado
            if m.get('categoria', '').lower() == 'otros'
            and float(m.get('importe', 0)) > REVIEW_THRESHOLD
        ]
        to_register = [m for m in resultado if m not in to_review]

        await msg.edit_text(f"📦 Registrando {len(to_register)} transacciones en Google Sheets...")
        total_insertados = sheets.batch_log_expenses(to_register)

        if to_review:
            context.user_data['pending_review'] = to_review
            await msg.edit_text(
                f"✅ Registradas <b>{total_insertados}</b> transacciones automáticamente.\n\n"
                f"❓ Hay <b>{len(to_review)}</b> transacciones en 'Otros' (>{REVIEW_THRESHOLD}€) "
                "que necesitan tu confirmación. Vamos una a una:",
                parse_mode=ParseMode.HTML
            )
            await ask_next_pending(update, context)
        else:
            await msg.edit_text(
                f"✅ ¡Éxito! Se han registrado <b>{total_insertados}</b> transacciones en tu presupuesto.",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error en handle_document: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error técnico: <code>{str(e)}</code>", parse_mode=ParseMode.HTML)
        temp = f"temp_{document.file_name}"
        if os.path.exists(temp):
            os.remove(temp)


# --- 4. ARRANQUE ---
async def post_init(app):
    """Registro de handlers. Se ejecuta tras inicializar la aplicación."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    # CallbackQueryHandler para los botones inline de revisión manual
    app.add_handler(CallbackQueryHandler(handle_category_callback, pattern="^CAT:"))
    logger.info("🚀 Handlers registrados correctamente.")


if __name__ == '__main__':
    # PicklePersistence inicializado en ApplicationBuilder para garantizar
    # que context.user_data persiste correctamente entre handlers
    persistence = PicklePersistence(filepath="sentinel_data.pickle")
    app = ApplicationBuilder().token(TOKEN).persistence(persistence).build()
    app.post_init = post_init

    if RENDER_URL:
        # ── PRODUCCIÓN (Render): Webhook ────────────────────────────────────
        # Telegram envía updates directamente a nuestra URL → sin conflictos,
        # sin polling, sin instancias duplicadas. Modo correcto para producción.
        logger.info(f"🌐 Iniciando en modo WEBHOOK → {RENDER_URL}/webhook")
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 10000)),
            url_path="webhook",
            webhook_url=f"{RENDER_URL}/webhook",
            drop_pending_updates=True,
        )
    else:
        # ── DESARROLLO LOCAL: Polling ────────────────────────────────────────
        # Cómodo para desarrollo: no requiere URL pública ni certificado SSL.
        logger.info("💻 Iniciando en modo POLLING (desarrollo local).")
        try:
            app.run_polling(drop_pending_updates=True)
        except KeyboardInterrupt:
            pass