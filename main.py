import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector

# Configuración de Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Instancias globales
sanitizer = DataSanitizer()
brain = SentinelBrain()

# Inicialización de Sheets
try:
    sheets = SheetsConnector()
    logging.info("✅ Conexión con Google Sheets lista.")
except Exception as e:
    logging.error(f"⚠️ Google Sheets no disponible: {e}")
    sheets = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida"""
    await update.message.reply_text(
        "🛡️ **Sentinel Activado**\n\n"
        "Hola. Soy tu auditor financiero. Envíame tus movimientos (gastos, ingresos o inversiones) "
        "y los registraré en tu presupuesto en tiempo real."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador de mensajes proactivos"""
    raw_text = update.message.text
    
    # 1. Seguridad: Limpieza de datos sensibles
    clean_text = sanitizer.clean(raw_text)

    # 2. IA: Obtener análisis visual y lista de movimientos extraídos
    # Ahora 'items' es una LISTA de diccionarios
    analysis_text, items = brain.process_transaction(clean_text)

    # 3. Registro en Excel: Bucle para procesar cada movimiento detectado
    status_msg = ""
    if sheets and items:
        exitos = 0
        for item in items:
            try:
                # Normalizamos el importe para Python/Excel
                clean_amount = item["importe"].replace(',', '.')
                
                # Intentamos registrar en la celda correspondiente
                if sheets.log_expense(item["concepto"], item["categoria"], clean_amount):
                    exitos += 1
            except Exception as e:
                logging.error(f"Error procesando item {item}: {e}")

        if exitos > 0:
            # Mensaje neutro: sirve para ingresos y gastos
            status_msg = f"\n\n✅ *{exitos} movimiento(s) registrado(s) en el Presupuesto*"
    
    elif not items:
        status_msg = "\n\n⚠️ *No he podido extraer datos válidos para el registro.*"

    # 4. Respuesta Final al usuario
    try:
        # Intentamos Markdown para que los emojis y negritas luzcan bien
        await update.message.reply_text(f"{analysis_text}{status_msg}", parse_mode='Markdown')
    except Exception:
        # Fallback si el Markdown de la IA tiene caracteres especiales que rompen Telegram
        await update.message.reply_text(f"{analysis_text}{status_msg}")

if __name__ == '__main__':
    if not TOKEN:
        exit("Error: No se encontró el TELEGRAM_TOKEN en el archivo .env")

    app = ApplicationBuilder().token(TOKEN).build()
    
    # Comandos
    app.add_handler(CommandHandler("start", start))
    
    # Mensajes de texto (excluyendo comandos)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Sentinel Operativo y conectado a la nube...")
    app.run_polling()