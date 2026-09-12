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
    update: Update, user_question: str, intent_data: dict = None, context: ContextTypes.DEFAULT_TYPE = None
) -> None:
    """
    Ejecuta la consulta determinista en Google Sheets y devuelve la respuesta
    formateada con las cifras reales (sin alucinaciones numéricas).
    """
    msg = await update.message.reply_text("📊 Consultando tus datos financieros...")

    intent_data = intent_data or {}
    query_type = intent_data.get("query_type", "monthly_summary")
    month = intent_data.get("month")
    category = intent_data.get("category")

    data = None
    # Si se especificó una categoría concreta (ej. Nómina, Gasolina), siempre priorizarla
    if category:
        data = sheets.get_category_spending(category, month)
        query_type = "category_total"
    elif query_type == "income_breakdown" or ("desglos" in user_question.lower() and "ingres" in user_question.lower()):
        data = sheets.get_income_breakdown(month)
        query_type = "income_breakdown"
    elif query_type == "patrimony":
        data = sheets.get_patrimony()
    elif query_type in ("monthly_summary", "monthly_savings", "monthly_income"):
        data = sheets.get_monthly_summary(month)
    elif query_type == "top_categories":
        data = sheets.get_top_categories(month)
    elif query_type == "last_transactions":
        data = sheets.get_recent_transactions()
    else:
        data = sheets.get_monthly_summary(month)
        query_type = "monthly_summary"

    answer = brain.format_query_response(query_type, data, user_question)
    await msg.edit_text(answer, parse_mode=ParseMode.HTML)

    # Registrar en historial para permitir preguntas de seguimiento contextual ("Desglosado", "Solo nómina", etc.)
    if context and "history" in context.user_data:
        m_name = (sheets.MONTH_NAMES[month - 1] if month else "actual")
        context.user_data["history"].append(f"Usuario: {user_question}")
        context.user_data["history"].append(f"Sentinel: consulta {query_type} de {m_name}")
        context.user_data["history"] = context.user_data["history"][-6:]


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
    history_str = "\n".join(context.user_data["history"])

    # ── Paso 1: Clasificar intención (usando historial para preguntas de seguimiento) ──
    intent_data = brain.classify_intent(clean_text, history=history_str)
    intent = intent_data.get("intent", "log")

    # ── Paso 2: Enrutar según intención ─────────────────────────────────────
    if intent in ("query", "analysis"):
        await handle_financial_question(update, clean_text, intent_data, context)
        return


    if intent == "unknown":
        await update.message.reply_text(
            "🤔 No estoy seguro de lo que quieres hacer.\n"
            "Puedes registrar un gasto (<i>'25€ en Mercadona'</i>) "
            "o consultarme algo (<i>'¿cuánto llevo en gasolina?'</i> o <i>'¿cuál es mi patrimonio?'</i>).",
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
        final_response = "🛡️ <b>Registro de Sentinel</b>\n\n"
        registrados = 0
        fallidos = 0
        budget_alerts = []

        for item in resultado:
            res = sheets.log_expense(
                item["concepto"],
                item["categoria"],
                str(item["importe"]),
                item.get("fecha"),
                item.get("tipo"),
            )
            if isinstance(res, dict) and res.get("success"):
                registrados += 1
                new_tot = res.get("new_total", 0.0)
                m_name = res.get("month_name", "")
                final_response += (
                    f"💰 <b>{item['concepto']}</b>\n"
                    f"🏷️ {item['categoria']} ({m_name})\n"
                    f"📉 {item['importe']}€ (acumulado mes: {new_tot:.2f}€)\n\n"
                )
                if res.get("budget_alert"):
                    budget_alerts.append(res["budget_alert"])
            else:
                fallidos += 1
                final_response += (
                    f"❌ <b>Fallo:</b> {item['concepto']}\n"
                    f"🏷️ {item['categoria']} (error al escribir en Sheets)\n"
                    f"📉 {item['importe']}€\n\n"
                )

        context.user_data["history"] = []

        # Si hay alertas de presupuesto, añadirlas
        if budget_alerts:
            final_response += "\n".join(budget_alerts) + "\n\n"

        if registrados > 0 and fallidos == 0:
            await update.message.reply_text(
                final_response + "✅ Movimiento registrado en matriz y log.",
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

async def debug_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /debug — muestra estado de conexión y datos clave en tiempo real."""
    now_m = datetime.datetime.now().month
    summary = sheets.get_monthly_summary(now_m)
    patrimony = sheets.get_patrimony()

    text = (
        f"<b>🔍 Debug — Sentinel en vivo</b>\n\n"
        f"<b>Libro:</b> {sheets.spreadsheet.title}\n"
        f"<b>Pestaña activa:</b> {sheets.matrix_sheet.title}\n\n"
        f"<b>Mes actual ({summary.get('month_name', 'N/A')}):</b>\n"
        f"  • Ingresos: {summary.get('total_ingresos', 0):.2f}€\n"
        f"  • Gastos vitales: {summary.get('total_gastos_vitales', 0):.2f}€\n"
        f"  • Gastos ocio: {summary.get('total_gastos_ocio', 0):.2f}€\n"
        f"  • Ahorro neto: {summary.get('ahorro_neto', 0):.2f}€\n\n"
        f"<b>Patrimonio ({patrimony.get('month_name', 'N/A')}):</b>\n"
        f"  • Total: {patrimony.get('patrimonio_total', 0):.2f}€"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def register_handlers(app) -> None:
    """Registra todos los handlers en la aplicación de PTB."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("debug", debug_sheet))
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