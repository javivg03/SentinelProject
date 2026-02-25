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