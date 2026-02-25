# 🛡️ Sentinel: Asistente Financiero Inteligente

Sentinel es un bot de Telegram potenciado por Inteligencia Artificial (Google Gemini) diseñado para automatizar el registro de finanzas personales directamente en Google Sheets.

## 🚀 Características

- **Procesamiento de Lenguaje Natural**: Envía mensajes como "15€ en gasolina y 20€ en comida" y Sentinel los entenderá.
- **Categorización Automática**: Clasifica gastos e ingresos según un presupuesto predefinido.
- **Integración con Google Sheets**: Actualiza celdas específicas en tiempo real mediante la API de Google.
- **Privacidad y Seguridad**: Sanitización de datos sensibles antes de ser procesados por la IA.
- **Soporte Multitarea**: Capacidad para procesar múltiples movimientos en un solo mensaje.

## 🛠️ Tecnologías Utilizadas

- **Lenguaje**: Python 3.10+
- **IA**: Google Gemini Flash API
- **Bot Platform**: python-telegram-bot
- **Base de Datos/Dashboard**: Google Sheets API (gspread)
- **Seguridad**: Regex para sanitización de datos y variables de entorno.

## 📋 Estructura del Proyecto

- `main.py`: Punto de entrada y orquestador del bot.
- `brain.py`: Lógica de integración con Gemini y extracción de datos.
- `sheets_connector.py`: Conexión y "cirugía" de celdas en Google Sheets.
- `sanitizer.py`: Filtro de seguridad para datos sensibles.
- `prompts/`: Instrucciones de personalidad y reglas del sistema.

## 🔧 Instalación y Configuración

1. Clonar el repositorio.
2. Crear un entorno virtual: `python -m venv venv`.
3. Instalar dependencias: `pip install -r requirements.txt`.
4. Configurar el archivo `.env` con tus credenciales.
5. Colocar tu `service_account.json` de Google Cloud en la raíz.
6. Ejecutar: `python main.py`.
s
---
*Proyecto desarrollado por Javier Villaseñor García como parte de un sistema de automatización financiera personal.*