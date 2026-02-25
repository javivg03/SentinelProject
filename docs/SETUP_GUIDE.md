# Guía de Configuración Completa

## 1. Configuración de Google Cloud
- Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/).
- Habilita las APIs de **Google Sheets** y **Google Drive**.
- Crea una **Service Account**, descarga el archivo JSON y renombralo a `service_account.json`.
- **IMPORTANTE**: Abre tu hoja de Google Sheets y comparte el acceso de "Editor" con el email de la Service Account.

## 2. Configuración del Bot de Telegram
- Habla con `@BotFather` en Telegram y crea un nuevo bot para obtener tu `API_TOKEN`.

## 3. Configuración de Gemini AI
- Obtén tu API Key desde [Google AI Studio](https://aistudio.google.com/).

## 4. Archivo de Entorno (.env)
Crea un archivo `.env` con este formato:
```env
TELEGRAM_TOKEN=tu_token_aqui
GOOGLE_API_KEY=tu_key_de_gemini