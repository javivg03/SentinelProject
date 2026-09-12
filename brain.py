import os
import re
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

    Interfaz con Google Gemini que gestiona:
    1. Clasificación de intención y extracción de parámetros (log vs query vs unknown).
    2. Extracción de movimientos a partir de lenguaje natural o documentos bancarios.
    3. Formateo determinista de consultas financieras con CERO alucinación numérica.
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

    def _keyword_classify_intent(self, text: str) -> str | None:
        """
        Clasificador rápido basado en patrones de texto.
        Maneja los casos obvios de REGISTRO sin llamar a la API de Gemini,
        ahorrando ~50% de llamadas en uso rutinario.
        """
        t = text.lower().strip()

        # Patrones que indican CONSULTA financiera
        QUERY_STARTERS = (
            "cuánto", "cuanto", "qué", "que", "cuál", "cual",
            "cuáles", "cuales", "cómo", "como", "dónde",
            "muestra", "dame", "dime", "enseñame", "lista",
            "resumen", "presupuesto", "balance", "informe",
            "patrimonio", "ahorro",
        )
        if any(t.startswith(w) for w in QUERY_STARTERS):
            return "query"

        # Patrones que indican REGISTRO de gasto/ingreso claro
        LOG_VERBS = (
            "gasté", "gaste", "pagué", "pague", "compré", "compre",
            "he gastado", "he pagado", "he comprado", "costó", "costo",
            "me ha costado", "cobré", "cobre", "me han pagado", "recibi",
            "recibí", "nómina", "nomina",
        )
        has_amount = any(c.isdigit() for c in t) and ("€" in t or "euro" in t or "eur" in t)

        if has_amount and any(v in t for v in LOG_VERBS):
            return "log"

        # Si no tiene patrón evidente, delegar en Gemini
        return None

    def classify_intent(self, user_message: str, history: str = "") -> dict:
        """
        Determina si el usuario quiere registrar ('log') o consultar ('query').
        Para consultas, devuelve el desglose estructurado:
        {
            "intent": "query",
            "query_type": "category_total|income_breakdown|monthly_summary|monthly_savings|monthly_income|patrimony|top_categories|last_transactions",
            "category": str | None,
            "month": int | None
        }
        """
        fast_intent = self._keyword_classify_intent(user_message)
        if fast_intent == "log":
            return {"intent": "log"}

        # Si es consulta o texto libre, pedir a Gemini que clasifique y extraiga parámetros usando historial
        try:
            instructions = self._load_prompt("query_prompt.txt")
            instructions = self._inject_date(instructions)
            hist_str = f"--- HISTORIAL DE CONVERSACIÓN RECIENTE ---\n{history}\n\n" if history else ""
            prompt = f"{instructions}\n\n{hist_str}--- MENSAJE DEL USUARIO ---\n{user_message}"
            response = self._call_api(prompt)
            data = json.loads(response.text)

            if isinstance(data, dict):
                return data

            return {"intent": "query", "query_type": "monthly_summary"}

        except Exception as e:
            print(f"❌ Error clasificando intención con Gemini: {e}")
            if fast_intent == "query":
                msg_lower = user_message.lower()
                if "patrimonio" in msg_lower or "net worth" in msg_lower:
                    return {"intent": "query", "query_type": "patrimony"}
                if "desglos" in msg_lower and "ingres" in msg_lower:
                    return {"intent": "query", "query_type": "income_breakdown"}
                if "ahorro" in msg_lower:
                    return {"intent": "query", "query_type": "monthly_savings"}
                if "nomina" in msg_lower or "nómina" in msg_lower:
                    return {"intent": "query", "query_type": "category_total", "category": "Nómina"}
                if "top" in msg_lower or "mas" in msg_lower or "más" in msg_lower:
                    return {"intent": "query", "query_type": "top_categories"}
                return {"intent": "query", "query_type": "monthly_summary"}

            return {"intent": "log"}

    # ─────────────────────────────────────────────────────────────────────────
    # PROCESAMIENTO DE TRANSACCIONES (REGISTRO)
    # ─────────────────────────────────────────────────────────────────────────

    def process_transaction(self, current_input: str, history: str = "") -> tuple:
        """
        Procesa un mensaje de texto natural para extraer uno o varios movimientos.
        Retorna: (resultado, status)
        - status "SUCCESS": lista de dicts [{concepto, categoria, importe, tipo, fecha}]
        - status "DOUBT": pregunta de clarificación
        - status "ERROR": mensaje de error
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
        Procesa el texto crudo de un extracto bancario (PDF o Excel).
        Retorna: (resultado, status)
        """
        if not raw_text or not raw_text.strip():
            return [], "SUCCESS"

        try:
            instructions = self._load_prompt("system_prompt.txt")
            instructions = self._inject_date(instructions)
            prompt = (
                f"{instructions}\n\n"
                f"--- MODO LECTOR DE DOCUMENTOS BANCARIOS ---\n"
                "El usuario ha subido un extracto bancario en crudo. Extrae todos los gastos e ingresos reales.\n"
                f"--- DATOS CRUDOS DEL BANCO ---\n{raw_text}\n"
            )

            print(f"🧠 Enviando a Gemini documento de {len(raw_text)} caracteres...")
            response = self._call_api(prompt)
            data = json.loads(response.text)

            return data.get("movimientos", []), "SUCCESS"

        except Exception as e:
            print(f"❌ Error en Gemini Document Parsing: {e}")
            return [], "ERROR"

    # ─────────────────────────────────────────────────────────────────────────
    # FORMATEO DETERMINISTA DE CONSULTAS (CERO ALUCINACIONES)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_euro(val: float) -> str:
        """Formatea un número con formato español: 1.234,56€."""
        return f"{val:,.2f}€".replace(",", "X").replace(".", ",").replace("X", ".")

    def format_query_response(self, query_type: str, data: dict, user_question: str = "") -> str:
        """
        Construye la respuesta en HTML de Telegram a partir EXCLUSIVAMENTE
        de los datos numéricos extraídos de Google Sheets.
        """
        if not data:
            return "⚠️ No encontré datos para esa consulta en tu hoja de cálculo."

        # ── 1. Consulta de Patrimonio ─────────────────────────────────────
        if query_type == "patrimony":
            m_name = data.get("month_name", "Actual")
            tr = data.get("cuenta_tr_remunerada", 0.0)
            msci = data.get("fondo_msci_world", 0.0)
            btc = data.get("bitcoin", 0.0)
            unicaja = data.get("cuenta_unicaja", 0.0)
            total = data.get("patrimonio_total", 0.0)

            return (
                f"🏦 <b>Patrimonio Total ({m_name}):</b> <code>{self._format_euro(total)}</code>\n\n"
                f"• 🔒 <b>Cuenta Remunerada TR (2%):</b> {self._format_euro(tr)}\n"
                f"• 📈 <b>Fondo Fidelity MSCI World:</b> {self._format_euro(msci)}\n"
                f"• ₿ <b>Bitcoin (TR):</b> {self._format_euro(btc)}\n"
                f"• 💳 <b>Cuenta Unicaja (operativa):</b> {self._format_euro(unicaja)}"
            )

        # ── 2. Consulta de Desglose de Ingresos ────────────────────────────
        elif query_type == "income_breakdown":
            m_name = data.get("month_name", "Mes actual")
            nomina = data.get("nomina", 0.0)
            otros = data.get("otros", 0.0)
            regalos = data.get("regalos_extras", 0.0)
            total = data.get("total_ingresos", 0.0)

            lines = [f"💵 <b>Desglose de Ingresos — {m_name}</b>\n"]
            lines.append(f"• 💼 <b>Nómina:</b> {self._format_euro(nomina)}")
            if otros > 0:
                lines.append(f"• 📦 <b>Otros ingresos:</b> {self._format_euro(otros)}")
            if regalos > 0:
                lines.append(f"• 🎁 <b>Regalos / Extras:</b> {self._format_euro(regalos)}")
            lines.append(f"\n💰 <b>Total Ingresos:</b> <code>{self._format_euro(total)}</code>")
            return "\n".join(lines)

        # ── 3. Consulta de Categoría Concreta ──────────────────────────────
        elif query_type == "category_total":
            cat = data.get("category", "Categoría")
            spent = data.get("spent", 0.0)
            m_name = data.get("month_name", "Mes actual")
            budget = data.get("budget")

            cat_lower = cat.lower()
            if any(inc in cat_lower for inc in ("nómina", "nomina", "otros", "regalos", "ingreso")):
                resp = f"💵 <b>Ingreso por {cat} ({m_name}):</b> <code>{self._format_euro(spent)}</code>"
            else:
                resp = f"📊 <b>Gasto en {cat} ({m_name}):</b> <code>{self._format_euro(spent)}</code>"

            if budget and budget > 0:
                pct = (spent / budget) * 100
                icon = "⚠️" if spent > budget else "🎯"
                resp += f"\n{icon} <i>Presupuesto asignado: {self._format_euro(budget)} ({pct:.0f}% consumido)</i>"
            return resp


        # ── 3. Balance mensual, ahorro o ingresos ─────────────────────────
        elif query_type in ("monthly_summary", "monthly_savings", "monthly_income"):
            m_name = data.get("month_name", "Mes actual")
            ingresos = data.get("total_ingresos", 0.0)
            vitales = data.get("total_gastos_vitales", 0.0)
            ocio = data.get("total_gastos_ocio", 0.0)
            inversion = data.get("total_inversion", 0.0)
            ahorro = data.get("ahorro_neto", 0.0)
            tasa = data.get("tasa_ahorro", 0.0)

            if query_type == "monthly_income":
                return f"💵 <b>Ingresos totales ({m_name}):</b> <code>{self._format_euro(ingresos)}</code>"

            if query_type == "monthly_savings":
                sign = "+" if ahorro >= 0 else ""
                icon = "💚" if ahorro >= 0 else "🔴"
                return (
                    f"{icon} <b>Ahorro Neto ({m_name}):</b> <code>{sign}{self._format_euro(ahorro)}</code>\n"
                    f"📈 <i>Tasa de ahorro: {tasa:.1f}%</i>"
                )

            # Resumen mensual completo
            sign = "+" if ahorro >= 0 else ""
            icon = "💚" if ahorro >= 0 else "🔴"
            return (
                f"📊 <b>Balance Financiero — {m_name}</b>\n\n"
                f"• 💵 <b>Ingresos:</b> {self._format_euro(ingresos)}\n"
                f"• 🏠 <b>Gastos Vitales:</b> {self._format_euro(vitales)}\n"
                f"• ☕ <b>Ocio y Extras:</b> {self._format_euro(ocio)}\n"
                f"• 📈 <b>Inversión:</b> {self._format_euro(inversion)}\n\n"
                f"{icon} <b>Ahorro Neto:</b> <code>{sign}{self._format_euro(ahorro)}</code> ({tasa:.1f}%)"
            )

        # ── 4. Ranking de categorías donde más se gasta ───────────────────
        elif query_type == "top_categories":
            items = data if isinstance(data, list) else []
            if not items:
                return "ℹ️ No hay registros de gasto computados para este mes."

            lines = ["🏆 <b>Top Gastos del Mes:</b>\n"]
            for i, it in enumerate(items, 1):
                lines.append(f"{i}. <b>{it['categoria']}:</b> {self._format_euro(it['total'])}")
            return "\n".join(lines)

        # ── 5. Últimas transacciones del log de auditoría ─────────────────
        elif query_type == "last_transactions":
            items = data if isinstance(data, list) else []
            if not items:
                return "ℹ️ Todavía no hay movimientos registrados en el log de auditoría."

            lines = ["📝 <b>Últimas transacciones registradas:</b>\n"]
            for it in items:
                lines.append(
                    f"• <code>{it['fecha']}</code> | <b>{it['concepto']}</b> ({it['categoria']}): "
                    f"<code>{self._format_euro(it['importe'])}</code>"
                )
            return "\n".join(lines)

        return "📊 Consulta procesada correctamente."

    def answer_financial_question(self, budget_data: dict, user_question: str) -> str:
        """
        Método de fallback mantenido por compatibilidad:
        Responde basándose en los datos pasados.
        """
        return self.format_query_response("monthly_summary", budget_data.get("resumen_mes_actual", {}), user_question)