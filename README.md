# 🛡️ Sentinel: AI-Powered Financial Auditor

Sentinel es un ecosistema de automatización financiera personal que integra la potencia de **Google Gemini AI** con la ubicuidad de **Telegram** y la flexibilidad de **Google Sheets**. 

A diferencia de las aplicaciones de finanzas tradicionales, Sentinel utiliza **Procesamiento de Lenguaje Natural (NLP)** para permitir que el usuario registre sus movimientos financieros mediante lenguaje cotidiano, encargándose de la categorización, el cálculo atómico y la actualización de presupuestos anuales de forma autónoma.

---

## 🌟 Características Principales

* **Comprensión Contextual**: Capacidad para procesar mensajes complejos como *"He cobrado la nómina y me he gastado 12€ en gasolina"* en una sola interacción.
* **Categorización Inteligente**: Motor de IA configurado para mapear entradas de usuario contra un presupuesto estructurado preexistente sin errores de formato.
* **Escritura Atómica en Google Sheets**: El sistema no solo anota; busca la intersección exacta entre Categoría y Mes, actualizando valores acumulados en tiempo real.
* **Seguridad "Zero-Trust"**: Sanitización de datos sensibles antes de que la información salga del servidor local hacia las APIs de terceros.
* **Feedback Proactivo**: Sentinel no solo registra; actúa como un auditor devolviendo consejos financieros basados en el gasto realizado.

## 🛠️ Stack Tecnológico

* **Core**: Python 3.10+
* **IA**: Google Gemini Pro/Flash (NLP Engine)
* **Interface**: Telegram Bot API (vía `python-telegram-bot`)
* **Infraestructura Cloud**: Google Cloud Platform (Sheets & Drive APIs)
* **Autenticación**: OAuth 2.0 con Cuentas de Servicio.

## 🚀 Inicio Rápido en 3 Pasos

### 1. Clonación y Dependencias
Primero, clona el repositorio e instala las librerías necesarias:
```bash
git clone [https://github.com/tu_usuario/sentinel-bot.git](https://github.com/tu_usuario/sentinel-bot.git)
cd sentinel-bot
pip install -r requirements.txt
```

### 2. Configuración de Secretos
* Crea un archivo `.env` en la raíz del proyecto y añade tus credenciales:
    ```env
    TELEGRAM_TOKEN=tu_token_aquí
    GOOGLE_API_KEY=tu_api_key_de_gemini
    ```
* Coloca tu archivo `service_account.json` (obtenido de Google Cloud) en la carpeta raíz del proyecto.

### 3. Ejecutar
Una vez configurados los secretos, inicia el orquestador principal:
```bash
python main.py