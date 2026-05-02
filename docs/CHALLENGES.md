# Desafíos Técnicos y Soluciones

Durante el desarrollo de Sentinel, se abordaron y resolvieron retos críticos de integración:

---

### 1. El Conflicto de Formato .xlsx vs Native Sheets (Error 400)
**Reto**: La API de Google Sheets devolvía errores de compatibilidad al intentar escribir en archivos subidos directamente desde Excel.  
**Solución**: Se implementó un protocolo de conversión a formato nativo de Google e identificación por `ID único (Key)` en lugar de nombres de archivo, eliminando la ambigüedad en la búsqueda de documentos en el Drive.

---

### 2. Integridad de los Sumatorios (Tipado de Datos)
**Reto**: Las celdas de Google Sheets a menudo contenían formatos de moneda (20,00€) que Python interpretaba como strings, rompiendo las fórmulas de suma.  
**Solución**: Se desarrolló un motor de limpieza (`_clean_value`) que normaliza cualquier entrada de celda a un `Float` operable antes de realizar cálculos matemáticos, asegurando que las fórmulas de "Total" del Excel siempre reciban datos numéricos puros.

---

### 3. Procesamiento Multitarea
**Reto**: Los usuarios tienden a enviar listas de gastos en un solo mensaje.  
**Solución**: Refactorización del motor de IA para generar bloques delimitados, permitiendo actualizaciones múltiples en una sola petición a Gemini y escritura batch en Google Sheets.

---

### 4. Normativa PSD2 y Open Banking (Pivotaje Arquitectónico)
**Reto**: Inicialmente, se implementó una integración directa con APIs bancarias (Tink, GoCardless) para la lectura de movimientos en tiempo real. Sin embargo, la estricta **normativa europea PSD2** bloquea el acceso de aplicaciones de terceros a cuentas bancarias reales sin una licencia o costosas suscripciones empresariales.  
**Solución**: En lugar de abandonar la automatización, el proyecto pivotó hacia un sistema "Batch" vía Telegram. El usuario exporta los movimientos en formato Excel/CSV desde la app de su banco y se los envía al Bot. Sentinel procesa masivamente el documento, extrae las filas, las categoriza con IA y las inserta atómicamente en Google Sheets, sorteando el bloqueo de PSD2 de forma gratuita, universal y segura.

---

### 5. UnicodeEncodeError en Consola Windows (Emojis en Logs)
**Reto**: Al ejecutar el bot en Windows, la terminal crasheaba con `UnicodeEncodeError: 'charmap' codec can't encode character` cada vez que el código intentaba imprimir un emoji en los logs (ej: `🔑`, `✅`). La causa raíz es que PowerShell usa por defecto la codificación `cp1252` (Windows-1252), que no soporta Unicode completo.  
**Solución**: Se añadió al inicio de `main.py` la detección de plataforma y la reconfiguración explícita del stdout:
```python
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
```

---

### 6. Conflicto de Puerto en Desarrollo Local (OSError 10048)
**Reto**: El mini-servidor web `aiohttp` (necesario para el health check de Render) lanzaba `OSError: [Errno 10048] solo se permite un uso de cada dirección de socket` al intentar iniciar en local, porque el puerto `10000` ya estaba ocupado por una instancia anterior del bot.  
**Solución**: Se condicionó el arranque del servidor web a la presencia de la variable de entorno `RENDER_EXTERNAL_URL`. En local esa variable no existe, así que el servidor no arranca. En Render, sí existe y el health check funciona con normalidad.

---

### 7. Formatos Bancarios Heterogéneos (Excel .xls Antiguo vs PDF)
**Reto**: Unicaja exporta sus movimientos en formato `.xls` (Excel 97-2003, formato binario antiguo), no en el `.xlsx` moderno. La librería estándar `openpyxl` no lo soporta. Trade Republic solo permite exportar a PDF, no a CSV.  
**Solución**: Se instaló `xlrd >= 2.0.1` como motor alternativo de `pandas` para archivos `.xls`. Para los PDFs de Trade Republic se usa `pdfplumber`, que extrae el texto plano página por página. Se creó el módulo `document_parser.py` que detecta automáticamente la extensión y aplica el parser correcto.

---

### 8. Dependencias Ausentes en Despliegue (ModuleNotFoundError en Render)
**Reto**: Las librerías `pdfplumber` y `xlrd` se instalaron localmente en el `.venv` mediante un script de diagnóstico, pero nunca se añadieron al `requirements.txt`. Render instala exclusivamente las dependencias de ese archivo, por lo que el despliegue fallaba con `ModuleNotFoundError: No module named 'pdfplumber'`.  
**Solución**: Se añadieron explícitamente al `requirements.txt`. Regla de oro establecida: **toda librería instalada en local debe añadirse a `requirements.txt` inmediatamente**.

---

### 9. Gastos Volcados en el Mes Incorrecto (Sin Conciencia de Fecha)
**Reto**: Al procesar un extracto de enero-abril, todos los gastos se registraban en la columna de Mayo (mes actual). El código usaba `datetime.datetime.now().month` para determinar la columna de escritura, ignorando completamente la fecha real de cada transacción.  
**Solución**: Se modificó el `system_prompt.txt` para que Gemini devuelva un campo `"fecha": "YYYY-MM"` por cada transacción detectada. `SheetsConnector` usa ese campo para calcular la columna correcta mediante `_get_month_col()`. El método `batch_log_expenses()` fue refactorizado para agrupar los gastos por tupla `(columna_mes, fila_categoría)` antes de la escritura masiva.

---

### 10. Categorías del Prompt Desincronizadas con el Sheet Real
**Reto**: El `system_prompt.txt` usaba nombres de categoría que no coincidían exactamente con los de la columna A del Google Sheet (ej: `"Supermercado & común"` en el prompt vs `"Supermercado"` en el Sheet). Esto causaba que los gastos no encontraran su fila destino y se asignaran silenciosamente a `"Otros"`.  
**Solución**: Se leyó programáticamente la columna A del Sheet real con un script de diagnóstico y se sincronizaron exactamente los nombres en el prompt. También se añadió `"Tecnología"` que existía en el Sheet pero no en el prompt.