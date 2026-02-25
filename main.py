import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector

# Configuración de Logging profesional
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Instancias globales
sanitizer = DataSanitizer()
brain = SentinelBrain()

# Inicialización de Sheets con verificación de salud
try:
    sheets = SheetsConnector()
    logger.info("✅ Conexión con Google Sheets establecida correctamente.")
except Exception as e:
    logger.error(f"⚠️ Google Sheets NO disponible. El bot funcionará solo como consultor: {e}")
    sheets = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida con instrucciones claras"""
    await update.message.reply_text(
        "🛡️ *Sentinel: Auditor Financiero Activado*\n\n"
        "Estoy listo para procesar tus finanzas. Puedes enviarme mensajes como:\n"
        "• _'15€ en Gasolina y 40€ en Supermercado'_\n"
        "• _'He cobrado la nómina de 2100 euros'_\n\n"
        "Registraré todo en tu Google Sheets automáticamente.",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador principal de la lógica de negocio"""
    raw_text = update.message.text
    
    # 1. Capa de Privacidad
    clean_text = sanitizer.clean(raw_text)

    # 2. Inferencia de IA
    # analysis_text: El mensaje amigable de Sentinel
    # items: Lista de movimientos O el string "DOUBT"
    analysis_text, items = brain.process_transaction(clean_text)

    # 3. Gestión de la Lógica de Registro
    status_msg = ""
    
    # CASO A: La IA tiene dudas
    if items == "DOUBT":
        status_msg = "\n\n🤔 *Necesito confirmación:* No he registrado nada para evitar errores. ¿Podrías ser más específico?"
        logger.info("Sentinel solicitó aclaración al usuario.")

    # CASO B: Hay movimientos para registrar
    elif sheets and isinstance(items, list) and len(items) > 0:
        exitos = 0
        for item in items:
            try:
                # Normalización final del importe
                clean_amount = item["importe"].replace(',', '.')
                
                if sheets.log_expense(item["concepto"], item["categoria"], clean_amount):
                    exitos += 1
            except Exception as e:
                logger.error(f"Fallo al registrar item {item}: {e}")

        if exitos > 0:
            status_msg = f"\n\n📊 *{exitos} movimiento(s) sincronizado(s) con Google Sheets.*"
        else:
            status_msg = "\n\n❌ *Error técnico al intentar escribir en el Excel.*"

    # CASO C: No se detectó nada procesable
    elif not items or len(items) == 0:
        status_msg = "\n\n⚠️ *No he detectado ningún gasto o ingreso válido en tu mensaje.*"

    # 4. Envío de Respuesta Final
    final_response = f"{analysis_text}{status_msg}"
    
    try:
        # Intentamos MarkdownV2 o Markdown estándar para formato rico
        await update.message.reply_text(final_response, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"Error de formato Markdown, enviando como texto plano: {e}")
        await update.message.reply_text(final_response)

if __name__ == '__main__':
    if not TOKEN:
        logger.error("No se encontró TELEGRAM_TOKEN. Revisa tu archivo .env")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Sentinel Operativo. Escuchando Telegram...")
    app.run_polling()