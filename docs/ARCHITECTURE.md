# 🏗️ ARQUITECTURA — Sentinel: AI-Powered Financial Auditor

## Visión General

Sentinel es un sistema de auditoría financiera personal compuesto por módulos desacoplados que se comunican entre sí a través de interfaces bien definidas. El punto de entrada del usuario es siempre **Telegram**.

---

## Diagrama de Flujo

```
┌─────────────┐     texto / archivo     ┌─────────────────────────┐
│   USUARIO   │ ──────────────────────► │  Telegram Bot (main.py) │
│  (Telegram) │ ◄────────────────────── │  Handler de mensajes    │
└─────────────┘    respuesta formateada └──────────┬──────────────┘
                                                   │
                          ┌────────────────────────┤
                          │                        │
                   archivo adjunto           texto natural
                          │                        │
                          ▼                        ▼
              ┌───────────────────┐    ┌───────────────────────┐
              │ document_parser   │    │  DataSanitizer        │
              │ .py               │    │  (sanitizer.py)       │
              │ - parse_pdf()     │    │  Elimina: IBAN, DNI,  │
              │ - parse_excel()   │    │  tarjetas, emails,    │
              └────────┬──────────┘    │  teléfonos            │
                       │              └──────────┬────────────┘
                       │ texto crudo             │ texto limpio
                       └──────────┬──────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │     SentinelBrain       │
                    │      (brain.py)         │
                    │                         │
                    │  process_transaction()  │  ← texto natural
                    │  process_raw_document() │  ← extracto bancario
                    │                         │
                    │  Modelo: Gemini 2.5     │
                    │  Flash (Google AI)      │
                    └──────────┬──────────────┘
                               │ JSON estructurado
                               │ {movimientos: [{concepto,
                               │   categoria, importe,
                               │   fecha, tipo}]}
                               ▼
                    ┌─────────────────────────┐
                    │   SheetsConnector       │
                    │  (sheets_connector.py)  │
                    │                         │
                    │  log_expense()          │  ← 1 transacción
                    │  batch_log_expenses()   │  ← lote masivo
                    │                         │
                    │  Autenticación dual:    │
                    │  - Local: .json file    │
                    │  - Cloud: env variable  │
                    └──────────┬──────────────┘
                               │ API call (gspread)
                               ▼
                    ┌─────────────────────────┐
                    │   Google Sheets         │
                    │  "Presupuesto"          │
                    │                         │
                    │  Columnas: Meses (B-M)  │
                    │  Filas: Categorías      │
                    │  Escritura batch (1     │
                    │  llamada API por lote)  │
                    └─────────────────────────┘
```

---

## Módulos del Sistema

### `main.py` — Orquestador Principal
Punto de entrada del bot. Gestiona el ciclo de vida de la aplicación (Telegram polling) y enruta los mensajes al handler correspondiente.

- **`handle_message()`**: Maneja texto natural del usuario.
- **`handle_document()`**: Maneja archivos adjuntos (Excel/PDF).
- **`run_web_server()`**: Mini-servidor HTTP para el health check de Render. Solo activo en producción (cuando `RENDER_EXTERNAL_URL` está definido).

### `document_parser.py` — Extractor de Documentos
Módulo sin estado que convierte archivos bancarios en texto plano procesable por la IA.

- **Unicaja** (`.xls`): Usa `pandas` con motor `xlrd` para archivos Excel binarios formato 97-2003. Elimina filas/columnas vacías antes de serializar a CSV.
- **Trade Republic** (`.pdf`): Usa `pdfplumber` para extraer texto página a página.

### `brain.py` — Motor de Inteligencia Artificial
Interfaz con la API de Google Gemini. Gestiona reintentos automáticos (hasta 3 intentos con backoff exponencial via `tenacity`).

- **`process_transaction()`**: Para mensajes de texto. Incluye contexto de historial de conversación.
- **`process_raw_document()`**: Para extractos bancarios. Envía el texto crudo completo con instrucciones específicas de extracción.
- **`process_batch_transactions()`**: Para listas pre-procesadas de transacciones.
- **`evaluate_spending()`**: Análisis proactivo de gastos contra perfil histórico (preparado para uso futuro).

### `sheets_connector.py` — Conector de Google Sheets
Gestiona la autenticación y escritura en el libro de presupuesto.

- **Autenticación dual**: Lee de `service_account.json` en local; de la variable de entorno `GOOGLE_SERVICE_ACCOUNT_JSON` en Render.
- **`_get_month_col()`**: Traduce una fecha `YYYY-MM` al número de columna del mes en el Sheet.
- **`batch_log_expenses()`**: Agrupa gastos por tupla `(columna_mes, fila_categoría)` y realiza **una sola escritura masiva** via `sheet.update_cells()`, minimizando el consumo de cuota de la API.

### `sanitizer.py` — Filtro de Privacidad (Zero-Trust)
Elimina datos personales sensibles antes de que salgan del servidor hacia APIs de terceros.

Patrones detectados y redactados como `[REDACTED:TIPO]`:
| Tipo | Patrón |
|---|---|
| IBAN | Cualquier IBAN europeo (`XX00...`) |
| Tarjeta de crédito | Grupos de 4 dígitos separados |
| Email | Dirección de correo estándar |
| DNI | 8 dígitos + letra |
| Teléfono | Números móviles españoles (+34, 6xx, 7xx) |

---

## Entorno de Despliegue

### Producción (Render)
- **Tipo**: Web Service (Python)
- **Inicio**: `python main.py`
- **Variables de entorno**: configuradas en el panel de Render (ver `.env.example`)
- **Auto-deploy**: Activado — cada `git push` a `main` desencadena un nuevo despliegue automático (~3-5 min)
- **Health check**: El servidor `aiohttp` en puerto `$PORT` responde `200 OK` en `/` para que Render sepa que el proceso está vivo

### Desarrollo Local
- **Entorno virtual**: `.venv/` (Python 3.12)
- **Activación**: `.\.venv\Scripts\activate`
- **⚠️ IMPORTANTE**: No ejecutar en local mientras Render esté activo. Dos instancias del mismo bot causan `telegram.error.Conflict`.

---

## Seguridad

| Medida | Implementación |
|---|---|
| Secretos nunca en código | Variables de entorno via `.env` + `.gitignore` |
| Credenciales Google nunca en repo | `service_account.json` en `.gitignore` |
| Datos sensibles nunca a la IA | `DataSanitizer` filtra antes de cada llamada a Gemini |
| Archivos bancarios borrados al instante | `os.remove(local_path)` tras el procesamiento |
| Política Zero-Trust | Sin almacenamiento permanente de datos financieros del usuario |