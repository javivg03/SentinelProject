import gspread
import os
import json
import datetime
import traceback
import unicodedata
import re
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()


def _normalize_text(text: str) -> str:
    """Normaliza texto eliminando acentos, caracteres especiales y convirtiendo a minúsculas."""
    if not text:
        return ""
    text = str(text).strip().lower()
    # Eliminar diacríticos (tildes)
    nfkd_form = unicodedata.normalize('NFKD', text)
    cleaned = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    # Limpiar espacios múltiples
    return re.sub(r'\s+', ' ', cleaned).strip()


class SheetsConnector:
    """
    Conector con Google Sheets para Sentinel adaptado a 'Finanzas_JVG_2026'.

    Pestañas gestionadas:
    1. '📊 Registro Mensual' (Matriz principal):
       - Columnas: Categoría (A), Concepto (B), Enero (C) ... Diciembre (N), Total Anual (O), Media/Mes (P).
       - Filas: Ingresos, Gastos Vitales, Ocio y Extras, Inversión y Ahorro, Resumen y Patrimonio.
    2. '🏦 Patrimonio y Objetivos':
       - Contiene el desglose de cubos y metas a largo plazo, enlazadas por fórmulas nativas a la Pestaña 1.
    3. 'Transacciones' (Log de auditoría - Opción B):
       - Histórico append-only con [Fecha, Concepto, Categoría, Importe, Tipo].
    4. Pestaña de Presupuesto ('🎯 Presupuesto Septiembre' o similar):
       - Objetivos de gasto mensual para alertas automáticas.
    """

    # 'drive.file' (no 'drive' completo): acceso solo a los ficheros que la
    # cuenta de servicio crea o que se le comparten explícitamente, en vez de
    # a todo el Google Drive del usuario (principio de mínimo privilegio).
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]

    MONTH_NAMES = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]

    # Filas fijas del resumen en '📊 Registro Mensual' (1-indexed)
    ROW_TOTAL_INGRESOS = 8
    ROW_TOTAL_VITALES = 20
    ROW_TOTAL_OCIO = 38
    ROW_TOTAL_INVERSION = 43
    ROW_AHORRO_NETO = 50
    ROW_TASA_AHORRO = 51

    # Filas de Patrimonio en '📊 Registro Mensual' (1-indexed)
    ROW_PATRIMONIO_TR = 54
    ROW_PATRIMONIO_MSCI = 55
    ROW_PATRIMONIO_BTC = 56
    ROW_PATRIMONIO_UNICAJA = 57
    ROW_PATRIMONIO_TOTAL = 58

    def __init__(self):
        try:
            # ── 1. Autenticación dual (local vs nube) ──────────────────────
            if os.path.exists("service_account.json"):
                self.creds = Credentials.from_service_account_file(
                    "service_account.json", scopes=self.SCOPES
                )
                print("🔑 Sentinel [Sheets]: Usando service_account.json local.")
            else:
                env_creds = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
                if not env_creds:
                    raise EnvironmentError(
                        "❌ No se encontró 'service_account.json' ni "
                        "la variable 'GOOGLE_SERVICE_ACCOUNT_JSON'."
                    )
                info = json.loads(env_creds)
                self.creds = Credentials.from_service_account_info(
                    info, scopes=self.SCOPES
                )
                print("☁️ Sentinel [Sheets]: Usando credenciales de variable de entorno.")

            self.client = gspread.authorize(self.creds)

            # ── 2. Apertura del libro ─────────────────────────────────────
            spreadsheet_id = os.getenv("SPREADSHEET_ID")
            if not spreadsheet_id:
                raise ValueError("❌ La variable 'SPREADSHEET_ID' no está definida.")

            # Limpiar posibles caracteres extraños o sufijos
            spreadsheet_id = spreadsheet_id.strip()
            self.spreadsheet = self.client.open_by_key(spreadsheet_id)

            # ── 3. Localizar pestañas con búsqueda flexible ───────────────
            worksheets = self.spreadsheet.worksheets()
            ws_map = {ws.title: ws for ws in worksheets}

            # Pestaña 1: Matriz principal (busca 'Registro' o primer worksheet)
            self.matrix_sheet = None
            for title, ws in ws_map.items():
                if "registro" in title.lower():
                    self.matrix_sheet = ws
                    break
            if not self.matrix_sheet:
                # Fallback al primer worksheet
                self.matrix_sheet = worksheets[0]

            # Alias para compatibilidad con código antiguo
            self.sheet = self.matrix_sheet

            # Pestaña 2: Patrimonio
            self.patrimony_sheet = None
            for title, ws in ws_map.items():
                if "patrimonio" in title.lower():
                    self.patrimony_sheet = ws
                    break

            # Pestaña 3: Presupuesto (para alertas)
            self.budget_sheet = None
            for title, ws in ws_map.items():
                if "presupuesto" in title.lower():
                    self.budget_sheet = ws
                    break

            # Pestaña Auxiliar: Log de auditoría ('Transacciones')
            self.transactions_sheet = None
            for title, ws in ws_map.items():
                if "transacciones" in title.lower() or "movimientos" in title.lower():
                    self.transactions_sheet = ws
                    break

            if not self.transactions_sheet:
                try:
                    self.transactions_sheet = self.spreadsheet.add_worksheet(
                        title="Transacciones", rows="5000", cols="5"
                    )
                    self.transactions_sheet.append_row(
                        ["Fecha", "Concepto", "Categoría", "Importe", "Tipo"]
                    )
                    print("✨ Pestaña 'Transacciones' creada automáticamente.")
                except Exception as e:
                    print(f"⚠️ No se pudo crear pestaña 'Transacciones': {e}")

            # ── 4. Mapeo de Columnas de Mes ──────────────────────────────
            # Enero=Col 3 (C), Febrero=Col 4 (D), ..., Diciembre=Col 14 (N)
            self.month_columns = {m: m + 2 for m in range(1, 13)}

            # ── 5. Mapeo de Categorías (Columna B de Registro Mensual) ────
            self._load_category_mappings()

            # ── 6. Cargar límites de presupuesto para alertas ────────────
            self.budget_limits = self._load_budget_limits()

            print(
                f"✅ Conexión establecida con '{self.spreadsheet.title}'. "
                f"Pestaña matriz: '{self.matrix_sheet.title}'. "
                f"Categorías indexadas: {len(self.category_map)}."
            )

        except Exception as e:
            print(f"❌ Error crítico en SheetsConnector: {e}")
            traceback.print_exc()
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # INICIALIZACIÓN Y CACHÉ
    # ─────────────────────────────────────────────────────────────────────────

    def _load_category_mappings(self):
        """
        Escanea la columna B ('Concepto') de '📊 Registro Mensual' y crea
        un diccionario de mapeo a fila (1-indexed), incluyendo sinónimos comunes.
        """
        self.category_map = {}
        self.category_display_names = {}

        try:
            # Leemos las primeras 50 filas de la columna B (Concepto)
            col_b = self.matrix_sheet.col_values(2)
            col_a = self.matrix_sheet.col_values(1)

            for i, val in enumerate(col_b):
                row_idx = i + 1
                concept = str(val).strip()
                if not concept or concept.lower() == "concepto":
                    continue

                clean_key = _normalize_text(concept)
                self.category_map[clean_key] = row_idx
                self.category_display_names[clean_key] = concept

            # Mapear sinónimos / alias habituales para mayor tolerancia
            synonyms = {
                "super": "supermercado",
                "mercadona": "supermercado",
                "carrefour": "supermercado",
                "lidl": "supermercado",
                "alcampo": "supermercado",
                "compra": "supermercado",
                "gasoil": "gasolina",
                "combustible": "gasolina",
                "repostaje": "gasolina",
                "farmacia": "farmacia / salud",
                "salud": "farmacia / salud",
                "medicamentos": "farmacia / salud",
                "disney": "suscripciones",
                "suscripcion disney": "suscripciones",
                "netflix": "suscripciones",
                "spotify": "suscripciones",
                "suscripcion": "suscripciones",
                "suscripciones": "suscripciones",
                "bar": "tomar algo",
                "cerveza": "tomar algo",
                "cervezas": "tomar algo",
                "copas": "tomar algo",
                "alcohol": "tomar algo",
                "restaurante": "comer fuera",
                "restaurantes": "comer fuera",
                "cena": "comer fuera",
                "cenar": "comer fuera",
                "comida": "comer fuera",
                "almuerzo": "comer fuera",
                "clases": "clases particulares",
                "msci world": "dca msci world (tr)",
                "msci": "dca msci world (tr)",
                "sp500": "dca msci world (tr)",
                "s&p 500": "dca msci world (tr)",
                "s&p500": "dca msci world (tr)",
                "btc": "dca btc (tr)",
                "bitcoin": "dca btc (tr)",
                "nomina": "nomina",
                "sueldo": "nomina",
                "paga": "nomina",
            }

            for alias, target in synonyms.items():
                norm_target = _normalize_text(target)
                if norm_target in self.category_map:
                    self.category_map[_normalize_text(alias)] = self.category_map[norm_target]

        except Exception as e:
            print(f"⚠️ Error cargando categorías de la matriz: {e}")

    def _load_budget_limits(self) -> dict:
        """
        Lee los límites de gasto mensual fijados en la pestaña de Presupuesto.
        Devuelve dict: {clean_category_name: limit_float}.
        """
        limits = {}
        if not self.budget_sheet:
            return limits

        try:
            all_vals = self.budget_sheet.get_all_values()
            # La tabla tiene Columna B (Concepto) y Columna C (Presupuesto)
            for row in all_vals[7:]:  # Empezar desde fila 8
                if len(row) < 3:
                    continue
                concept = row[1].strip()
                budget_val = row[2].strip()
                if not concept or not budget_val:
                    continue

                clean_concept = _normalize_text(concept)
                amt = self._clean_value(budget_val)
                if amt > 0:
                    limits[clean_concept] = amt

        except Exception as e:
            print(f"⚠️ Error cargando límites de presupuesto: {e}")

        return limits

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS PRIVADOS
    # ─────────────────────────────────────────────────────────────────────────

    def _clean_value(self, val) -> float:
        """Normaliza cualquier celda a float positivo operable."""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        try:
            s = str(val).replace("€", "").replace("%", "").replace(" ", "").strip()
            if not s or s.lower() in ("none", "#error!", "#ref!", "#value!", "—", "-"):
                return 0.0
            if "," in s and "." in s:
                s = s.replace(".", "").replace(",", ".")
            elif "," in s:
                s = s.replace(",", ".")
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    def _get_month_col(self, fecha_str: str = None) -> int:
        """Devuelve el número de columna (1-indexed) correspondiente al mes."""
        if fecha_str:
            try:
                # Extraer mes de formato YYYY-MM-DD o YYYY-MM
                parts = str(fecha_str).split("-")
                if len(parts) >= 2:
                    month = int(parts[1])
                    return self.month_columns.get(month, 11)
            except (IndexError, ValueError):
                pass
        now_month = datetime.datetime.now().month
        return self.month_columns.get(now_month, now_month + 2)

    def _get_month_idx(self, fecha_str: str = None) -> int:
        """Devuelve el número del mes (1 a 12)."""
        if fecha_str:
            try:
                parts = str(fecha_str).split("-")
                if len(parts) >= 2:
                    return int(parts[1])
            except (IndexError, ValueError):
                pass
        return datetime.datetime.now().month

    def _today(self) -> str:
        """Devuelve la fecha actual en formato YYYY-MM-DD."""
        return datetime.datetime.now().strftime("%Y-%m-%d")

    def _find_row_for_category(self, category: str) -> int:
        """Busca el número de fila para una categoría con búsqueda difusa."""
        clean = _normalize_text(category)
        if clean in self.category_map:
            return self.category_map[clean]

        # Búsqueda por contención
        for key, row in self.category_map.items():
            if key in clean or clean in key:
                return row

        # Si no se encuentra, buscar fila 'Otros'
        return self.category_map.get("otros", 32)

    # ─────────────────────────────────────────────────────────────────────────
    # ESCRITURA — log_expense y batch_log_expenses (OPCIÓN B)
    # ─────────────────────────────────────────────────────────────────────────

    def log_expense(
        self, concept: str, category: str, amount, fecha: str = None, tipo: str = None
    ) -> dict:
        """
        Registra una transacción siguiendo la Arquitectura Opción B:
        1. Acumula el importe en la matriz '📊 Registro Mensual' en la celda (categoría, mes).
        2. Añade fila en la pestaña auxiliar 'Transacciones' (log de auditoría).
        3. Evalúa si se supera el presupuesto asignado para alertar al usuario.

        Returns:
            dict con {
                "success": bool,
                "category": str,
                "amount": float,
                "new_total": float,
                "month_name": str,
                "budget_alert": str | None
            }
        """
        try:
            amount_to_add = abs(self._clean_value(amount))
            month_idx = self._get_month_idx(fecha)
            month_col = self._get_month_col(fecha)
            month_name = self.MONTH_NAMES[month_idx - 1]
            timestamp = fecha if fecha else self._today()

            target_row = self._find_row_for_category(category)
            clean_cat = _normalize_text(category)

            # Determinar tipo
            if not tipo:
                tipo = "INGRESO" if clean_cat in ("nomina", "regalos/extras", "otros ingresos") else "GASTO"
                if "dca" in clean_cat or "inversion" in clean_cat:
                    tipo = "AHORRO"

            # 1. Leer valor actual de la celda de la matriz y acumular
            current_cell_val = self._clean_value(self.matrix_sheet.cell(target_row, month_col).value)
            new_total = round(current_cell_val + amount_to_add, 2)
            self.matrix_sheet.update_cell(target_row, month_col, new_total)

            # 2. Append en pestaña 'Transacciones' (Auditoría)
            if self.transactions_sheet:
                try:
                    self.transactions_sheet.append_row(
                        [timestamp, concept, category, amount_to_add, tipo]
                    )
                except Exception as e_log:
                    print(f"⚠️ Error añadiendo fila a Transacciones: {e_log}")

            # 3. Comprobar alerta de presupuesto
            budget_alert = None
            budget_limit = self.budget_limits.get(clean_cat)
            if budget_limit and new_total > budget_limit:
                budget_alert = (
                    f"⚠️ <b>Atención: Presupuesto excedido en {category}</b>\n"
                    f"Llevas <b>{new_total:.2f}€</b> gastados de <b>{budget_limit:.2f}€</b> presupuestados "
                    f"({(new_total / budget_limit) * 100:.0f}%)."
                )

            print(f"💰 Registro exitoso: {category} ({month_name}) | {current_cell_val}€ → {new_total}€")
            return {
                "success": True,
                "category": category,
                "amount": amount_to_add,
                "new_total": new_total,
                "month_name": month_name,
                "budget_alert": budget_alert,
            }

        except Exception as e:
            print(f"❌ Error al registrar gasto en Sheets: {e}")
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def batch_log_expenses(self, parsed_items: list) -> int:
        """
        Registra un lote masivo de movimientos (extractos bancarios):
        1. Vuelca todas las filas en 'Transacciones'.
        2. Agrupa por (mes, categoría) y actualiza las celdas en la matriz.
        """
        if not parsed_items:
            return 0

        try:
            rows_to_append = []
            aggregated = {}  # (target_row, month_col) -> float

            for item in parsed_items:
                f = item.get("fecha") or self._today()
                cat = item.get("categoria", "Otros")
                c = item.get("concepto", "Sin concepto")
                amt = abs(self._clean_value(item.get("importe", 0)))
                tipo = item.get("tipo", "GASTO")

                rows_to_append.append([f, c, cat, amt, tipo])

                target_row = self._find_row_for_category(cat)
                month_col = self._get_month_col(f)
                key = (target_row, month_col)
                aggregated[key] = aggregated.get(key, 0.0) + amt

            # Volcar a Transacciones
            if self.transactions_sheet and rows_to_append:
                self.transactions_sheet.append_rows(rows_to_append)

            # Actualizar celdas en la matriz
            cells_to_update = []
            for (target_row, month_col), amt_to_add in aggregated.items():
                current_val = self._clean_value(self.matrix_sheet.cell(target_row, month_col).value)
                new_total = round(current_val + amt_to_add, 2)
                cells_to_update.append(
                    gspread.Cell(row=target_row, col=month_col, value=new_total)
                )

            if cells_to_update:
                self.matrix_sheet.update_cells(cells_to_update)

            return len(parsed_items)

        except Exception as e:
            print(f"❌ Error en batch_log_expenses: {e}")
            return 0

    # ─────────────────────────────────────────────────────────────────────────
    # LECTURA DETERMINISTA — Consultas Financieras sin Alucinaciones
    # ─────────────────────────────────────────────────────────────────────────

    def get_category_spending(self, category: str, month: int = None) -> dict:
        """
        Consulta determinista: devuelve el total gastado en una categoría exacta
        para el mes indicado (por defecto el mes actual) y su presupuesto si existe.
        """
        try:
            month = month or datetime.datetime.now().month
            month_col = self.month_columns.get(month, month + 2)
            month_name = self.MONTH_NAMES[month - 1]

            target_row = self._find_row_for_category(category)
            clean_cat = _normalize_text(category)

            val_raw = self.matrix_sheet.cell(target_row, month_col).value
            spent = self._clean_value(val_raw)
            budget = self.budget_limits.get(clean_cat)

            display_name = self.category_display_names.get(clean_cat, category)

            return {
                "category": display_name,
                "month": month,
                "month_name": month_name,
                "spent": spent,
                "budget": budget,
            }
        except Exception as e:
            print(f"❌ Error en get_category_spending: {e}")
            return {"category": category, "spent": 0.0, "month_name": "Mes actual", "budget": None}

    def get_income_breakdown(self, month: int = None) -> dict:
        """
        Consulta determinista: devuelve el desglose de ingresos (Nómina, Otros, Regalos/Extras, Total)
        para el mes indicado.
        """
        try:
            month = month or datetime.datetime.now().month
            month_col = self.month_columns.get(month, month + 2)
            month_name = self.MONTH_NAMES[month - 1]

            col_data = self.matrix_sheet.col_values(month_col)

            def val_at(r):
                idx = r - 1
                return self._clean_value(col_data[idx]) if idx < len(col_data) else 0.0

            nomina = val_at(5)
            otros = val_at(6)
            regalos = val_at(7)
            total = val_at(8)

            if total == 0.0 and (nomina > 0 or otros > 0 or regalos > 0):
                total = round(nomina + otros + regalos, 2)

            return {
                "month": month,
                "month_name": month_name,
                "nomina": nomina,
                "otros": otros,
                "regalos_extras": regalos,
                "total_ingresos": total,
            }
        except Exception as e:
            print(f"❌ Error en get_income_breakdown: {e}")
            return {}

    def get_monthly_summary(self, month: int = None) -> dict:
        """
        Consulta determinista: lee las filas de resumen calculadas por fórmulas
        en '📊 Registro Mensual' para el mes solicitado.
        """
        try:
            month = month or datetime.datetime.now().month
            month_col = self.month_columns.get(month, month + 2)
            month_name = self.MONTH_NAMES[month - 1]

            # Leer celdas calculadas por fórmulas nativas
            col_data = self.matrix_sheet.col_values(month_col)

            def safe_get(row_idx):
                idx = row_idx - 1
                return self._clean_value(col_data[idx]) if idx < len(col_data) else 0.0

            total_ingresos = safe_get(self.ROW_TOTAL_INGRESOS)
            total_vitales = safe_get(self.ROW_TOTAL_VITALES)
            total_ocio = safe_get(self.ROW_TOTAL_OCIO)
            total_inversion = safe_get(self.ROW_TOTAL_INVERSION)
            ahorro_neto = safe_get(self.ROW_AHORRO_NETO)
            tasa_ahorro = safe_get(self.ROW_TASA_AHORRO) * 100

            # Si tasa de ahorro es 0 y hay ingresos, calcularla directamente
            if tasa_ahorro == 0.0 and total_ingresos > 0:
                tasa_ahorro = round((ahorro_neto / total_ingresos) * 100, 1)

            return {
                "month": month,
                "month_name": month_name,
                "total_ingresos": total_ingresos,
                "total_gastos_vitales": total_vitales,
                "total_gastos_ocio": total_ocio,
                "total_gastos": round(total_vitales + total_ocio, 2),
                "total_inversion": total_inversion,
                "ahorro_neto": ahorro_neto,
                "tasa_ahorro": round(tasa_ahorro, 1),
            }
        except Exception as e:
            print(f"❌ Error en get_monthly_summary: {e}")
            return {}

    def get_patrimony(self) -> dict:
        """
        Consulta determinista: lee las filas 54-58 de '📊 Registro Mensual'
        buscando el mes más reciente con datos reales de patrimonio.
        Optimizado: lee la fila 58 de totales en 1 sola llamada para identificar el mes.
        """
        try:
            row_total = self.matrix_sheet.row_values(self.ROW_PATRIMONIO_TOTAL)

            # Buscar desde diciembre hacia enero el mes con patrimonio > 0
            for m in range(12, 0, -1):
                col_idx = self.month_columns.get(m)  # m + 2
                val_total = (
                    self._clean_value(row_total[col_idx - 1])
                    if col_idx - 1 < len(row_total)
                    else 0.0
                )
                if val_total > 0:
                    col_data = self.matrix_sheet.col_values(col_idx)

                    def val_at(r):
                        idx = r - 1
                        return self._clean_value(col_data[idx]) if idx < len(col_data) else 0.0

                    return {
                        "month_name": self.MONTH_NAMES[m - 1],
                        "cuenta_tr_remunerada": val_at(self.ROW_PATRIMONIO_TR),
                        "fondo_msci_world": val_at(self.ROW_PATRIMONIO_MSCI),
                        "bitcoin": val_at(self.ROW_PATRIMONIO_BTC),
                        "cuenta_unicaja": val_at(self.ROW_PATRIMONIO_UNICAJA),
                        "patrimonio_total": val_total,
                    }

            return {
                "month_name": "Actual",
                "cuenta_tr_remunerada": 0.0,
                "fondo_msci_world": 0.0,
                "bitcoin": 0.0,
                "cuenta_unicaja": 0.0,
                "patrimonio_total": 0.0,
            }
        except Exception as e:
            print(f"❌ Error en get_patrimony: {e}")
            return {}

    def get_recent_transactions(self, limit: int = 5) -> list:
        """Devuelve las últimas N transacciones del log de auditoría."""
        if not self.transactions_sheet:
            return []
        try:
            all_rows = self.transactions_sheet.get_all_values()
            data_rows = all_rows[1:] if len(all_rows) > 1 else []
            last_n = data_rows[-limit:] if len(data_rows) >= limit else data_rows
            last_n.reverse()
            return [
                {
                    "fecha": r[0] if len(r) > 0 else "",
                    "concepto": r[1] if len(r) > 1 else "",
                    "categoria": r[2] if len(r) > 2 else "",
                    "importe": self._clean_value(r[3]) if len(r) > 3 else 0.0,
                    "tipo": r[4] if len(r) > 4 else "GASTO",
                }
                for r in last_n
            ]
        except Exception as e:
            print(f"❌ Error en get_recent_transactions: {e}")
            return []

    def get_top_categories(self, month: int = None, limit: int = 5) -> list:
        """Devuelve las categorías con mayor gasto en el mes indicado."""
        try:
            month = month or datetime.datetime.now().month
            month_col = self.month_columns.get(month, month + 2)
            col_b = self.matrix_sheet.col_values(2)
            col_data = self.matrix_sheet.col_values(month_col)

            gastos = []
            # Categorías de gasto: filas 11 a 19 (Vitales) y 23 a 37 (Ocio)
            expense_rows = list(range(11, 20)) + list(range(23, 38))
            for r in expense_rows:
                idx = r - 1
                cat = col_b[idx] if idx < len(col_b) else ""
                val = self._clean_value(col_data[idx]) if idx < len(col_data) else 0.0
                if cat and val > 0:
                    gastos.append({"categoria": cat, "total": val})

            gastos.sort(key=lambda x: x["total"], reverse=True)
            return gastos[:limit]
        except Exception as e:
            print(f"❌ Error en get_top_categories: {e}")
            return []

    def get_monthly_notes(self, month: int = None) -> dict:
        """
        Consulta las notas del mes (filas 61 a 72, columna B).
        """
        try:
            month = month or datetime.datetime.now().month
            row_idx = 60 + month  # Enero (1) -> 61, ..., Septiembre (9) -> 69
            month_name = self.MONTH_NAMES[month - 1]

            val = self.matrix_sheet.cell(row_idx, 2).value
            return {
                "month": month,
                "month_name": month_name,
                "notes": str(val or "").strip(),
            }
        except Exception as e:
            print(f"❌ Error en get_monthly_notes: {e}")
            return {"month": month, "month_name": "Mes actual", "notes": ""}

    def append_monthly_note(self, note_text: str, month: int = None) -> dict:
        """
        Añade una nota al final de la celda de notas del mes (filas 61 a 72, columna B).
        """
        try:
            month = month or datetime.datetime.now().month
            row_idx = 60 + month
            month_name = self.MONTH_NAMES[month - 1]

            current = str(self.matrix_sheet.cell(row_idx, 2).value or "").strip()
            if current.lower() == "none":
                current = ""
            clean_note = note_text.strip()
            if not clean_note:
                return {"success": False, "error": "El texto de la nota está vacío."}

            if current:
                new_val = f"{current} | {clean_note}"
            else:
                new_val = clean_note

            self.matrix_sheet.update_cell(row_idx, 2, new_val)
            print(f"📝 Nota añadida a {month_name}: {clean_note}")
            return {
                "success": True,
                "month": month,
                "month_name": month_name,
                "notes": new_val,
                "added": clean_note,
            }
        except Exception as e:
            print(f"❌ Error en append_monthly_note: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    # COMPATIBILIDAD CON CÓDIGO ANTERIOR
    # ─────────────────────────────────────────────────────────────────────────

    def get_full_budget_data(self) -> dict:
        """Devuelve un dict simplificado para debug o compatibilidad previa."""
        m = datetime.datetime.now().month
        return {
            "resumen_mes_actual": self.get_monthly_summary(m),
            "patrimonio": self.get_patrimony(),
            "top_gastos": self.get_top_categories(m),
        }