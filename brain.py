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
    def _call_api(self, prompt: str) -> dict:
        """
        Llama a la API de Gemini y parsea el JSON, con reintentos automáticos
        (backoff exponencial). Máximo 3 intentos: espera 2s, 4s, 8s entre
        reintentos. El parseo ocurre DENTRO del bloque reintentado a
        propósito: Gemini puede devolver un 200 OK con un JSON ocasionalmente
        mal formado (glitch de generación), y sin esto ese fallo nunca se
        reintentaba — se propagaba directo como error al usuario.
        """
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )
        return json.loads(response.text)

    # ─────────────────────────────────────────────────────────────────────────
    # CLASIFICADOR DE INTENCIÓN — Enrutador principal
    # ─────────────────────────────────────────────────────────────────────────

    def _keyword_classify_intent(self, text: str) -> str | None:
        """
        Clasificador rápido basado en patrones de texto.
        Maneja los casos obvios de REGISTRO sin llamar a la API de Gemini,
        ahorrando ~50% de llamadas en uso rutinario.
        """
        t = text.lower().strip().lstrip("¿¡")

        # Patrones que indican CONSULTA financiera
        QUERY_STARTERS = (
            "cuánto", "cuanto", "qué", "que", "cuál", "cual",
            "cuáles", "cuales", "cómo", "como", "dónde", "cuándo", "cuando",
            "muestra", "dame", "dime", "enseñame", "lista", "busca",
            "resumen", "presupuesto", "balance", "informe", "desglose", "desglosa",
            "patrimonio", "ahorro", "nota", "notas", "apunta", "borra", "elimina",
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
            data = self._call_api(prompt)

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
                if "desglos" in msg_lower and ("gasto" in msg_lower or "ocio" in msg_lower or "vital" in msg_lower or "todo" in msg_lower):
                    if "vital" in msg_lower and "ocio" not in msg_lower and "todo" not in msg_lower:
                        return {"intent": "query", "query_type": "section_breakdown", "section": "vitales"}
                    if "ocio" in msg_lower and "vital" not in msg_lower and "todo" not in msg_lower:
                        return {"intent": "query", "query_type": "section_breakdown", "section": "ocio"}
                    return {"intent": "query", "query_type": "expenses_breakdown"}
                if "ahorro" in msg_lower:
                    return {"intent": "query", "query_type": "monthly_savings"}
                if "nomina" in msg_lower or "nómina" in msg_lower:
                    return {"intent": "query", "query_type": "category_total", "category": "Nómina"}
                if "top" in msg_lower or "mas" in msg_lower or "más" in msg_lower:
                    return {"intent": "query", "query_type": "top_categories"}
                if "nota" in msg_lower or "notas" in msg_lower or "comentario" in msg_lower:
                    if any(w in msg_lower for w in ("borra", "borrar", "elimina", "eliminar", "quita", "quitar")):
                        note_txt = user_message.split(":", 1)[1].strip() if ":" in user_message else None
                        return {"intent": "query", "query_type": "delete_note", "note_text": note_txt}
                    if any(w in msg_lower for w in ("añade", "agrega", "pon", "guarda", "apunta", "anota")):
                        note_txt = user_message
                        if ":" in user_message:
                            note_txt = user_message.split(":", 1)[1].strip()
                        return {"intent": "query", "query_type": "add_note", "note_text": note_txt}
                    return {"intent": "query", "query_type": "get_notes"}
                if "busca" in msg_lower or "cuando compr" in msg_lower or "cuándo compr" in msg_lower:
                    return {"intent": "query", "query_type": "search_transaction", "search_term": user_message}
                return {"intent": "query", "query_type": "monthly_summary"}

            # Ni el clasificador rápido ni Gemini pudieron determinar la
            # intención (ej. cuota de la API agotada). Antes esto asumía
            # "log" a ciegas, lo que llevaba a un segundo intento fallido
            # contra Gemini en process_transaction y el bot se quedaba sin
            # responder nada. Mejor admitir el fallo explícitamente.
            return {"intent": "error", "raw_message": user_message}

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

            data = self._call_api(full_prompt)

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
            data = self._call_api(prompt)

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
        # Distingue "no hay dato real" (dict/lista vacíos) de "no se pudo
        # leer Sheets" (None, o dict con clave "error" SIN "success"): un
        # fallo técnico no debe presentarse como si el saldo real fuera
        # 0,00€. Los dicts de ESCRITURA (add_note, delete_note...) siempre
        # incluyen "success" con su propio "error" de negocio (nota vacía,
        # no encontrada...) — esos deben llegar a su rama específica más
        # abajo, no confundirse aquí con un fallo de conexión.
        if data is None or (isinstance(data, dict) and "success" not in data and data.get("error")):
            return (
                "⚠️ No pude leer tus datos ahora mismo "
                "(error de conexión con Google Sheets). Inténtalo de nuevo en unos segundos."
            )

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


        # ── 3. Balance mensual, ahorro, ingresos o gasto total ────────────
        elif query_type in ("monthly_summary", "monthly_savings", "monthly_income", "monthly_expenses"):
            m_name = data.get("month_name", "Mes actual")
            ingresos = data.get("total_ingresos", 0.0)
            vitales = data.get("total_gastos_vitales", 0.0)
            ocio = data.get("total_gastos_ocio", 0.0)
            inversion = data.get("total_inversion", 0.0)
            ahorro = data.get("ahorro_neto", 0.0)
            tasa = data.get("tasa_ahorro", 0.0)
            total_gastos = data.get("total_gastos", round(vitales + ocio, 2))

            if query_type == "monthly_income":
                return f"💵 <b>Ingresos totales ({m_name}):</b> <code>{self._format_euro(ingresos)}</code>"

            if query_type == "monthly_expenses":
                return (
                    f"📉 <b>Gasto Total ({m_name}):</b> <code>{self._format_euro(total_gastos)}</code>\n"
                    f"🏠 Vitales: {self._format_euro(vitales)}  |  ☕ Ocio: {self._format_euro(ocio)}"
                )

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

        # ── 6. Consulta de Notas Mensuales ────────────────────────────────
        elif query_type == "get_notes":
            m_name = data.get("month_name", "Mes actual")
            notes = data.get("notes", "").strip()
            if not notes:
                return f"📝 <b>Notas de {m_name}:</b>\n<i>No tienes notas registradas para este mes en la hoja de cálculo.</i>"

            bullets = [f"• {n.strip()}" for n in notes.split(" | ") if n.strip()]
            formatted_notes = "\n".join(bullets)
            return f"📝 <b>Notas de {m_name}:</b>\n\n{formatted_notes}"

        # ── 7. Añadir Nota Mensual ────────────────────────────────────────
        elif query_type == "add_note":
            if data.get("success"):
                m_name = data.get("month_name", "Mes actual")
                added = data.get("added", "")
                notes = data.get("notes", "").strip()
                bullets = [f"• {n.strip()}" for n in notes.split(" | ") if n.strip()]
                formatted_notes = "\n".join(bullets)
                return (
                    f"✅ <b>Nota registrada correctamente para {m_name}:</b>\n"
                    f"<i>\"{added}\"</i>\n\n"
                    f"📝 <b>Notas acumuladas ({m_name}):</b>\n{formatted_notes}"
                )
            else:
                return f"❌ <b>Error al guardar la nota:</b> <code>{data.get('error', 'Desconocido')}</code>"

        # ── 8. Búsqueda de un movimiento concreto en el log de auditoría ──
        elif query_type == "search_transaction":
            items = data if isinstance(data, list) else []
            if not items:
                return "🔍 No encontré ningún movimiento que coincida con esa búsqueda."

            lines = ["🔍 <b>Movimientos encontrados:</b>\n"]
            for it in items:
                lines.append(
                    f"• <code>{it['fecha']}</code> | <b>{it['concepto']}</b> ({it['categoria']}): "
                    f"<code>{self._format_euro(it['importe'])}</code>"
                )
            return "\n".join(lines)

        # ── 9. Borrar Nota Mensual ─────────────────────────────────────────
        elif query_type == "delete_note":
            if data.get("success"):
                m_name = data.get("month_name", "Mes actual")
                removed = data.get("removed", [])
                notes = data.get("notes", "").strip()
                removed_str = "\n".join(f"• {r}" for r in removed)
                header = f"🗑️ <b>Nota(s) eliminada(s) de {m_name}:</b>\n{removed_str}"
                if notes:
                    bullets = [f"• {n.strip()}" for n in notes.split(" | ") if n.strip()]
                    return header + f"\n\n📝 <b>Notas restantes ({m_name}):</b>\n" + "\n".join(bullets)
                return header + f"\n\n📝 No quedan más notas para {m_name}."
            else:
                return f"❌ <b>No pude borrar la nota:</b> <code>{data.get('error', 'Desconocido')}</code>"

        # ── 10. Desglose Completo de Gastos (Vitales + Ocio) ─────────────
        elif query_type == "expenses_breakdown":
            m_name = data.get("month_name", "Mes actual")
            vitales = data.get("vitales", {})
            ocio = data.get("ocio", {})
            total_gastos = data.get("total_gastos", 0.0)

            vit_items = [it for it in vitales.get("items", []) if it["total"] > 0]
            ocio_items = [it for it in ocio.get("items", []) if it["total"] > 0]

            if not vit_items and not ocio_items:
                return f"ℹ️ No hay gastos registrados para {m_name}."

            lines = [f"📊 <b>Desglose de Gastos — {m_name}</b>\n"]

            lines.append("🏠 <b>Gastos Vitales:</b>")
            if vit_items:
                for it in vit_items:
                    lines.append(f"  • {it['categoria']}: {self._format_euro(it['total'])}")
                lines.append(f"  <i>Subtotal Vitales: {self._format_euro(vitales.get('total', 0.0))}</i>\n")
            else:
                lines.append("  <i>Sin gastos vitales registrados</i>\n")

            lines.append("☕ <b>Ocio y Extras:</b>")
            if ocio_items:
                for it in ocio_items:
                    lines.append(f"  • {it['categoria']}: {self._format_euro(it['total'])}")
                lines.append(f"  <i>Subtotal Ocio: {self._format_euro(ocio.get('total', 0.0))}</i>\n")
            else:
                lines.append("  <i>Sin gastos de ocio registrados</i>\n")

            lines.append(f"📉 <b>Total Gastos:</b> <code>{self._format_euro(total_gastos)}</code>")
            return "\n".join(lines)

        # ── 11. Desglose de una sección (Vitales / Ocio / Inversión) ─────
        elif query_type == "section_breakdown":
            section_name = data.get("section_name", "esta sección")
            m_name = data.get("month_name", "Mes actual")
            items = data.get("items", [])
            total = data.get("total", 0.0)

            con_gasto = [it for it in items if it["total"] > 0]
            if not con_gasto:
                return f"ℹ️ No hay gastos registrados en {section_name} para {m_name}."

            lines = [f"📊 <b>Desglose de {section_name} — {m_name}</b>\n"]
            for it in con_gasto:
                lines.append(f"• <b>{it['categoria']}:</b> {self._format_euro(it['total'])}")
            lines.append(f"\n💰 <b>Total {section_name}:</b> <code>{self._format_euro(total)}</code>")
            return "\n".join(lines)

        # ── 11. Promedio de ingresos/gastos en lo que va de año ───────────
        elif query_type == "yearly_average":
            n = data.get("meses_computados", 0)
            if n == 0:
                return "ℹ️ Todavía no hay suficientes meses con datos para calcular una media."

            ingresos = data.get("media_ingresos", 0.0)
            gastos = data.get("media_gastos", 0.0)
            ahorro = data.get("media_ahorro", 0.0)
            sign = "+" if ahorro >= 0 else ""
            icon = "💚" if ahorro >= 0 else "🔴"
            return (
                f"📊 <b>Promedio mensual</b> <i>(sobre {n} mes{'es' if n != 1 else ''} con datos)</i>\n\n"
                f"• 💵 Ingresos medios: {self._format_euro(ingresos)}\n"
                f"• 📉 Gastos medios: {self._format_euro(gastos)}\n"
                f"{icon} <b>Ahorro medio:</b> <code>{sign}{self._format_euro(ahorro)}</code>"
            )

        return "📊 Consulta procesada correctamente."

    def answer_financial_question(self, budget_data: dict, user_question: str) -> str:
        """
        Método de fallback mantenido por compatibilidad:
        Responde basándose en los datos pasados.
        """
        return self.format_query_response("monthly_summary", budget_data.get("resumen_mes_actual", {}), user_question)