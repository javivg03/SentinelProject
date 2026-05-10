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


async def handle_query_intent(
    update: Update, intent_data: dict
) -> None:
    """
    Resuelve consultas financieras del usuario leyendo datos de Google Sheets.
    Enrutado desde handle_message() cuando classify_intent() devuelve 'query'.
    """
    q_type = intent_data.get("query_type")
    category = intent_data.get("category")
    now = datetime.datetime.now()
    month_name = MONTH_NAMES.get(now.month, "este mes")

    # ── Gasto en una categoría concreta ──────────────────────────────────────
    if q_type == "category_total" and category:
        total = sheets.query_category_total(category)
        if total == -1.0:
            await update.message.reply_text(
                f"❌ No encontré la categoría <b>{category}</b> en tu presupuesto.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                f"📊 En <b>{category}</b> llevas gastados <b>{total}€</b> en {month_name}.",
                parse_mode=ParseMode.HTML,
            )

    # ── Total gastado en el mes ───────────────────────────────────────────────
    elif q_type == "monthly_total":
        data = sheets.query_monthly_totals()
        await update.message.reply_text(
            f"📅 Total gastado en <b>{month_name}</b>: <b>{data.get('expenses', 0)}€</b>",
            parse_mode=ParseMode.HTML,
        )

    # ── Ingresos del mes ─────────────────────────────────────────────────────
    elif q_type == "monthly_income":
        data = sheets.query_monthly_totals()
        await update.message.reply_text(
            f"💼 Ingresos en <b>{month_name}</b>: <b>{data.get('income', 0)}€</b>",
            parse_mode=ParseMode.HTML,
        )

    # ── Ahorro del mes ───────────────────────────────────────────────────────
    elif q_type == "monthly_savings":
        data = sheets.query_monthly_totals()
        savings = data.get("savings", 0)
        emoji = "✅" if savings >= 0 else "⚠️"
        await update.message.reply_text(
            f"{emoji} Ahorro en <b>{month_name}</b>: <b>{savings}€</b>\n"
            f"(Ingresos: {data.get('income', 0)}€ — Gastos: {data.get('expenses', 0)}€)",
            parse_mode=ParseMode.HTML,
        )

    # ── Total entre dos fechas ───────────────────────────────────────────────
    elif q_type == "period_total":
        start = intent_data.get("period_start")
        end = intent_data.get("period_end") or now.strftime("%Y-%m-%d")
        if not start:
            # Si no hay fecha inicio, asumimos esta semana
            start = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        result = sheets.query_period_total(start, end)
        await update.message.reply_text(
            f"📆 Entre <b>{start}</b> y <b>{end}</b>:\n"
            f"  💸 Gastos: <b>{result['expenses']}€</b>\n"
            f"  💼 Ingresos: <b>{result['income']}€</b>\n"
            f"  🔢 Transacciones: {result['count']}",
            parse_mode=ParseMode.HTML,
        )

    # ── Últimos 7 días ───────────────────────────────────────────────────────
    elif q_type == "weekly_total":
        start = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        result = sheets.query_period_total(start, end)
        await update.message.reply_text(
            f"📆 Últimos 7 días: <b>{result['expenses']}€</b> en gastos "
            f"({result['count']} transacciones)",
            parse_mode=ParseMode.HTML,
        )

    # ── Categorías top ───────────────────────────────────────────────────────
    elif q_type == "top_categories":
        limit = intent_data.get("limit", 5)
        top = sheets.query_top_categories(top_n=limit)
        if not top:
            await update.message.reply_text("No hay datos de gasto este mes.")
            return
        lines = "\n".join(
            f"  {i+1}. <b>{item['categoria']}</b>: {item['total']}€"
            for i, item in enumerate(top)
        )
        await update.message.reply_text(
            f"🏆 Top {limit} categorías en <b>{month_name}</b>:\n{lines}",
            parse_mode=ParseMode.HTML,
        )

    # ── Últimas N transacciones ──────────────────────────────────────────────
    elif q_type == "last_transactions":
        limit = intent_data.get("limit", 5)
        txns = sheets.query_last_transactions(limit=limit)
        if not txns:
            await update.message.reply_text("No hay transacciones registradas aún.")
            return
        lines = "\n".join(
            f"  • <b>{t['concepto']}</b> — {t['importe']}€ [{t['fecha']}]"
            for t in txns
        )
        await update.message.reply_text(
            f"🕐 Últimas {limit} transacciones:\n{lines}",
            parse_mode=ParseMode.HTML,
        )

    else:
        await update.message.reply_text(
            "No entendí exactamente qué datos quieres ver. "
            "Prueba con: '¿cuánto llevo en supermercado?', "
            "'¿cuánto he gastado esta semana?', etc."
        )


async def handle_analysis_intent(
    update: Update, intent_data: dict
) -> None:
    """
    Genera un análisis financiero en lenguaje natural usando Gemini.
    Enrutado desde handle_message() cuando classify_intent() devuelve 'analysis'.
    """
    await update.message.reply_text("🧠 Analizando tus finanzas...")
    data = sheets.query_monthly_totals()
    if not data:
        await update.message.reply_text(
            "⚠️ No pude leer datos del Sheet para el análisis. "
            "Comprueba la conexión con Google Sheets."
        )
        return
    focus = intent_data.get("focus")
    analysis_text = brain.generate_analysis(data, focus=focus)
    await update.message.reply_text(analysis_text)


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
    if intent == "query":
        await handle_query_intent(update, intent_data)
        return

    if intent == "analysis":
        await handle_analysis_intent(update, intent_data)
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

async def post_init(app) -> None:
    """Registra todos los handlers tras inicializar la aplicación de PTB."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern="^CAT:"))
    logger.info("🚀 Handlers registrados correctamente.")


# ─────────────────────────────────────────────────────────────────────────────
# 6. SERVIDOR DE HEALTH CHECK (para ping externo en Render)
# ─────────────────────────────────────────────────────────────────────────────

async def health_check(request) -> web.Response:
    """
    Endpoint HTTP GET / que responde 200 OK.
    Permite que UptimeRobot, cron-job.org y Render marquen el servicio
    como "activo" sin errores 404.
    """
    return web.Response(text="Sentinel está activo ✅")


# ─────────────────────────────────────────────────────────────────────────────
# 7. ARRANQUE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    persistence = PicklePersistence(filepath="sentinel_data.pickle")
    app = ApplicationBuilder().token(TOKEN).persistence(persistence).build()
    app.post_init = post_init

    if RENDER_URL:
        # ── PRODUCCIÓN (Render): Webhook + Health Check ──────────────────
        # PTB levanta el servidor en el puerto $PORT con run_webhook().
        # Añadimos la ruta / para responder 200 OK a los pings de UptimeRobot.
        logger.info(f"🌐 Iniciando en modo WEBHOOK → {RENDER_URL}/webhook")

        aio_app = web.Application()
        aio_app.router.add_get("/", health_check)

        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 10000)),
            url_path="webhook",
            webhook_url=f"{RENDER_URL}/webhook",
            drop_pending_updates=True,
            webserver=aio_app,
        )
    else:
        # ── DESARROLLO LOCAL: Polling ────────────────────────────────────
        logger.info("💻 Iniciando en modo POLLING (desarrollo local).")
        try:
            app.run_polling(drop_pending_updates=True)
        except KeyboardInterrupt:
            pass