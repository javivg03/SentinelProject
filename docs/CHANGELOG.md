# 📋 CHANGELOG — Sentinel: AI-Powered Financial Auditor

Todos los cambios notables de este proyecto se documentan en este archivo.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

---

## [0.3.0] — 2026-05-02

### ✨ Añadido
- **Pipeline de ingestión de documentos bancarios**: El bot ahora acepta archivos Excel (`.xls`, `.xlsx`) y PDF adjuntados directamente en Telegram.
- **`document_parser.py`**: Nuevo módulo que extrae el texto crudo de documentos bancarios usando `pdfplumber` (PDFs de Trade Republic) y `pandas + xlrd` (Excel .xls de Unicaja, formato binario 97-2003).
- **`SentinelBrain.process_raw_document()`**: Nuevo método en `brain.py` que envía el texto crudo completo a Gemini AI en modo "Lector de Documentos Bancarios" para extraer todas las transacciones de golpe.
- **Conciencia de fechas en Google Sheets**: `SheetsConnector` ahora usa el campo `fecha` (`YYYY-MM`) devuelto por Gemini para escribir cada gasto en la columna del mes correcto, en lugar de usar siempre el mes actual.
- **Modo debug en Telegram**: El handler de documentos reporta ahora un preview de los primeros 300 caracteres extraídos y el resultado exacto de Gemini directamente en el chat, eliminando la necesidad de consultar los logs de Render para diagnosticar errores.
- **Detección de entorno**: El servidor web `aiohttp` solo se lanza cuando `RENDER_EXTERNAL_URL` está presente en el entorno, evitando el error `OSError: [Errno 10048]` al ejecutar en local.
- **`Tecnología`** añadida como nueva categoría de gasto en el `system_prompt.txt`.

### 🔧 Modificado
- **`system_prompt.txt`**: Prompts de categorización completamente reescritos con reglas de inferencia explícitas (Mercadona → Supermercado, Iberdrola → Electricidad + Gas, etc.) y formato JSON ampliado con campo `fecha`.
- **`SheetsConnector.batch_log_expenses()`**: Refactorizado para agrupar gastos por tupla `(mes_columna, fila_categoría)` en lugar de solo por categoría, permitiendo escritura multi-mes en una sola llamada API.
- **`SheetsConnector.log_expense()`**: Añadido parámetro opcional `fecha` para coherencia con el batch.
- **`requirements.txt`**: Añadidas dependencias `pdfplumber` y `xlrd` que faltaban para el despliegue en Render.
- **`sanitizer.py`**: Mejorado el patrón IBAN para cubrir todos los países europeos (no solo ES) y añadido patrón de teléfono español.
- **`main.py`**: Limpieza completa — eliminado import `BankConnector`, variables globales `global_bank` y `bank`, importaciones huérfanas. Añadido fix de codificación UTF-8 para consolas Windows.

### 🐛 Corregido
- **`UnicodeEncodeError`**: La consola de Windows crasheaba al intentar imprimir emojis en los logs. Solucionado con `sys.stdout.reconfigure(encoding='utf-8')` al arranque.
- **`OSError: [Errno 10048]`**: El servidor web fallaba en local porque el puerto 10000 ya estaba ocupado por una instancia anterior. Solucionado con detección de entorno.
- **`ModuleNotFoundError: pdfplumber`**: Librería instalada localmente pero ausente en `requirements.txt`, causando fallo de build en Render.
- **`telegram.error.Conflict`**: Dos instancias del bot (local + Render) compitiendo por el mismo token. Clarificado el flujo de trabajo: solo Render en producción.
- **Categorías no encontradas**: `Supermercado & común` no existía en el Sheet real (el nombre correcto es `Supermercado`). Sincronizadas todas las categorías del prompt con los valores exactos de la hoja.

---

## [0.2.0] — 2026-04-XX *(sesión anterior al formateo)*

### ✨ Añadido
- Integración inicial con Google Gemini AI para clasificación de gastos en lenguaje natural.
- Conexión a Google Sheets para registro automático de gastos.
- Sistema de historial de conversación para contexto multi-turno.
- `DataSanitizer`: limpieza de datos sensibles (IBAN, tarjetas, DNI, email) antes de enviar a APIs externas.

### ❌ Descartado
- Integración con **Tink API** (Open Banking): bloqueada por normativa PSD2 para usuarios individuales sin licencia AISP. Ver `docs/CHALLENGES.md` y `bank_connector.py` para el registro histórico completo.
- Comandos de Telegram `/conectar`, `/sincronizar`, `/activar_asesor`: eliminados por depender de la integración bancaria.

---

## [0.1.0] — 2026-01-XX *(versión inicial)*

### ✨ Añadido
- Estructura base del proyecto: `main.py`, `brain.py`, `sheets_connector.py`, `bank_connector.py`, `sanitizer.py`.
- Bot de Telegram funcional con polling.
- Primer intento de integración con Tink para lectura de movimientos bancarios en tiempo real.
