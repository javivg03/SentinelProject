# Desafíos Técnicos y Soluciones

Durante el desarrollo de Sentinel, se abordaron y resolvieron retos críticos de integración:

### 1. El Conflicto de Formato .xlsx vs Native Sheets (Error 400)
**Reto**: La API de Google Sheets devolvía errores de compatibilidad al intentar escribir en archivos subidos directamente desde Excel.  
**Solución**: Se implementó un protocolo de conversión a formato nativo de Google e identificación por `ID único (Key)` en lugar de nombres de archivo, eliminando la ambigüedad en la búsqueda de documentos en el Drive.

### 2. Integridad de los Sumatorios (Tipado de Datos)
**Reto**: Las celdas de Google Sheets a menudo contenían formatos de moneda (20,00€) que Python interpretaba como strings, rompiendo las fórmulas de suma.  
**Solución**: Se desarrolló un motor de limpieza (`_clean_value`) que normaliza cualquier entrada de celda a un `Float` operable antes de realizar cálculos matemáticos, asegurando que las fórmulas de "Total" del Excel siempre reciban datos numéricos puros.

### 3. Procesamiento Multitarea
**Reto**: Los usuarios tienden a enviar listas de gastos en un solo mensaje.  
**Solución**: Refactorización del motor de IA para generar bloques delimitados y uso de expresiones regulares (Regex) en Python para iterar sobre cada movimiento, permitiendo actualizaciones múltiples en una sola petición.

### 4. Normativa PSD2 y Open Banking (Pivotaje Arquitectónico)
**Reto**: Inicialmente, se implementó una integración directa con APIs bancarias (Tink, GoCardless) para la lectura de movimientos en tiempo real. Sin embargo, la estricta **normativa europea PSD2** bloquea el acceso de aplicaciones de terceros a cuentas bancarias reales sin una licencia o costosas suscripciones empresariales.  
**Solución**: En lugar de abandonar la automatización, el proyecto pivotó hacia un sistema "Batch" vía Telegram. El usuario exporta los movimientos en formato Excel/CSV desde la app de su banco y se los envía al Bot. Sentinel procesa masivamente el documento, extrae las filas, las categoriza con IA y las inserta atómicamente en Google Sheets, sorteando el bloqueo de PSD2 de forma gratuita, universal y segura.