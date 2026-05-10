import asyncio
import os
import sys
import logging
import datetime

# Fijar UTF-8 en la consola de Windows para evitar crasheos con emojis en los logs
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    PicklePersistence,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector
from document_parser import parse_document

# ─────────────────────────────────────────────────────────────────────────────
# 1. CONFIGURACIÓN INICIAL
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

# Módulos compartidos — instanciados una sola vez al arrancar
sanitizer = DataSanitizer()
brain = SentinelBrain()
sheets = SheetsConnector()

# Importe mínimo (€) para solicitar revisión manual en categoría "Otros"
REVIEW_THRESHOLD = 5.0

# Categorías disponibles para el teclado inline de revisión
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


# ─────────────────────────────────────────────────────────────────────────────
# 2. HELPERS DE REVISIÓN MANUAL (Botones Inline)
# ─────────────────────────────────────────────────────────────────────────────

def build_review_keyboard() -> InlineKeyboardMarkup:
    """Construye el teclado inline con todas las categorías disponibles."""
    keyboard = [
        [InlineKeyboardButton(cat, callback_data=f"CAT:{cat}") for cat in row]
        for row in REVIEW_KEYBOARD_ROWS
    ]
    return InlineKeyboardMarkup(keyboard)


async def ask_next_pending(
    target, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Presenta la siguiente transacción pendiente de revisión al usuario.

    - Si target es un CallbackQuery: edita el mensaje actual (flujo limpio sin spam)
    - Si target es un Update: envía un mensaje nuevo (primera llamada del flujo)
    """
    pending = context.user_data.get("pending_review", [])

    if not pending:
        text = "✅ ¡Revisión completada! Todas las transacciones han sido procesadas."
        if isinstance(target, CallbackQuery):
            await target.edit_message_text(text)
        else:
            await target.message.reply_text(text)
        return

    item = pending[0]
    n = len(pending)
    text = (
        f"❓ <b>Transacción sin categorizar ({n} pendiente{'s' if n > 1 else ''}):</b>\n\n"
        f"📝 <b>{item['concepto']}</b>\n"
        f"💸 {item['importe']}€\n"
        f"📅 {item.get('fecha', 'Sin fecha')}\n\n"
        "Selecciona la categoría correcta o ignórala:"
    )
    keyboard = build_review_keyboard()

    if isinstance(target, CallbackQuery):
        await target.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )
    else:
        await target.message.reply_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. HELPERS DE CONSULTAS FINANCIERAS
# ─────────────────────────────────────────────────────────────────────────────

MONTH_NAMES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


async def handle_financial_question(
    update: Update, user_question: str
) -> None:
    """
    Responde CUALQUIER consulta o análisis financiero del usuario.

    Reemplaza los dos handlers anteriores (handle_query_intent y
    handle_analysis_intent) con un enfoque unificado:
    1. Leer TODOS los datos del Sheet de una sola vez (todos los meses,
       todas las categorías)
    2. Pasar esos datos + la pregunta del usuario a Gemini
    3. Dejar que Gemini responda libremente sin restricciones

    Es equivalente a pegarle el Excel completo al usuario y que él mismo
    responda cualquier duda. Sin limitaciones de mes ni de tipo de consulta.
    """
    msg = await update.message.reply_text("📊 Consultando tus datos financieros...")

    budget_data = sheets.get_full_budget_data()
    if not budget_data:
        await msg.edit_text(
            "⚠️ No pude leer datos de tu hoja de presupuesto. "
            "Comprueba que el Sheet tiene datos y la conexión está activa."
        )
        return

    answer = brain.answer_financial_question(budget_data, user_question)
    await msg.edit_text(answer, parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────────────────────────────────────
# 4. HANDLERS PRINCIPALES
# ─────────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /start — presenta las funcionalidades del bot."""
    await update.message.reply_text(
        "🛡️ <b>Sentinel: Auditor Financiero Personal</b>\n\n"
        "Puedo ayudarte de tres formas:\n\n"
        "📝 <b>Registro de gastos</b>: Escríbeme un gasto y lo registro.\n"
        "    <i>'Me he gastado 20€ en cena'</i>\n\n"
        "📎 <b>Extractos bancarios</b>: Adjunta tu Excel o PDF del banco.\n"
        "    Formatos: <code>.xls, .xlsx, .csv, .pdf</code>\n\n"
        "📊 <b>Consultas financieras</b>: Pregúntame por tus datos.\n"
        "    <i>'¿Cuánto llevo en gasolina?'</i>\n"
        "    <i>'¿Cuánto he ahorrado este mes?'</i>\n"
        "    <i>'¿Cómo voy con el presupuesto?'</i>",
        parse_mode=ParseMode.HTML,
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Procesa la pulsación de un botón de categoría para una transacción pendiente.
    Solo gestiona callbacks con prefijo 'CAT:'.
    """
    query = update.callback_query
    await query.answer()  # Elimina el spinner de carga del botón en Telegram

    if not query.data.startswith("CAT:"):
        return

    chosen_category = query.data[4:]
    pending = context.user_data.get("pending_review", [])

    if not pending:
        await query.edit_message_text("✅ No hay más transacciones pendientes.")
        return

    item = pending.pop(0)
    context.user_data["pending_review"] = pending

    if chosen_category == "⏭️ Ignorar (no registrar)":
        logger.info(f"Ignorado por el usuario: {item['concepto']} ({item['importe']}€)")
    else:
        sheets.log_expense(
            item["concepto"],
            chosen_category,
            str(item["importe"]),
            item.get("fecha"),
        )
        logger.info(
            f"Categorizado manualmente: {item['concepto']} → {chosen_category} ({item['importe']}€)"
        )

    await ask_next_pending(query, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Procesador principal de mensajes de texto.

    Pipeline de 2 pasos:
    1. classify_intent() determina si el usuario quiere registrar, consultar o analizar
    2. Se enruta al handler apropiado según la intención detectada
    """
    raw_text = update.message.text
    if "history" not in context.user_data:
        context.user_data["history"] = []

    clean_text = sanitizer.clean(raw_text)

    # ── Paso 1: Clasificar intención ─────────────────────────────────────────
    intent_data = brain.classify_intent(clean_text)
    intent = intent_data.get("intent", "log")

    # ── Paso 2: Enrutar según intención ─────────────────────────────────────
    # Tanto 'query' como 'analysis' van al mismo handler unificado.
    # La diferencia entre "consulta" y "análisis" la gestiona Gemini internamente.
    if intent in ("query", "analysis"):
        await handle_financial_question(update, clean_text)
        return

    if intent == "unknown":
        await update.message.reply_text(
            "🤔 No estoy seguro de lo que quieres hacer.\n"
            "Puedes registrar un gasto (<i>'25€ en Mercadona'</i>) "
            "o consultarme algo (<i>'¿cuánto llevo este mes?'</i>).",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── intent == "log": registrar transacción ───────────────────────────────
    history_str = "\n".join(context.user_data["history"])
    resultado, status = brain.process_transaction(clean_text, history=history_str)

    if status == "DOUBT":
        context.user_data["history"].append(f"Usuario: {clean_text}")
        context.user_data["history"] = context.user_data["history"][-4:]
        await update.message.reply_text(resultado)
        return

    if status == "SUCCESS":
        final_response = "🛡️ <b>Análisis de Sentinel</b>\n\n"
        registrados = 0
        fallidos = 0

        for item in resultado:
            if sheets.log_expense(
                item["concepto"], item["categoria"], str(item["importe"])
            ):
                registrados += 1
                final_response += (
                    f"💰 <b>{item['concepto']}</b>\n"
                    f"🏷️ {item['categoria']}\n"
                    f"📉 {item['importe']}€\n\n"
                )
            else:
                fallidos += 1
                final_response += (
                    f"❌ <b>Fallo:</b> {item['concepto']}\n"
                    f"🏷️ {item['categoria']} (categoría no encontrada o error de Sheets)\n"
                    f"📉 {item['importe']}€\n\n"
                )

        context.user_data["history"] = []

        if registrados > 0 and fallidos == 0:
            await update.message.reply_text(
                final_response + "✅ Todo registrado correctamente.",
                parse_mode=ParseMode.HTML,
            )
        elif registrados > 0:
            await update.message.reply_text(
                final_response + "⚠️ Registrado parcialmente. Revisa los errores.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                final_response + "❌ No se pudo registrar ningún movimiento.",
                parse_mode=ParseMode.HTML,
            )


async def handle_document(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Maneja la recepción de extractos bancarios (Excel o PDF).

    Pipeline:
    1. Descarga y valida el formato del archivo
    2. Extrae texto con document_parser
    3. Sanitiza datos sensibles (Zero-Trust)
    4. Envía a Gemini para categorización masiva
    5. Registra automáticamente lo categorizable
    6. Encola en 'pending_review' lo que va a 'Otros' (>REVIEW_THRESHOLD€)
    """
    document = update.message.document
    ext = document.file_name.split(".")[-1].lower()

    if ext not in ["xls", "xlsx", "csv", "pdf"]:
        await update.message.reply_text(
            "❌ Formato no soportado.\n"
            "Formatos aceptados: <code>.xls, .xlsx, .csv, .pdf</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    msg = await update.message.reply_text("📥 Descargando y procesando documento...")
    local_path = f"temp_{document.file_name}"

    try:
        file_obj = await context.bot.get_file(document.file_id)
        await file_obj.download_to_drive(local_path)

        raw_text = parse_document(local_path)

        # Sanitizamos datos sensibles ANTES de enviar a la IA (Zero-Trust)
        raw_text = sanitizer.clean(raw_text)

        # Limitamos el texto para evitar superar el contexto de Gemini
        if len(raw_text) > 15000:
            raw_text = raw_text[:15000] + "\n[... documento truncado ...]"

        await msg.edit_text("🧠 Analizando transacciones con IA...")
        resultado, status = brain.process_raw_document(raw_text)

        # Borramos el archivo temporal inmediatamente (Zero-Trust)
        if os.path.exists(local_path):
            os.remove(local_path)

        if status != "SUCCESS" or not resultado:
            await msg.edit_text(
                "⚠️ La IA no encontró transacciones procesables en el documento.\n"
                f"Status: {status}. Revisa los logs de Render para más detalle."
            )
            return

        # Separar: revisión manual vs. registro automático
        to_review = [
            m for m in resultado
            if m.get("categoria", "").lower() == "otros"
            and float(m.get("importe", 0)) > REVIEW_THRESHOLD
        ]
        to_register = [m for m in resultado if m not in to_review]

        await msg.edit_text(
            f"📦 Registrando {len(to_register)} transacciones en Google Sheets..."
        )
        total_insertados = sheets.batch_log_expenses(to_register)

        if to_review:
            context.user_data["pending_review"] = to_review
            await msg.edit_text(
                f"✅ Registradas <b>{total_insertados}</b> transacciones automáticamente.\n\n"
                f"❓ Hay <b>{len(to_review)}</b> en 'Otros' (>{REVIEW_THRESHOLD}€) "
                "que necesitan tu confirmación:",
                parse_mode=ParseMode.HTML,
            )
            await ask_next_pending(update, context)
        else:
            await msg.edit_text(
                f"✅ ¡Éxito! Se han registrado <b>{total_insertados}</b> "
                "transacciones en tu presupuesto.",
                parse_mode=ParseMode.HTML,
            )

    except Exception as e:
        logger.error(f"Error en handle_document: {e}", exc_info=True)
        await msg.edit_text(
            f"❌ Error técnico: <code>{str(e)}</code>", parse_mode=ParseMode.HTML
        )
        if os.path.exists(local_path):
            os.remove(local_path)


# ─────────────────────────────────────────────────────────────────────────────
# 5. REGISTRO DE HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def register_handlers(app) -> None:
    """Registra todos los handlers en la aplicación de PTB."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern="^CAT:"))
    logger.info("🚀 Handlers registrados correctamente.")


# ─────────────────────────────────────────────────────────────────────────────
# 6. ARRANQUE — Webhook personalizado con Health Check en /
# ─────────────────────────────────────────────────────────────────────────────

async def run_webhook_server(ptb_app, port: int, webhook_url: str) -> None:
    """
    Servidor de producción: aiohttp como servidor HTTP principal.

    En lugar de usar run_webhook() de PTB (que no permite añadir rutas
    personalizadas en v22), gestionamos nuestro propio servidor aiohttp:
    - POST /webhook → recibe updates de Telegram y los pasa a PTB
    - GET  /        → responde 200 OK para UptimeRobot y cron-job.org

    Esto nos da control total del servidor sin depender de parámetros
    privados o no documentados de la librería.
    """

    async def telegram_webhook(request: web.Request) -> web.Response:
        """Recibe el update de Telegram y lo inyecta en la cola de PTB."""
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
        return web.Response(text="OK")

    async def health_check(request: web.Request) -> web.Response:
        """Responde 200 OK para mantener el servicio activo en Render."""
        return web.Response(text="Sentinel está activo ✅")

    # Construir servidor aiohttp
    aio_app = web.Application()
    aio_app.router.add_post("/webhook", telegram_webhook)
    aio_app.router.add_get("/", health_check)

    # Inicializar PTB y registrar el webhook en la API de Telegram
    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
    )
    logger.info(f"🔗 Webhook registrado en Telegram: {webhook_url}")

    # Arrancar servidor HTTP
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Servidor HTTP escuchando en puerto {port}")

    try:
        # Mantener el proceso vivo indefinidamente
        await asyncio.Event().wait()
    finally:
        logger.info("🛑 Apagando Sentinel...")
        await ptb_app.stop()
        await ptb_app.shutdown()
        await runner.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# 7. PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    persistence = PicklePersistence(filepath="sentinel_data.pickle")
    ptb_app = ApplicationBuilder().token(TOKEN).persistence(persistence).build()
    register_handlers(ptb_app)

    if RENDER_URL:
        # ── PRODUCCIÓN (Render): Servidor aiohttp con webhook + health check
        logger.info(f"🌐 Iniciando en modo WEBHOOK → {RENDER_URL}/webhook")
        PORT = int(os.environ.get("PORT", 10000))
        asyncio.run(
            run_webhook_server(
                ptb_app=ptb_app,
                port=PORT,
                webhook_url=f"{RENDER_URL}/webhook",
            )
        )
    else:
        # ── DESARROLLO LOCAL: Polling (no requiere URL pública)
        logger.info("💻 Iniciando en modo POLLING (desarrollo local).")
        try:
            ptb_app.run_polling(drop_pending_updates=True)
        except KeyboardInterrupt:
            pass