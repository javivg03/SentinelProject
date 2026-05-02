# 🛡️ Sentinel: AI-Powered Financial Auditor

Sentinel es un ecosistema de automatización financiera personal que integra la potencia de **Google Gemini AI** con la ubicuidad de **Telegram** y la flexibilidad de **Google Sheets**.

A diferencia de las aplicaciones de finanzas tradicionales, Sentinel utiliza **Procesamiento de Lenguaje Natural (NLP)** para permitir que el usuario registre sus movimientos financieros mediante lenguaje cotidiano, y un **pipeline de ingestión de documentos** para procesar masivamente los extractos bancarios exportados desde la app del banco.

---

## 🌟 Características Principales

- **Comprensión Contextual**: Procesa mensajes complejos como _"He cobrado la nómina y me he gastado 12€ en gasolina"_ en una sola interacción, manteniendo historial de conversación para completar información incompleta.
- **Categorización Inteligente**: Motor de IA (Gemini 2.5 Flash) configurado para mapear entradas de usuario y conceptos bancarios contra un presupuesto estructurado preexistente, con reglas de inferencia explícitas.
- **Ingestión de Documentos Bancarios (Anti-PSD2)**: El bot acepta archivos Excel (`.xls`, `.xlsx`) y PDF adjuntados directamente en Telegram. Procesa masivamente extractos de meses completos sin depender de conexiones bancarias directas bloqueadas por la normativa PSD2.
- **Conciencia de Fechas**: Cada transacción se registra en la columna del mes que le corresponde según su fecha real, no según el mes actual.
- **Escritura Atómica en Google Sheets**: El sistema no solo anota; busca la intersección exacta entre Categoría y Mes, acumulando valores con una sola llamada API por lote (batch writing).
- **Seguridad "Zero-Trust"**: Sanitización de datos sensibles (IBAN, DNI, tarjetas, teléfonos) antes de que la información salga del servidor hacia las APIs de terceros. Los archivos bancarios se eliminan del disco inmediatamente tras su procesamiento.
- **Soporte Multi-banco**: Compatible con el formato `.xls` de **Unicaja** y el PDF de **Trade Republic**. Arquitectura extensible para nuevos bancos.

---

## ⚠️ Contexto: Por qué no usamos Open Banking (PSD2)

El proyecto comenzó con la intención de conectarse directamente a los bancos en tiempo real mediante APIs de Open Banking (Tink, GoCardless). Esta integración fue bloqueada por la **normativa europea PSD2**, que requiere una licencia AISP (Account Information Service Provider) — reservada a entidades financieras reguladas — para acceder a datos bancarios reales de terceros. El módulo `bank_connector.py` se conserva como testimonio del trabajo realizado y la comprensión de la normativa. Ver `docs/CHALLENGES.md` para el análisis técnico completo.

---

## 🛠️ Stack Tecnológico

- **Core**: Python 3.12
- **IA**: Google Gemini 2.5 Flash (NLP Engine)
- **Interface**: Telegram Bot API (vía `python-telegram-bot` v20+)
- **Infraestructura Cloud**: Google Cloud Platform (Sheets & Drive APIs)
- **Despliegue**: Web Service en Render (24/7 Uptime, auto-deploy desde GitHub)
- **Parsing de documentos**: `pdfplumber` (PDF), `pandas + xlrd` (Excel .xls)

---

## 📁 Estructura del Proyecto

```
SentinelProject/
├── main.py                  # Orquestador principal (Telegram bot)
├── brain.py                 # Motor de IA (interfaz con Gemini)
├── sheets_connector.py      # Conector de Google Sheets
├── document_parser.py       # Extractor de Excel y PDF bancarios
├── sanitizer.py             # Filtro de datos sensibles (Zero-Trust)
├── bank_connector.py        # ⚠️ DEPRECATED — Registro histórico de integración PSD2
├── requirements.txt         # Dependencias del proyecto
├── .env                     # Secretos locales (NO subir a Git)
├── service_account.json     # Credenciales Google (NO subir a Git)
├── prompts/
│   └── system_prompt.txt    # Instrucciones del sistema para Gemini AI
└── docs/
    ├── ARCHITECTURE.md      # Diagrama y descripción de módulos
    ├── CHANGELOG.md         # Historial de cambios por versión
    └── CHALLENGES.md        # Retos técnicos y cómo se resolvieron
```

---

## 🚀 Inicio Rápido en 4 Pasos

### 1. Clonar e instalar dependencias

```bash
git clone https://github.com/javivg03/SentinelProject.git
cd SentinelProject
python -m venv .venv
.\.venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 2. Configurar secretos locales

Crea un archivo `.env` en la raíz del proyecto:

```env
TELEGRAM_TOKEN=tu_token_de_botfather
GOOGLE_API_KEY=tu_api_key_de_google_ai_studio
SPREADSHEET_ID=el_id_de_tu_google_sheet
```

Descarga tu `service_account.json` desde Google Cloud Console y colócalo en la raíz del proyecto.

### 3. Configurar Google Sheets

Tu hoja debe tener:
- **Hoja llamada `Presupuesto`**
- **Fila 1**: Cabecera con los meses (`Enero`, `Febrero`, ..., `Diciembre`)
- **Columna A**: Nombres de categorías exactos (ver `prompts/system_prompt.txt`)
- La cuenta de servicio debe tener permisos de editor en el documento

### 4. Ejecutar en local (desarrollo)

```bash
python main.py
```

> ⚠️ **No ejecutar en local si Render está activo.** Dos instancias del mismo bot causan `telegram.error.Conflict`.

---

## ☁️ Despliegue en Render (Producción)

1. Conecta tu repositorio de GitHub a Render
2. Crea un **Web Service** con comando de inicio: `python main.py`
3. Añade las siguientes **Environment Variables** en el panel de Render:
   - `TELEGRAM_TOKEN`
   - `GOOGLE_API_KEY`
   - `SPREADSHEET_ID`
   - `GOOGLE_SERVICE_ACCOUNT_JSON` (contenido completo del JSON de la cuenta de servicio)
   - `RENDER_EXTERNAL_URL` (Render la añade automáticamente)
4. Activa **Auto-Deploy** para que cada `git push` actualice el bot automáticamente

---

## 📚 Documentación

- [Arquitectura del Sistema](docs/ARCHITECTURE.md)
- [Historial de Cambios](docs/CHANGELOG.md)
- [Retos Técnicos y Soluciones](docs/CHALLENGES.md)

---

Desarrollado con 💙 como herramienta de auditoría financiera inteligente y proyecto de portfolio.
