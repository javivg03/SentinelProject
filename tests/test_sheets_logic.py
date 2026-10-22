import pytest
import os
import sys
import datetime
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sheets_connector import _normalize_text, SheetsConnector


def _make_connector(category_map=None, display_names=None, row_display=None, budget_limits=None):
    """
    Crea un SheetsConnector sin llamar a __init__ (sin tocar la API real de
    Google) para poder testear la lógica de escritura/lectura determinista
    con un matrix_sheet y transactions_sheet mockeados.
    """
    sc = SheetsConnector.__new__(SheetsConnector)
    sc.month_columns = {m: m + 2 for m in range(1, 13)}
    sc.category_map = category_map or {}
    sc.category_display_names = display_names or {}
    sc.row_display_name = row_display or {}
    sc.budget_limits = budget_limits or {}
    sc.matrix_sheet = MagicMock()
    sc.transactions_sheet = MagicMock()
    return sc


def test_normalize_text():
    assert _normalize_text("Nómina") == "nomina"
    assert _normalize_text("  Electricidad + Gas  ") == "electricidad + gas"
    assert _normalize_text("DCA MSCI WORLD (TR)") == "dca msci world (tr)"
    assert _normalize_text("Farmacia / Salud ") == "farmacia / salud"


def test_clean_value():
    # Instanciamos la clase sin llamar a __init__ para probar helper estático/puro
    sc = SheetsConnector.__new__(SheetsConnector)
    assert sc._clean_value("1.226,52 €") == 1226.52
    assert sc._clean_value("755,68") == 755.68
    assert sc._clean_value("40.00") == 40.0
    assert sc._clean_value(100) == 100.0
    assert sc._clean_value(None) == 0.0
    assert sc._clean_value("#ERROR!") == 0.0
    assert sc._clean_value("—") == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _parse_month / _get_month_col / _get_month_idx
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_month_valid_date():
    sc = _make_connector()
    assert sc._get_month_idx("2026-03-15") == 3
    assert sc._get_month_col("2026-03-15") == 5  # columna = mes + 2


def test_parse_month_out_of_range_falls_back_to_current_month():
    sc = _make_connector()
    current = datetime.datetime.now().month
    assert sc._get_month_idx("2026-13-01") == current


def test_parse_month_garbage_falls_back_to_current_month():
    sc = _make_connector()
    current = datetime.datetime.now().month
    assert sc._get_month_idx("fecha-invalida") == current


# ─────────────────────────────────────────────────────────────────────────────
# log_expense — acumulación, nombre canónico y manejo de errores
# ─────────────────────────────────────────────────────────────────────────────

def test_log_expense_accumulates_and_writes_audit_log():
    sc = _make_connector(
        category_map={"comer fuera": 10},
        display_names={"comer fuera": "Comer fuera"},
        row_display={10: "Comer fuera"},
    )
    sc.matrix_sheet.cell.return_value.value = "10,00"

    result = sc.log_expense("Cena", "Comer fuera", "20,00")

    assert result["success"] is True
    assert result["new_total"] == 30.0
    assert result["category"] == "Comer fuera"

    row, col, new_val = sc.matrix_sheet.update_cell.call_args[0]
    assert (row, col, new_val) == (10, sc.month_columns[datetime.datetime.now().month], 30.0)

    sc.transactions_sheet.append_row.assert_called_once()
    audit_row = sc.transactions_sheet.append_row.call_args[0][0]
    assert audit_row[2] == "Comer fuera"
    assert audit_row[3] == 20.0


def test_log_expense_normalizes_category_label_for_audit_log():
    """
    Un botón manual (u otra vía) puede mandar 'Farmacia' aunque la fila real
    del Sheet se llame 'Farmacia / Salud'. El log de auditoría debe guardar
    siempre el nombre canónico, no la etiqueta de entrada.
    """
    sc = _make_connector(
        category_map={"farmacia / salud": 15, "farmacia": 15},
        display_names={"farmacia / salud": "Farmacia / Salud"},
        row_display={15: "Farmacia / Salud"},
    )
    sc.matrix_sheet.cell.return_value.value = "0"

    result = sc.log_expense("Ibuprofeno", "Farmacia", "6,50")

    assert result["category"] == "Farmacia / Salud"
    audit_row = sc.transactions_sheet.append_row.call_args[0][0]
    assert audit_row[2] == "Farmacia / Salud"


