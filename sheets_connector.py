import gspread
import os
import json
import datetime
import traceback
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()


class SheetsConnector:
    """
    Conector con Google Sheets para el proyecto Sentinel.

    Gestiona autenticación dual (local / nube), mapeo de categorías y meses,
    y ofrece operaciones tanto de escritura (log de gastos) como de lectura
    (consultas financieras del usuario).

    Pestañas gestionadas:
    - "Presupuesto"    → Totales mensuales por categoría (escritura acumulativa)
    - "Transacciones"  → Log individual de cada movimiento (append-only)
    """

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(self):
        try:
            # ── Autenticación dual: local vs. producción (Render) ──────────
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

            # ── Libro de cálculo ───────────────────────────────────────────
            spreadsheet_id = os.getenv("SPREADSHEET_ID")
            if not spreadsheet_id:
                raise ValueError("❌ La variable 'SPREADSHEET_ID' no está definida.")

            self.spreadsheet = self.client.open_by_key(spreadsheet_id)
            self.sheet = self.spreadsheet.worksheet("Presupuesto")

            # ── Pestaña de Transacciones (log individual, append-only) ─────
            try:
                self.transactions_sheet = self.spreadsheet.worksheet("Transacciones")
            except gspread.exceptions.WorksheetNotFound:
                self.transactions_sheet = self.spreadsheet.add_worksheet(
                    title="Transacciones", rows="5000", cols="5"
                )
                self.transactions_sheet.append_row(
                    ["Fecha", "Concepto", "Categoría", "Importe", "Tipo"]
                )
                print("✨ Pestaña 'Transacciones' creada automáticamente.")

            # ── Índices en caché para evitar lecturas repetitivas ──────────
            # Mes -> columna: Enero=col 2 (B), Febrero=col 3 (C), ...
            self.month_columns = {m: m + 1 for m in range(1, 13)}

            # Categoría (lowercase) -> número de fila (1-indexed)
            categories = self.sheet.col_values(1)
            self.category_map = {
                val.strip().lower(): i + 1
                for i, val in enumerate(categories)
                if val.strip()
            }

            print(
                f"✅ Conexión establecida con '{self.spreadsheet.title}'. "
                f"Categorías cacheadas: {len(self.category_map)}"
            )

        except Exception as e:
            print(f"❌ Error crítico en SheetsConnector: {e}")
            traceback.print_exc()
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS PRIVADOS
    # ─────────────────────────────────────────────────────────────────────────

    def _clean_value(self, val) -> float:
        """
        Normaliza un valor de celda (puede ser texto con '€', comas, espacios)
        a un float positivo operable.
        """
        if val is None or str(val).strip() == "":
            return 0.0
        try:
            sanitized = (
                str(val)
                .replace("€", "")
                .replace(" ", "")
                .replace(",", ".")
                .strip()
            )
            return abs(float(sanitized))
        except ValueError:
            return 0.0

    def _get_month_col(self, fecha_str: str = None) -> int:
        """
        Devuelve el número de columna del mes.
        Acepta fecha en formato 'YYYY-MM-DD' o 'YYYY-MM'.
        Si no se proporciona, usa el mes actual.
        """
        if fecha_str:
            try:
                month = int(str(fecha_str).split("-")[1])
                return self.month_columns.get(month)
            except (IndexError, ValueError):
                pass
        return self.month_columns.get(datetime.datetime.now().month)

    def _today(self) -> str:
        """Devuelve la fecha actual en formato YYYY-MM-DD."""
        return datetime.datetime.now().strftime("%Y-%m-%d")

    # ─────────────────────────────────────────────────────────────────────────
    # ESCRITURA — log_expense y batch_log_expenses
    # ─────────────────────────────────────────────────────────────────────────

    def log_expense(
        self, concept: str, category: str, amount, fecha: str = None
    ) -> bool:
        """
        Registra una única transacción:
        1. Añade fila en la pestaña 'Transacciones' (log individual)
        2. Acumula el importe en la celda correspondiente de 'Presupuesto'

        Args:
            concept:  Nombre del gasto (ej: "Mercadona")
            category: Categoría exacta del Sheet (ej: "Supermercado")
            amount:   Importe (string o float, siempre se toma absoluto)
            fecha:    Fecha en formato YYYY-MM-DD o YYYY-MM (opcional)

        Returns:
            True si el registro fue exitoso, False en caso de error.
        """
        try:
            col = self._get_month_col(fecha)
            clean_category = category.strip().lower()
            target_row = self.category_map.get(clean_category, -1)

            if target_row == -1:
                print(f"⚠️ Categoría '{category}' no encontrada. Abortando registro.")
                return False

            amount_to_add = self._clean_value(amount)
            timestamp = fecha if fecha else self._today()

            # 1. Log individual en Transacciones
            tipo = "INGRESO" if clean_category == "nómina" else "GASTO"
            self.transactions_sheet.append_row(
                [timestamp, concept, category, amount_to_add, tipo]
            )

            # 2. Acumular en Presupuesto
            current_val = self._clean_value(self.sheet.cell(target_row, col).value)
            new_total = round(current_val + amount_to_add, 2)
            self.sheet.update_cell(target_row, col, new_total)

            print(f"💰 Registro exitoso: {category} | {current_val}€ → {new_total}€")
            return True

        except Exception as e:
            print(f"❌ Error al registrar gasto en Sheets: {e}")
            return False

    def batch_log_expenses(self, parsed_items: list) -> int:
        """
        Registra una lista de movimientos en bloque (extracción de documentos bancarios).

        Estrategia de eficiencia (minimizar llamadas a la API de Google):
        1. Vuelca TODAS las filas de una vez a 'Transacciones' con append_rows()
        2. Agrupa los importes por (mes, categoría) y hace UNA sola escritura
           masiva a 'Presupuesto' con update_cells()

        Args:
            parsed_items: Lista de dicts con claves: concepto, categoria, importe,
                          fecha (opcional), tipo (opcional)

        Returns:
            Número de items procesados (o 0 si hubo error).
        """
        if not parsed_items:
            return 0

        try:
            # ── Paso 1: Volcar log individual a Transacciones ──────────────
            rows_to_append = []
            for item in parsed_items:
                fecha_log = item.get("fecha") or self._today()
                tipo = item.get("tipo", "GASTO")
                rows_to_append.append([
                    fecha_log,
                    item.get("concepto", "Sin concepto"),
                    item.get("categoria", "Otros"),
                    self._clean_value(item.get("importe", 0)),
                    tipo,
                ])

            if rows_to_append:
                self.transactions_sheet.append_rows(rows_to_append)
                print(f"📝 {len(rows_to_append)} transacciones registradas en el Log.")

            # ── Paso 2: Agregar importes por (mes, categoría) ──────────────
            aggregated = {}  # clave: (col_mes, fila_cat) → importe acumulado
            for item in parsed_items:
                cat = str(item.get("categoria", "")).strip().lower()
                amt = self._clean_value(item.get("importe", 0))
                col = self._get_month_col(item.get("fecha"))
                target_cat = cat if cat in self.category_map else "otros"
                target_row = self.category_map.get(target_cat)
                if target_row:
                    key = (col, target_row)
                    aggregated[key] = aggregated.get(key, 0.0) + amt

            if not aggregated:
                return 0

            # ── Paso 3: Leer valores actuales (1 lectura por columna) ──────
            cols_needed = {k[0] for k in aggregated}
            col_caches = {col: self.sheet.col_values(col) for col in cols_needed}

            # ── Paso 4: Preparar escritura masiva ─────────────────────────
            cells_to_update = []
            for (col, target_row), amount_to_add in aggregated.items():
                col_data = col_caches[col]
                current_val = (
                    self._clean_value(col_data[target_row - 1])
                    if target_row <= len(col_data)
                    else 0.0
                )
                new_total = round(current_val + amount_to_add, 2)
                cells_to_update.append(
                    gspread.Cell(row=target_row, col=col, value=new_total)
                )
                print(f"📦 Lote: fila {target_row} col {col} | {current_val}€ → {new_total}€")

            # ── Paso 5: Una sola llamada API para toda la escritura ────────
            self.sheet.update_cells(cells_to_update)
            print(f"✅ Batch completado: {len(parsed_items)} movimientos en {len(cells_to_update)} celdas.")

            return len(parsed_items)

        except Exception as e:
            print(f"❌ Error al insertar lote en Sheets: {e}")
            return 0

    # ─────────────────────────────────────────────────────────────────────────
    # LECTURA — Consultas financieras del usuario
    # ─────────────────────────────────────────────────────────────────────────

    def get_full_budget_data(self) -> dict:
        """
        Lee TODOS los datos del Sheet de Presupuesto (todas las categorías,
        todos los meses del año) y los devuelve como un dict estructurado.

        Este método es la base del sistema de consultas libre: en lugar de
        hacer múltiples llamadas a la API para cada mes/categoría, hacemos
        UNA sola lectura masiva y dejamos que Gemini interprete cualquier
        pregunta sobre los datos completos.

        Returns:
            {
                "Supermercado": {"Enero": 150.0, "Febrero": 200.0, ...},
                "Gasolina":     {"Enero": 40.0, ...},
                ...
            }
        """
        MONTH_NAMES = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
        ]
        try:
            all_values = self.sheet.get_all_values()
            budget = {}

            for row in all_values:
                if not row or not row[0].strip():
                    continue
                cat_name = row[0].strip()
                cat_data = {}
                for i, month in enumerate(MONTH_NAMES):
                    col_idx = i + 1  # Columna B en adelante
                    val = (
                        self._clean_value(row[col_idx])
                        if col_idx < len(row)
                        else 0.0
                    )
                    if val > 0:
                        cat_data[month] = val
                if cat_data:
                    budget[cat_name] = cat_data

            return budget

        except Exception as e:
            print(f"❌ Error en get_full_budget_data: {e}")
            return {}

    def query_category_total(self, category: str, month: int = None) -> float:
        """
        Devuelve el total gastado en una categoría durante el mes indicado
        (por defecto el mes actual).
        """
        try:
            month = month or datetime.datetime.now().month
            col = self.month_columns.get(month)
            target_row = self.category_map.get(category.strip().lower(), -1)
            if target_row == -1:
                return -1.0  # Categoría no existe
            return self._clean_value(self.sheet.cell(target_row, col).value)
        except Exception as e:
            print(f"❌ Error en query_category_total: {e}")
            return 0.0

    def query_monthly_totals(self, month: int = None) -> dict:
        """
        Devuelve un resumen completo del mes: ingresos, gastos totales por
        categoría y ahorro calculado.

        Returns:
            {
                "month": int,
                "income": float,
                "expenses": float,
                "savings": float,
                "by_category": {"Supermercado": 150.0, ...}
            }
        """
        try:
            month = month or datetime.datetime.now().month
            col = self.month_columns.get(month)
            col_data = self.sheet.col_values(col)
            categories = self.sheet.col_values(1)

            income = 0.0
            expenses = 0.0
            by_category = {}

            for i, cat_name in enumerate(categories):
                if not cat_name.strip():
                    continue
                val = self._clean_value(col_data[i]) if i < len(col_data) else 0.0
                if val == 0.0:
                    continue
                cat_lower = cat_name.strip().lower()
                by_category[cat_name.strip()] = val
                if cat_lower == "nómina":
                    income += val
                else:
                    expenses += val

            return {
                "month": month,
                "income": round(income, 2),
                "expenses": round(expenses, 2),
                "savings": round(income - expenses, 2),
                "by_category": by_category,
            }
        except Exception as e:
            print(f"❌ Error en query_monthly_totals: {e}")
            return {}

    def query_last_transactions(self, limit: int = 5) -> list:
        """
        Devuelve las últimas N transacciones del log individual ('Transacciones').

        Returns:
            Lista de dicts: [{"fecha": ..., "concepto": ..., "categoria": ...,
                               "importe": ..., "tipo": ...}]
        """
        try:
            all_rows = self.transactions_sheet.get_all_values()
            # La primera fila son cabeceras, ignorarla
            data_rows = all_rows[1:] if len(all_rows) > 1 else []
            last_n = data_rows[-limit:] if len(data_rows) >= limit else data_rows
            # Invertimos para mostrar las más recientes primero
            last_n = list(reversed(last_n))
            return [
                {
                    "fecha": row[0] if len(row) > 0 else "",
                    "concepto": row[1] if len(row) > 1 else "",
                    "categoria": row[2] if len(row) > 2 else "",
                    "importe": self._clean_value(row[3]) if len(row) > 3 else 0.0,
                    "tipo": row[4] if len(row) > 4 else "GASTO",
                }
                for row in last_n
            ]
        except Exception as e:
            print(f"❌ Error en query_last_transactions: {e}")
            return []

    def query_period_total(self, start_date: str, end_date: str) -> dict:
        """
        Devuelve el total de gastos e ingresos entre dos fechas (inclusive)
        consultando directamente la pestaña 'Transacciones'.

        Args:
            start_date: Fecha inicio en formato YYYY-MM-DD
            end_date:   Fecha fin en formato YYYY-MM-DD

        Returns:
            {"expenses": float, "income": float, "count": int}
        """
        try:
            all_rows = self.transactions_sheet.get_all_values()
            data_rows = all_rows[1:]  # Saltar cabecera

            start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

            expenses = 0.0
            income = 0.0
            count = 0

            for row in data_rows:
                if not row or not row[0]:
                    continue
                try:
                    # Intentamos parsear solo la parte de fecha (ignora hora si la hay)
                    row_date = datetime.datetime.strptime(
                        row[0][:10], "%Y-%m-%d"
                    ).date()
                except ValueError:
                    continue

                if start <= row_date <= end:
                    amount = self._clean_value(row[3]) if len(row) > 3 else 0.0
                    tipo = row[4].upper() if len(row) > 4 else "GASTO"
                    if tipo == "INGRESO":
                        income += amount
                    else:
                        expenses += amount
                    count += 1

            return {
                "expenses": round(expenses, 2),
                "income": round(income, 2),
                "count": count,
            }
        except Exception as e:
            print(f"❌ Error en query_period_total: {e}")
            return {"expenses": 0.0, "income": 0.0, "count": 0}

    def query_top_categories(self, month: int = None, top_n: int = 5) -> list:
        """
        Devuelve las N categorías con mayor gasto en el mes indicado,
        ordenadas de mayor a menor.

        Returns:
            [{"categoria": str, "total": float}, ...]
        """
        try:
            totals = self.query_monthly_totals(month)
            by_cat = totals.get("by_category", {})
            # Excluir Nómina del ranking de "más gastado"
            sorted_cats = sorted(
                [(k, v) for k, v in by_cat.items() if k.lower() != "nómina"],
                key=lambda x: x[1],
                reverse=True,
            )
            return [
                {"categoria": cat, "total": total}
                for cat, total in sorted_cats[:top_n]
            ]
        except Exception as e:
            print(f"❌ Error en query_top_categories: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # APRENDIZAJE CONTINUO — Para uso futuro (Fase 3)
    # ─────────────────────────────────────────────────────────────────────────

    def calculate_dynamic_thresholds(self) -> dict:
        """
        Calcula la media aritmética de gasto mensual en categorías críticas
        (ocio, alcohol, tabaco, fiesta, restaurantes) para detectar desviaciones.

        Preparado para la Fase 3 del roadmap (Umbrales Dinámicos).
        """
        try:
            print("📊 Calculando umbrales dinámicos...")
            all_values = self.sheet.get_all_values()
            keywords = ["ocio", "alcohol", "tabaco", "fiesta", "restaurante"]
            results = {}

            for row in all_values:
                if not row:
                    continue
                cat = str(row[0]).lower().strip()
                if any(k in cat for k in keywords):
                    numeric_vals = [
                        self._clean_value(val)
                        for val in row[1:]
                        if self._clean_value(val) > 0
                    ]
                    if numeric_vals:
                        media = sum(numeric_vals) / len(numeric_vals)
                        results[str(row[0])] = round(media, 2)

            print(f"🧠 Perfiles aprendidos: {results}")
            return results

        except Exception as e:
            print(f"❌ Error al calcular umbrales: {e}")
            return {}