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
    sc = _make_connector(category_map={"otros": 32}, row_display={32: "Otros"})
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
    sc = _make_connector(category_map={"otros": 32}, row_display={32: "Otros"})
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
