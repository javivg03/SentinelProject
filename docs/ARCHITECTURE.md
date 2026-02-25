# Arquitectura del Sistema: Sentinel

La arquitectura de Sentinel sigue el patrón de **Diseño Modular**, separando la responsabilidad de comunicación, procesamiento e integración de datos.

## 🔄 Flujo de Datos (Pipeline)

1. **Ingesta (Telegram)**: El usuario envía un mensaje no estructurado.
2. **Sanitización (`sanitizer.py`)**: Se filtran posibles datos sensibles o inyecciones de código.
3. **Inferencia (`brain.py`)**: 
   - Se inyecta el *System Prompt* (Contexto Financiero).
   - Gemini extrae entidades (Concepto, Importe, Categoría).
   - Se formulan múltiples objetos si el mensaje es compuesto.
4. **Integración (`sheets_connector.py`)**: 
   - Localización dinámica de celdas por coincidencia de strings (Categoría) e índice temporal (Mes actual).
   - Operación de lectura-suma-escritura para mantener la integridad del presupuesto.
5. **Confirmación**: El bot devuelve un resumen visual al usuario con el estado del registro.

## 🛡️ Capa de Seguridad

- **Variables de Entorno**: Uso estricto de `.env` para evitar fugas de credenciales en Git.
- **Service Accounts**: Acceso restringido vía IAM a Google Cloud, limitando el alcance del bot solo a los documentos necesarios.