def test_log_expense_budget_alert_uses_canonical_name():
    sc = _make_connector(
        category_map={"gasolina": 12},
        display_names={"gasolina": "Gasolina"},
        row_display={12: "Gasolina"},
        budget_limits={"gasolina": 50.0},
    )
    sc.matrix_sheet.cell.return_value.value = "45,00"

    result = sc.log_expense("Repsol", "Gasolina", "10")

    assert result["new_total"] == 55.0
    assert result["budget_alert"] is not None
    assert "Gasolina" in result["budget_alert"]


def test_log_expense_handles_exception_gracefully():
    sc = _make_connector(category_map={"otros": 31}, row_display={31: "Otros"})
    sc.matrix_sheet.cell.side_effect = RuntimeError("API caída")

    result = sc.log_expense("Compra rara", "Otros", "5")

    assert result["success"] is False
    assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# batch_log_expenses — agregación por (fila, mes) y manejo de errores
# ─────────────────────────────────────────────────────────────────────────────

def test_batch_log_expenses_aggregates_same_category_and_month():
    sc = _make_connector(
        category_map={"supermercado": 11},
        row_display={11: "Supermercado"},
    )
    sc.matrix_sheet.cell.return_value.value = "0"

    items = [
        {"concepto": "Mercadona", "categoria": "Supermercado", "importe": 20, "fecha": "2026-09-01"},
        {"concepto": "Carrefour", "categoria": "supermercado", "importe": 15, "fecha": "2026-09-05"},
    ]

    total = sc.batch_log_expenses(items)

    assert total == 2
    sc.transactions_sheet.append_rows.assert_called_once()
    rows = sc.transactions_sheet.append_rows.call_args[0][0]
    assert all(r[2] == "Supermercado" for r in rows)

    sc.matrix_sheet.update_cells.assert_called_once()
    cells = sc.matrix_sheet.update_cells.call_args[0][0]
    assert len(cells) == 1
    assert cells[0].value == 35.0


def test_batch_log_expenses_handles_exception_gracefully():
    sc = _make_connector(category_map={"otros": 31}, row_display={31: "Otros"})
    sc.matrix_sheet.cell.side_effect = RuntimeError("fallo de red")

    total = sc.batch_log_expenses([{"concepto": "X", "categoria": "Otros", "importe": 5}])

    assert total == 0


def test_batch_log_expenses_empty_list_is_noop():
    sc = _make_connector()
    assert sc.batch_log_expenses([]) == 0
    sc.matrix_sheet.update_cells.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# _validate_matrix_layout — aviso no fatal si la estructura del Sheet cambió
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_matrix_layout_warns_on_mismatch(capsys):
    sc = _make_connector()
    sc.matrix_sheet.col_values.return_value = []  # ninguna etiqueta esperada aparecerá

    sc._validate_matrix_layout()

    captured = capsys.readouterr()
    assert "ALERTA DE INTEGRIDAD" in captured.out


# ─────────────────────────────────────────────────────────────────────────────
# search_transactions — búsqueda de un movimiento concreto por concepto
# ─────────────────────────────────────────────────────────────────────────────

def _fake_transactions_rows():
    return [
        ["Fecha", "Concepto", "Categoría", "Importe", "Tipo"],  # cabecera
        ["2026-06-15", "Entrada Hard GZ", "Fiesta", "35", "GASTO"],
        ["2026-07-02", "Mercadona", "Supermercado", "42,50", "GASTO"],
        ["2026-09-10", "Zara camisa", "Ropa", "29,99", "GASTO"],
    ]


def test_search_transactions_finds_match_case_and_accent_insensitive():
    sc = _make_connector()
    sc.transactions_sheet.get_all_values.return_value = _fake_transactions_rows()

    results = sc.search_transactions("hard gz")

    assert len(results) == 1
    assert results[0]["concepto"] == "Entrada Hard GZ"
    assert results[0]["importe"] == 35.0
    assert results[0]["fecha"] == "2026-06-15"


def test_search_transactions_no_match_returns_empty_list():
    sc = _make_connector()
    sc.transactions_sheet.get_all_values.return_value = _fake_transactions_rows()

    assert sc.search_transactions("netflix") == []


