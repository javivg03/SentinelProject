import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from sanitizer import DataSanitizer
from brain import SentinelBrain
from sheets_connector import SheetsConnector
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import time
import socket

# Servidor mínimo para pasar el Health Check de Hugging Face
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sentinel is active")

def run_health_check():
    server = HTTPServer(('0.0.0.0', 7860), HealthCheckHandler)
    server.serve_forever()

# Iniciamos el servidor en un hilo secundario
threading.Thread(target=run_health_check, daemon=True).start()

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
        # DEJAMOS status_msg VACÍO. 
        # ¿Por qué? Porque la IA ya ha escrito un mensaje de duda muy bueno (analysis_text).
        # No hace falta que el código añada nada más.
        status_msg = "" 
        logger.info("Sentinel (IA) solicitó aclaración.")

    # CASO B: Hay movimientos (Lista con datos)
    elif sheets and isinstance(items, list) and len(items) > 0:
        exitos = 0
        for item in items:
            try:
                clean_amount = item["importe"].replace(',', '.')
                if sheets.log_expense(item["concepto"], item["categoria"], clean_amount):
                    exitos += 1
            except Exception as e:
                logger.error(f"Error: {e}")

        if exitos > 0:
            # Aquí SÍ añadimos mensaje porque la IA no sabe si el Excel se guardó bien
            status_msg = f"\n\n📊 *{exitos} movimiento(s) sincronizado(s).*"

    # CASO C: La IA no devuelve nada (Mensajes de charla, "gracias", "olvídalo")
    else:
        # Si no hay items y no es una DUDA, es que es charla normal.
        # No ponemos "⚠️ No he detectado nada" para no ser pesados.
        status_msg = "" 
        logger.info("Mensaje de cortesía o sin datos financieros.")

    # 4. Envío de Respuesta Final
    final_response = f"{analysis_text}{status_msg}"
    
    try:
        # Intentamos MarkdownV2 o Markdown estándar para formato rico
        await update.message.reply_text(final_response, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"Error de formato Markdown, enviando como texto plano: {e}")
        await update.message.reply_text(final_response)

def check_network():
    """Espera hasta que api.telegram.org sea alcanzable"""
    logger.info("🌐 Comprobando conexión a internet...")
    while True:
        try:
            # Intentamos resolver el dominio de Telegram
            socket.gethostbyname('api.telegram.org')
            logger.info("✅ Red lista. Conectando con Telegram...")
            return True
        except socket.gaierror:
            logger.warning("⏳ Esperando a que el DNS de Hugging Face despierte...")
            time.sleep(5)

if __name__ == "__main__":
    # 1. Esperamos a que la red sea real
    check_network()
    
    # 2. Arrancamos el servidor de salud (Hugging Face)
    threading.Thread(target=run_health_check, daemon=True).start()

    # 3. Configuramos el bot con tiempos de espera más largos
    # Esto evita que se rinda si la conexión es inestable al inicio
    try:
        logger.info("🚀 Sentinel Operativo. Escuchando Telegram...")
        app.run_polling(
            connect_timeout=60,
            read_timeout=60,
            write_timeout=60,
            pool_timeout=60,
            drop_pending_updates=True
        )
    except Exception as e:
        logger.error(f"💥 Error crítico en el bot: {e}")
        # Esperamos un poco y salimos para que el contenedor se reinicie solo
        time.sleep(10)