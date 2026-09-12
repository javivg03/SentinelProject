# 🛡️ Sentinel: AI-Powered Financial Auditor & Telegram Bot

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot-PTB%20v22-blue.svg)](https://python-telegram-bot.org/)
[![Google Gemini AI](https://img.shields.io/badge/AI%20Engine-Gemini%202.5%20Flash-orange.svg)](https://ai.google.dev/)
[![Google Sheets API](https://img.shields.io/badge/Storage-Google%20Sheets%20API-green.svg)](https://developers.google.com/sheets/api)
[![Render Deploy](https://img.shields.io/badge/Deploy-Render%20Web%20Service-black.svg)](https://render.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Sentinel** es un asistente financiero personal y auditor técnico para Telegram. Integra la capacidad de razonamiento y procesamiento de lenguaje natural de **Google Gemini AI** con la infraestructura analítica de **Google Sheets**, diseñado bajo principios rigurosos de **Privacidad por Diseño (Privacy by Design)**, **Zero-Trust** e **Integridad Determinista de Datos**.

El proyecto sustituye la fricción de los Excels manuales y los riesgos de las apps tradicionales mediante un flujo conversacional instantáneo: registra gastos en lenguaje natural, audita extractos bancarios masivos y responde consultas sobre presupuesto y patrimonio con **cero alucinaciones numéricas**.

---

## 🌟 Principios de Arquitectura e Ingeniería

### 1. Consultas Deterministas (Anti-Alucinación Financiera)
En finanzas personales, **una IA generativa nunca debe inventar, redondear o calcular cifras de forma no supervisada**. Sentinel implementa un patrón estricto de **Tool Calling / Function Dispatch**:
- **Gemini actúa únicamente como enrutador semántico**: clasifica la intención (`category_total`, `monthly_summary`, `patrimony`, `top_categories`) y extrae los parámetros (categoría, mes).
- **Python ejecuta la lectura determinista en Google Sheets**: accede a la celda exacta o al acumulado calculado por la hoja de cálculo.
- **Formateo controlado**: El bot inyecta la cifra real obtenida en la plantilla de respuesta de Telegram. Cero riesgo de alucinación.

### 2. Arquitectura de Registro Híbrido (Matriz + Auditoría)
Para mantener la simplicidad analítica sin perder trazabilidad:
- **Matriz Mensual (`📊 Registro Mensual`)**: El bot acumula el gasto en la celda correspondiente a `(Categoría, Mes)`. Todas las fórmulas de la hoja (`Total Gastos Vitales`, `Total Ocio`, `Ahorro Neto`, `Tasa de Ahorro`) se recalculan de forma nativa e inmediata en Google Drive.
- **Log de Auditoría (`Transacciones`)**: En paralelo, cada movimiento individual se anota con `[Fecha, Concepto, Categoría, Importe, Tipo]` para conservar el histórico detallado.

### 3. Patrimonio Desacoplado y Resiliente
- La pestaña **`🏦 Patrimonio y Objetivos`** se calcula al 100% mediante fórmulas nativas de Google Sheets enlazadas al histórico mensual.
- **El bot nunca escribe en Patrimonio**: reduce la superficie de fallo, garantiza que los datos perduren aunque el bot esté inactivo y evita que un error de software corrompa el cálculo patrimonial.

### 4. Privacidad por Diseño (Zero-Trust & Sanitización)
Diseñado con formación en Derecho, Ciberseguridad y Protección de Datos:
- **Data Sanitizer**: Antes de enviar cualquier mensaje o documento a la API de Gemini, un filtro regex redacta de forma irreversible datos sensibles como IBANs, números de tarjetas de crédito, correos electrónicos, DNIs y números de teléfono (`[REDACTED]`).
- **Eliminación Efímera**: Los extractos bancarios subidos en Telegram se procesan en memoria / directorio temporal y se destruyen inmediatamente tras su inserción en Google Sheets.
- **Gestión de Secretos**: Ninguna credencial o clave vive en el código fuente; todo se inyecta por variables de entorno y archivos ignorados en git.

### 5. Alta Disponibilidad y Mitigación del Cold-Start
- En la capa gratuita de hosting (Render), los contenedores hibernan tras 15 minutos de inactividad.
- Sentinel expone un endpoint HTTP de salud (`GET /`) gestionado con `aiohttp` y cuenta con un **sistema keep-alive dual** (cron periódico cada 10 minutos vía `cron-job.org` y flujo de trabajo en **GitHub Actions**) que mantiene el bot despierto 24/7 con tiempos de respuesta en Telegram inferiores a 2 segundos.

---

## 🛠️ Stack Tecnológico

| Componente | Tecnología | Rol |
|---|---|---|
| **Lenguaje** | Python 3.11 / 3.12 | Lógica del sistema y motor asíncrono |
| **Motor de IA** | Google Gemini 2.5 Flash (`google-genai` SDK) | Clasificación de intenciones, extracción de entidades y parsing de tickets |
| **Interfaz de Usuario** | Telegram Bot API (`python-telegram-bot` v22) | Entrada de mensajes, teclado interactivo inline y notificaciones |
| **Servidor HTTP** | `aiohttp` | Gestión del webhook de Telegram y health check keep-alive |
| **Almacenamiento** | Google Sheets API (`gspread` + Service Account) | Base de datos analítica matricial y log de transacciones |
| **Ingestión Bancaria** | `pdfplumber`, `pandas`, `openpyxl`, `xlrd` | Extracción de datos de extractos en PDF y Excel binarios |
| **Resiliencia** | `tenacity` | Reintentos automáticos con retroceso exponencial ante rate limits de API |
| **CI / CD** | GitHub Actions & Render Web Service | Despliegue continuo automatizado y monitor de keep-alive |

---

## 📁 Estructura del Repositorio

```text
SentinelProject/
├── .github/
│   └── workflows/
│       └── keep_alive.yml       # Ping programado cada 10 min para evitar cold-start
├── prompts/
│   ├── system_prompt.txt        # Reglas de categorización e inferencia para Gemini
│   └── query_prompt.txt         # Clasificador estructurado de intenciones y parámetros
├── tests/
│   ├── test_brain.py            # Tests de inferencia de IA y formato determinista
│   ├── test_sanitizer.py        # Tests del filtro de datos personales (Zero-Trust)
│   └── test_sheets_logic.py     # Tests de normalización y parsing de moneda europea
├── main.py                      # Orquestador principal, webhook y handlers de Telegram
├── brain.py                     # Interfaz con Gemini y formateador de consultas
├── sheets_connector.py          # Conector matricial y determinista de Google Sheets
├── sanitizer.py                 # Sanitizador de privacidad (IBAN, DNI, tarjetas)
├── document_parser.py           # Parser de extractos bancarios (.xls, .xlsx, .pdf)
├── bank_connector.py            # ⚠️ Histórico: análisis normativo PSD2 / Open Banking
├── requirements.txt             # Dependencias del proyecto
├── Dockerfile                   # Contenedor para despliegue en Render
└── docs/
    ├── ARCHITECTURE.md          # Diagramas de flujo y arquitectura detallada
    ├── CHANGELOG.md             # Histórico de versiones
    └── CHALLENGES.md            # Desafíos técnicos (PSD2, límites de cuota, encoding)
```

---

## 🚀 Puesta en Marcha Local

### 1. Clonar el repositorio y configurar el entorno
```bash
git clone https://github.com/javivg03/SentinelProject.git
cd SentinelProject
python -m venv .venv
.\.venv\Scripts\activate       # En Windows
pip install -r requirements.txt
```

### 2. Configurar variables de entorno
Crea un archivo `.env` en la raíz del proyecto (basado en `.env.example`):
```env
TELEGRAM_TOKEN=tu_token_de_telegram_botfather
GOOGLE_API_KEY=tu_api_key_de_google_ai_studio
SPREADSHEET_ID=id_del_google_sheet
```

Coloca tu archivo `service_account.json` (cuenta de servicio con permisos de Editor en el Sheet) en la raíz del proyecto.

### 3. Ejecutar suite de pruebas
```bash
pytest
```

### 4. Iniciar el bot en modo local (Polling)
```bash
python main.py
```
*(Si no se define `RENDER_EXTERNAL_URL`, el bot arranca automáticamente en modo Polling sin necesidad de configurar webhook).*

---

## 💬 Ejemplos de Interacción

### Registro de Gastos
- **Usuario**: *"20€ en gasolina hoy"*
- **Sentinel**:
  > 💰 **Gasolina**
  > 🏷️ Gasolina (Septiembre)
  > 📉 20.00€ (acumulado mes: 60.00€)
  > ✅ Movimiento registrado en matriz y log.

### Consulta de Categoría
- **Usuario**: *"¿Cuánto llevo gastado en gasolina este mes?"*
- **Sentinel**:
  > 📊 **Gasto en Gasolina (Septiembre):** `60,00€`
  > 🎯 *Presupuesto asignado: 110,00€ (55% consumido)*

### Consulta de Patrimonio
- **Usuario**: *"¿Cuál es mi patrimonio actual?"*
- **Sentinel**:
  > 🏦 **Patrimonio Total (Agosto):** `7.928,55€`
  >
  > • 🔒 **Cuenta Remunerada TR (2%):** 5.213,21€
  > • 📈 **Fondo Fidelity MSCI World:** 1.541,92€
  > • ₿ **Bitcoin (TR):** 218,60€
  > • 💳 **Cuenta Unicaja (operativa):** 954,82€

---

## 📄 Licencia

Distribuido bajo la Licencia MIT. Consulta `LICENSE` para más información.