def test_search_transactions_most_recent_first():
    sc = _make_connector()
    sc.transactions_sheet.get_all_values.return_value = [
        ["Fecha", "Concepto", "Categoría", "Importe", "Tipo"],
        ["2026-01-01", "Zara pantalón", "Ropa", "20", "GASTO"],
        ["2026-09-01", "Zara camisa", "Ropa", "30", "GASTO"],
    ]

    results = sc.search_transactions("zara")

    assert [r["concepto"] for r in results] == ["Zara camisa", "Zara pantalón"]


def test_search_transactions_handles_exception_gracefully():
    sc = _make_connector()
    sc.transactions_sheet.get_all_values.side_effect = RuntimeError("fallo de red")

    assert sc.search_transactions("algo") is None


def test_search_transactions_no_transactions_sheet_returns_empty():
    sc = _make_connector()
    sc.transactions_sheet = None

    assert sc.search_transactions("algo") == []


# ─────────────────────────────────────────────────────────────────────────────
# delete_monthly_note — borrar una nota concreta por palabra clave
# ─────────────────────────────────────────────────────────────────────────────

def test_delete_monthly_note_removes_matching_bullet():
    sc = _make_connector()
    sc.matrix_sheet.cell.return_value.value = "No pagado spoti marta | Pendiente fianza 25€"

    result = sc.delete_monthly_note("fianza", month=9)

    assert result["success"] is True
    assert result["removed"] == ["Pendiente fianza 25€"]
    assert result["notes"] == "No pagado spoti marta"
    row, col, new_val = sc.matrix_sheet.update_cell.call_args[0]
    assert (row, col, new_val) == (69, 2, "No pagado spoti marta")


def test_delete_monthly_note_removes_all_matches():
    sc = _make_connector()
    sc.matrix_sheet.cell.return_value.value = "Gym HSN 47,75 | Gym febrero pendiente | Otra nota"

    result = sc.delete_monthly_note("gym", month=9)

    assert result["success"] is True
    assert set(result["removed"]) == {"Gym HSN 47,75", "Gym febrero pendiente"}
    assert result["notes"] == "Otra nota"


def test_delete_monthly_note_no_match_reports_error_without_writing():
    sc = _make_connector()
    sc.matrix_sheet.cell.return_value.value = "No pagado spoti marta"

    result = sc.delete_monthly_note("inexistente", month=9)

    assert result["success"] is False
    assert "error" in result
    sc.matrix_sheet.update_cell.assert_not_called()


def test_delete_monthly_note_empty_notes_reports_error():
    sc = _make_connector()
    sc.matrix_sheet.cell.return_value.value = ""

    result = sc.delete_monthly_note("fianza", month=9)

    assert result["success"] is False
    assert "error" in result


def test_delete_monthly_note_handles_exception_gracefully():
    sc = _make_connector()
    sc.matrix_sheet.cell.side_effect = RuntimeError("fallo de red")

    result = sc.delete_monthly_note("fianza", month=9)

    assert result["success"] is False
    assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# get_section_breakdown — desglose de una sección (Vitales/Ocio/Inversión)
# ─────────────────────────────────────────────────────────────────────────────

def _build_col(values_by_row, length=45):
    col = [""] * length
    for row, val in values_by_row.items():
        if row - 1 < length:
            col[row - 1] = val
    return col


def test_get_section_breakdown_vitales():
    sc = _make_connector()
    col_b = _build_col({11: "Alquiler", 12: "Facturas", 15: "Supermercado"})
    col_data = _build_col({11: "500", 12: "80", 15: "120,50"})
    sc.matrix_sheet.col_values.side_effect = lambda col: col_b if col == 2 else col_data

    result = sc.get_section_breakdown("vitales", month=9)

    assert result["section_name"] == "Gastos Vitales"
    cats = {it["categoria"]: it["total"] for it in result["items"] if it["total"] > 0}
    assert cats == {"Alquiler": 500.0, "Facturas": 80.0, "Supermercado": 120.5}
    assert result["total"] == 700.5


def test_get_section_breakdown_unknown_section_reports_error():
    sc = _make_connector()
    result = sc.get_section_breakdown("inexistente")
    assert "error" in result


def test_get_section_breakdown_handles_exception_gracefully():
    sc = _make_connector()
    sc.matrix_sheet.col_values.side_effect = RuntimeError("fallo de red")
    result = sc.get_section_breakdown("vitales")
    assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# get_expenses_breakdown — desglose completo de gastos (Vitales + Ocio)
# ─────────────────────────────────────────────────────────────────────────────

