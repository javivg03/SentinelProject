import os
import json
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()


class SentinelBrain:
    """
    Motor de Inteligencia Artificial de Sentinel.

    Interfaz con Google Gemini que gestiona dos flujos principales:
    1. Clasificación de intención (log / query / analysis)
    2. Procesamiento de transacciones (texto natural o documentos bancarios)

    Todos los métodos públicos devuelven tuplas (resultado, status) excepto
    classify_intent(), que devuelve un dict directamente.
    """

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ ERROR: No se encontró GOOGLE_API_KEY en el entorno.")

        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash"
        self.prompts_dir = "prompts"

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODOS PRIVADOS — Infraestructura interna
    # ─────────────────────────────────────────────────────────────────────────

    def _load_prompt(self, filename: str) -> str:
        """Carga un archivo de prompt desde el directorio /prompts/."""
        try:
            path = os.path.join(self.prompts_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            print(f"⚠️ Prompt no encontrado: {filename}")
            return ""

    def _inject_date(self, prompt: str) -> str:
        """Sustituye el placeholder {FECHA_ACTUAL} por la fecha real del sistema."""
        fecha_actual = datetime.now().strftime("%Y-%m-%d")
        return prompt.replace("{FECHA_ACTUAL}", fecha_actual)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_api(self, prompt: str) -> object:
        """
        Llama a la API de Gemini con reintentos automáticos (backoff exponencial).
        Máximo 3 intentos: espera 2s, 4s, 8s entre reintentos.
        Fuerza la respuesta en formato JSON estricto.
        """
        return self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # CLASIFICADOR DE INTENCIÓN — Enrutador principal
    # ─────────────────────────────────────────────────────────────────────────

    def classify_intent(self, user_message: str) -> dict:
        """
        Determina si el usuario quiere registrar un gasto ('log'), consultar
        datos ('query'), pedir un análisis ('analysis'), o es ambiguo ('unknown').

        Es el primer paso del pipeline y decide a qué handler se enviará
        el mensaje en main.py.

        Fallback seguro: si la clasificación falla por cualquier motivo,
        devuelve {"intent": "log"} para no perder posibles registros de gastos.
        """
        try:
            instructions = self._load_prompt("query_prompt.txt")
            instructions = self._inject_date(instructions)
            prompt = f"{instructions}\n\n--- MENSAJE DEL USUARIO ---\n{user_message}"
            response = self._call_api(prompt)
            return json.loads(response.text)
        except Exception as e:
            print(f"❌ Error clasificando intención: {e}")
            return {"intent": "log"}  # Fallback: nunca perder un posible gasto

    # ─────────────────────────────────────────────────────────────────────────
    # PROCESAMIENTO DE TRANSACCIONES
    # ─────────────────────────────────────────────────────────────────────────

    def process_transaction(self, current_input: str, history: str = "") -> tuple:
        """
        Procesa un mensaje de texto natural del usuario para extraer
        uno o varios gastos/ingresos.

        El historial de conversación (últimas 4 interacciones) se incluye
        en el prompt para resolver ambigüedades como "¿cuánto fue?" sin
        repetir el concepto.

        Retorna: (resultado, status)
        - status "SUCCESS": resultado es una lista de dicts [{concepto, categoria, importe...}]
        - status "DOUBT": resultado es una string con la pregunta de clarificación
        - status "ERROR": resultado es una string con el error
        """
        try:
            instructions = self._load_prompt("system_prompt.txt")
            instructions = self._inject_date(instructions)
            full_prompt = (
                f"{instructions}\n\n"
                f"--- HISTORIAL ---\n{history}\n\n"
                f"--- ACTUAL ---\n{current_input}"
            )

            response = self._call_api(full_prompt)
            data = json.loads(response.text)

            if data.get("duda"):
                return data["duda"], "DOUBT"

            return data.get("movimientos", []), "SUCCESS"

        except Exception as e:
            return f"Error en IA: {str(e)}", "ERROR"

    def process_raw_document(self, raw_text: str) -> tuple:
        """
        Procesa el texto crudo extraído de un PDF o Excel bancario.

        A diferencia de process_transaction(), aquí no hay historial de
        conversación. El texto puede tener cientos de líneas, por lo que
        el prompt instruye explícitamente a no omitir ninguna transacción real.

        Retorna: (resultado, status) — igual que process_transaction()
        """
        if not raw_text or not raw_text.strip():
            return [], "SUCCESS"

        try:
            instructions = self._load_prompt("system_prompt.txt")
            instructions = self._inject_date(instructions)
            prompt = (
                f"{instructions}\n\n"
                f"--- MODO LECTOR DE DOCUMENTOS BANCARIOS ---\n"
                "El usuario ha subido un extracto bancario en crudo (Excel o PDF). "
                "Tu objetivo es analizar TODAS las líneas y extraer tanto GASTOS como INGRESOS reales.\n"
                "Registra la nómina y cualquier ingreso real como tipo INGRESO con categoría 'Nómina' u 'Otros'.\n"
                "Sigue estrictamente las reglas del sistema sobre qué IGNORAR.\n"
                "El campo 'fecha' DEBE ser YYYY-MM-DD completo. Si el extracto solo da mes/año, usa el día 1.\n\n"
                f"--- DATOS CRUDOS DEL BANCO ---\n{raw_text}\n"
            )

            print(f"🧠 Enviando a Gemini documento de {len(raw_text)} caracteres...")
            response = self._call_api(prompt)
            data = json.loads(response.text)

            return data.get("movimientos", []), "SUCCESS"

        except Exception as e:
            print(f"❌ Error en Gemini Document Parsing: {e}")
            return [], "ERROR"

    def answer_financial_question(self, budget_data: dict, user_question: str) -> str:
        """
        Responde CUALQUIER pregunta financiera del usuario basándose en el
        contenido completo de su hoja de presupuesto (todos los meses, todas
        las categorías).

        Soporta cualquier pregunta: media de meses, comparativas, totales
        históricos, ahorro real (puede ser negativo), tendencias, etc.

        Args:
            budget_data: Dict completo de {categoría: {mes: importe}}
            user_question: Pregunta en lenguaje natural del usuario

        Returns:
            Respuesta en HTML (etiquetas <b>, <i>), lista para Telegram.
        """
        try:
            fecha_actual = datetime.now().strftime("%Y-%m-%d")
            año_actual = datetime.now().year

            prompt = (
                f"Eres Sentinel, un asesor financiero personal profesional, directo y claro.\n"
                f"Fecha actual: {fecha_actual}. Año en curso: {año_actual}.\n\n"

                "=== REGLAS DE INTERPRETACIÓN DE DATOS ===\n"
                "Los datos contienen TODAS las categorías del presupuesto del usuario.\n"
                "IMPORTANTE — Distingue entre INGRESOS y GASTOS así:\n"
                "  • INGRESOS: ÚNICAMENTE la categoría 'Nómina'. Todo lo demás son GASTOS.\n"
                "  • AHORRO de un mes = Nómina de ese mes - SUMA de todos los demás gastos de ese mes.\n"
                "  • El ahorro PUEDE ser negativo (si los gastos superan a la nómina).\n"
                "  • Si la categoría 'Nómina' no tiene dato para un mes, el ingreso de ese mes es 0€ "
                "y el ahorro será negativo.\n"
                "  • Si un mes tiene gastos pero NO tiene 'Nómina' registrada, indícalo: "
                "'(nómina no registrada ese mes)'.\n\n"

                "=== DATOS DEL PRESUPUESTO ===\n"
                f"{json.dumps(budget_data, ensure_ascii=False, indent=2)}\n\n"

                f"=== PREGUNTA DEL USUARIO ===\n{user_question}\n\n"

                "=== INSTRUCCIONES DE RESPUESTA ===\n"
                "- Responde de forma DIRECTA y CONCRETA a lo que pregunta, sin rodeos.\n"
                "- Si pregunta por un mes concreto, busca ese mes en los datos y responde exactamente.\n"
                "- Si pregunta por medias, calcúlalas tú mismo sumando y dividiendo.\n"
                "- Si pregunta por comparativas entre meses, hazlas con los datos reales.\n"
                "- NUNCA omitas un mes que el usuario pregunte aunque el ahorro sea negativo.\n"
                "- Muestra los valores negativos con el signo menos: '-40€'.\n"
                "- Si un mes realmente no tiene NINGÚN dato, di 'sin registros'.\n"
                "- Máximo 300 palabras.\n"
                "- Responde ÚNICAMENTE en español.\n\n"

                "=== FORMATO DE RESPUESTA ===\n"
                "OBLIGATORIO: Usa etiquetas HTML de Telegram, NO markdown con asteriscos.\n"
                "  • Negrita: <b>texto</b>  (NO **texto**)\n"
                "  • Cursiva: <i>texto</i>  (NO *texto*)\n"
                "  • Listas: usa el carácter • como viñeta, NO guiones ni asteriscos\n"
                "  • No uses encabezados con # ni separadores con ---\n"
                "  • No uses tablas markdown\n"
            )

            # Para respuestas en lenguaje natural no forzamos JSON
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            return response.text.strip()

        except Exception as e:
            print(f"❌ Error en answer_financial_question: {e}")
            return "No pude acceder a tus datos financieros en este momento. Inténtalo de nuevo."

    def generate_analysis(self, budget_data: dict, focus: str = None) -> str:
        """
        Genera un análisis financiero en lenguaje natural a partir de los
        datos leídos del Sheet (ingresos, gastos por categoría, ahorro).

        Usada en el flujo 'analysis' del clasificador de intenciones.
        Devuelve directamente el texto de respuesta (no JSON).
        """
        try:
            fecha_actual = datetime.now().strftime("%Y-%m-%d")
            focus_str = f"El usuario quiere enfocarse en: {focus}" if focus else ""

            prompt = (
                f"Eres Sentinel, un asesor financiero personal profesional y cercano.\n"
                f"Fecha actual: {fecha_actual}.\n"
                f"{focus_str}\n\n"
                "Analiza los siguientes datos financieros del mes actual y proporciona "
                "un resumen claro, con emojis, destacando lo positivo, lo preocupante "
                "y un consejo concreto y accionable.\n\n"
                f"--- DATOS FINANCIEROS ---\n{json.dumps(financial_data, ensure_ascii=False, indent=2)}\n\n"
                "Responde en español, de forma directa y útil. Máximo 200 palabras."
            )

            # Para análisis no forzamos JSON — queremos texto natural
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            return response.text.strip()

        except Exception as e:
            print(f"❌ Error en análisis IA: {e}")
            return "No pude generar el análisis en este momento. Inténtalo de nuevo."

    def evaluate_spending(self, transactions: list, dynamic_profile: dict) -> tuple:
        """
        Analiza transacciones contra el perfil histórico del usuario para
        detectar gastos impulsivos. Preparado para uso futuro (Fase 3).

        Retorna: (alerta: bool, motivo: str)
        """
        try:
            prompt = (
                "Eres un Asesor Financiero Proactivo muy estricto y severo.\n"
                f"Perfil de gasto histórico mensual del usuario:\n{json.dumps(dynamic_profile, indent=2)}\n\n"
                f"Compras recientes:\n{json.dumps(transactions, indent=2)}\n\n"
                "Instrucciones:\n"
                "1. Busca gastos impulsivos en categorías críticas (Ocio, Alcohol, Tabaco, Fiesta).\n"
                "2. Si un gasto supera el 30% de la media mensual de esa categoría, emite alerta.\n"
                "3. Responde ESTRICTAMENTE con JSON: "
                "{'alerta': true/false, 'motivo': 'Mensaje amigable pero severo con emojis.'}\n"
            )

            response = self._call_api(prompt)
            data = json.loads(response.text)
            return data.get("alerta", False), data.get("motivo", "")

        except Exception as e:
            print(f"❌ Error en evaluación proactiva IA: {e}")
            return False, ""