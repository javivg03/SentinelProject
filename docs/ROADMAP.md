# 🗺️ Sentinel - Hoja de Ruta (Roadmap)

Este documento recopila las ideas, mejoras y nuevas funcionalidades propuestas para futuras versiones del proyecto Sentinel, organizadas por prioridad e impacto.

---

## 🚀 Fase 2: Consolidación y Robustez (A corto/medio plazo)

### 1. Refactorización de Google Sheets (Fórmulas Automáticas)
- **Descripción**: Modificar la arquitectura actual para que la pestaña `Presupuesto` no dependa de sumas manuales hechas por el bot. En su lugar, el bot se limitará a volcar datos en `Transacciones`, y será el propio Excel el que calcule los totales mensuales usando fórmulas `SUMAR.SI` o `SUMAR.SI.CONJUNTO`.
- **Ventaja**: El usuario podrá borrar o modificar filas en `Transacciones` y el dashboard se actualizará solo. Otorga control total al usuario en caso de errores del bot.

### 2. Procesamiento de Fechas en Texto Natural (NLP)
- **Descripción**: Mejorar el prompt de Gemini para la introducción de gastos manuales para que entienda el contexto temporal. Si el usuario escribe *"Ayer me gasté 20€ en Zara"*, el bot debería calcular la fecha de ayer en lugar de usar el `datetime.now()`.
- **Ventaja**: Mayor flexibilidad para registrar gastos atrasados a mano sin tener que recurrir al Excel.

### 3. Teclado Interactivo para Dudas Manuales
- **Descripción**: Actualmente, el sistema de botones inline para confirmar la categoría solo se dispara cuando se sube un Excel masivo. Se debería portar esta funcionalidad a la entrada manual: si un gasto introducido por texto va a "Otros", el bot debería ofrecer la botonera en lugar de registrarlo a ciegas.

---

## 🔮 Fase 3: Inteligencia Financiera Avanzada (A largo plazo)

### 1. Conciliación Bancaria Interactiva (Enfoque YNAB)
- **Descripción**: Solución al problema de la duplicidad de transacciones. Cuando se procese un extracto bancario (Excel/PDF), el bot buscará gastos insertados manualmente en los últimos 3-5 días que coincidan exactamente en el importe. 
- **Flujo**: Si encuentra una coincidencia, enviará un mensaje por Telegram: *"❓ He encontrado un cargo de 15.00€ en el Excel (GASOLINERA X), pero tú registraste 15.00€ a mano hace dos días. ¿Es el mismo gasto?"*.
- **Ventaja**: Previene la duplicación de gastos y permite usar el bot tanto en modo "seguimiento manual diario" como en modo "conciliación a fin de mes".

### 2. Umbrales de Gasto Dinámicos (Aprendizaje Continuo)
- **Descripción**: Activar y refinar la función `calculate_dynamic_thresholds()` en `sheets_connector.py`. El bot analizará el histórico de gastos de meses anteriores para aprender cuánto suele gastar el usuario en "Ocio" o "Supermercado", y le enviará una alerta proactiva por Telegram si detecta que este mes se está desviando de su propia media.

### 3. Soporte Multi-Usuario / Multi-Cuenta
- **Descripción**: Preparar la base de datos (o la persistencia de Telegram) para mapear distintos `chat_id` a distintos documentos de Google Sheets. 
- **Ventaja**: Permitiría que el usuario comparta el bot con su pareja (cada uno con su propio Excel, o ambos apuntando al mismo Excel de gastos compartidos).