def test_get_expenses_breakdown():
    sc = _make_connector()
    col_b = _build_col({11: "Alquiler", 15: "Supermercado", 22: "Comer fuera", 25: "Viajes"})
    col_data = _build_col({11: "325", 15: "100", 22: "50", 25: "170"})
    sc.matrix_sheet.col_values.side_effect = lambda col: col_b if col == 2 else col_data

    result = sc.get_expenses_breakdown(month=10)

    assert result["month"] == 10
    assert result["vitales"]["total"] == 425.0
    assert result["ocio"]["total"] == 220.0
    assert result["total_gastos"] == 645.0
    vit_non_zero = [it for it in result["vitales"]["items"] if it["total"] > 0]
    assert len(vit_non_zero) == 2
    ocio_non_zero = [it for it in result["ocio"]["items"] if it["total"] > 0]
    assert len(ocio_non_zero) == 2


def test_get_top_categories_uses_correct_rows():
    sc = _make_connector()
    col_b = _build_col({11: "Alquiler", 19: "Total Vitales", 22: "Comer fuera"})
    col_data = _build_col({11: "300", 19: "9999", 22: "150"})
    sc.matrix_sheet.col_values.side_effect = lambda col: col_b if col == 2 else col_data

    result = sc.get_top_categories(month=10, limit=5)
    cats = [it["categoria"] for it in result]
    assert "Alquiler" in cats
    assert "Comer fuera" in cats
    assert "Total Vitales" not in cats


# ─────────────────────────────────────────────────────────────────────────────
# get_yearly_average — promedio de ingresos/gastos en lo que va de año
# ─────────────────────────────────────────────────────────────────────────────

def _build_row(values_by_col, length=15):
    row = [""] * length
    for col, val in values_by_col.items():
        if col - 1 < length:
            row[col - 1] = val
    return row


def test_get_yearly_average_uses_only_months_with_income():
    sc = _make_connector()
    row_ingresos = _build_row({3: "3000", 4: "3200"})  # Enero=col3, Febrero=col4
    row_vitales = _build_row({3: "800", 4: "850"})
    row_ocio = _build_row({3: "400", 4: "420"})

    def row_values_side_effect(row_idx):
        if row_idx == sc.ROW_TOTAL_INGRESOS:
            return row_ingresos
        if row_idx == sc.ROW_TOTAL_VITALES:
            return row_vitales
        if row_idx == sc.ROW_TOTAL_OCIO:
            return row_ocio
        return []

    sc.matrix_sheet.row_values.side_effect = row_values_side_effect

    result = sc.get_yearly_average(upto_month=9)

    assert result["meses_computados"] == 2
    assert result["media_ingresos"] == 3100.0
    assert result["media_gastos"] == 1235.0
    assert result["media_ahorro"] == 1865.0


def test_get_yearly_average_no_months_with_data():
    sc = _make_connector()
    sc.matrix_sheet.row_values.return_value = []

    result = sc.get_yearly_average(upto_month=9)

    assert result["meses_computados"] == 0
    assert result["media_ingresos"] == 0.0


def test_get_yearly_average_handles_exception_gracefully():
    sc = _make_connector()
    sc.matrix_sheet.row_values.side_effect = RuntimeError("fallo de red")

    result = sc.get_yearly_average(upto_month=9)
    assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# get_monthly_summary — regresión: la tasa de ahorro no debe multiplicarse x100
# ─────────────────────────────────────────────────────────────────────────────

def test_get_monthly_summary_tasa_ahorro_not_double_scaled():
    """
    La celda de Sheets ya viene formateada como porcentaje (ej. "29,3%" ->
    _clean_value la deja en 29.3). Multiplicarla otra vez por 100 daba
    tasas absurdas como 2930%.
    """
    sc = _make_connector()
    col_data = _build_col(
        {
            sc.ROW_TOTAL_INGRESOS: "2369,49",
            sc.ROW_TOTAL_VITALES: "811,57",
            sc.ROW_TOTAL_OCIO: "702,58",
            sc.ROW_TOTAL_INVERSION: "160",
            sc.ROW_AHORRO_NETO: "695,34",
            sc.ROW_TASA_AHORRO: "29,3%",
        },
        length=60,
    )
    sc.matrix_sheet.col_values.return_value = col_data

    result = sc.get_monthly_summary(month=9)

    assert result["tasa_ahorro"] == 29.3
