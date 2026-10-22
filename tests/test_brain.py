import pytest
from unittest.mock import patch, MagicMock
import os
import sys

# Asegurar path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain import SentinelBrain


class MockResponse:
    def __init__(self, text):
        self.text = text


@patch("google.genai.Client")
def test_brain_success(mock_client_cls):
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_instance.models.generate_content.return_value = MockResponse(
        '{"movimientos": [{"concepto": "Cena", "categoria": "Comer fuera", "importe": 20}]}'
    )

    brain = SentinelBrain()
    res, status = brain.process_transaction("Me gasté 20 en cena")
    assert status == "SUCCESS"
    assert len(res) == 1
    assert res[0]["concepto"] == "Cena"
    assert res[0]["categoria"] == "Comer fuera"


@patch("google.genai.Client")
def test_brain_retries_on_malformed_json(mock_client_cls):
    """
    Gemini puede devolver un 200 OK con JSON ocasionalmente mal formado
    (glitch de generación, ej. con varios movimientos en un mensaje). Antes
    el parseo ocurría fuera del bloque con reintentos y el fallo se
    propagaba directo; ahora debe reintentar y recuperarse si el segundo
    intento sí es válido.
    """
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_instance.models.generate_content.side_effect = [
        MockResponse('{"movimientos": [{"concepto": "Gimnasio",'),  # JSON roto
        MockResponse('{"movimientos": [{"concepto": "Gimnasio", "categoria": "Gimnasio", "importe": 42.9}]}'),
    ]

    brain = SentinelBrain()
    res, status = brain.process_transaction("Gimnasio 42.9")

    assert status == "SUCCESS"
    assert res[0]["concepto"] == "Gimnasio"
    assert mock_instance.models.generate_content.call_count == 2


@patch("google.genai.Client")
def test_classify_intent_returns_error_when_gemini_fails_and_ambiguous(mock_client_cls):
    """
    Si Gemini falla (ej. cuota agotada) y el mensaje no encaja con ninguna
    palabra clave de consulta ni de registro, antes se asumía "log" a
    ciegas -> segundo intento fallido contra Gemini -> el bot se quedaba
    sin responder nada. Ahora debe admitir el fallo explícitamente.
    """
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_instance.models.generate_content.side_effect = RuntimeError(
        "429 RESOURCE_EXHAUSTED: quota exceeded"
    )

    brain = SentinelBrain()
    result = brain.classify_intent("Y de nomina")

    assert result["intent"] == "error"
    assert result["raw_message"] == "Y de nomina"


@patch("google.genai.Client")
def test_classify_intent_falls_back_to_query_heuristics_when_gemini_fails(mock_client_cls):
    """Si el mensaje sí encaja con palabras clave de consulta, se mantiene el fallback heurístico."""
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_instance.models.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED")

    brain = SentinelBrain()
    result = brain.classify_intent("¿Cuánto llevo de nómina?")

    assert result["intent"] == "query"
    assert result["query_type"] == "category_total"
    assert result["category"] == "Nómina"


@patch("google.genai.Client")
def test_brain_doubt(mock_client_cls):
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_instance.models.generate_content.return_value = MockResponse(
        '{"duda": "¿Qué importe pagaste?"}'
    )

    brain = SentinelBrain()
    res, status = brain.process_transaction("Pagué cena")
    assert status == "DOUBT"
    assert res == "¿Qué importe pagaste?"


@patch("google.genai.Client")
def test_deterministic_patrimony_format(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {
        "month_name": "Agosto",
        "cuenta_tr_remunerada": 5213.21,
        "fondo_msci_world": 1541.92,
        "bitcoin": 218.60,
        "cuenta_unicaja": 954.82,
        "patrimonio_total": 7928.55,
    }
    formatted = brain.format_query_response("patrimony", data)
    assert "7.928,55€" in formatted
    assert "5.213,21€" in formatted
    assert "1.541,92€" in formatted
    assert "218,60€" in formatted
    assert "954,82€" in formatted


@patch("google.genai.Client")
def test_deterministic_category_format(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {
        "category": "Gasolina",
        "spent": 40.0,
        "month_name": "Septiembre",
        "budget": 110.0,
    }
    formatted = brain.format_query_response("category_total", data)
    assert "Gasolina" in formatted
    assert "40,00€" in formatted
    assert "110,00€" in formatted


@patch("google.genai.Client")
def test_deterministic_income_breakdown(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {
        "month_name": "Agosto",
        "nomina": 3692.16,
        "otros": 235.50,
        "regalos_extras": 10.00,
        "total_ingresos": 3927.66,
    }
    formatted = brain.format_query_response("income_breakdown", data)
    assert "3.692,16€" in formatted
    assert "235,50€" in formatted
    assert "10,00€" in formatted
    assert "3.927,66€" in formatted


@patch("google.genai.Client")
def test_deterministic_notes_formatting(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    # Test get_notes with content
    data_notes = {
        "month_name": "Septiembre",
        "notes": "No pagado spoti marta | GYM: HSN 47,75-14 ali"
    }
    formatted = brain.format_query_response("get_notes", data_notes)
    assert "Septiembre" in formatted
    assert "• No pagado spoti marta" in formatted
    assert "• GYM: HSN 47,75-14 ali" in formatted

    # Test get_notes empty
    formatted_empty = brain.format_query_response("get_notes", {"month_name": "Octubre", "notes": ""})
    assert "No tienes notas registradas" in formatted_empty

    # Test add_note success
    data_added = {
        "success": True,
        "month_name": "Septiembre",
        "added": "Pendiente fianza 25€",
        "notes": "No pagado spoti marta | Pendiente fianza 25€"
    }
    formatted_add = brain.format_query_response("add_note", data_added)
    assert "Pendiente fianza 25€" in formatted_add
    assert "Nota registrada correctamente" in formatted_add


@patch("google.genai.Client")
def test_format_search_transaction_with_results(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = [
        {"fecha": "2026-06-15", "concepto": "Entrada Hard GZ", "categoria": "Fiesta", "importe": 35.0, "tipo": "GASTO"},
    ]
    formatted = brain.format_query_response("search_transaction", data)
    assert "Entrada Hard GZ" in formatted
    assert "35,00€" in formatted
    assert "2026-06-15" in formatted


@patch("google.genai.Client")
def test_format_search_transaction_no_results(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    formatted = brain.format_query_response("search_transaction", [])
    assert "No encontré ningún movimiento" in formatted


@patch("google.genai.Client")
def test_format_delete_note_success(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {
        "success": True,
        "month_name": "Septiembre",
        "removed": ["Pendiente fianza 25€"],
        "notes": "No pagado spoti marta",
    }
    formatted = brain.format_query_response("delete_note", data)
    assert "eliminada" in formatted.lower()
    assert "Pendiente fianza 25€" in formatted
    assert "No pagado spoti marta" in formatted


@patch("google.genai.Client")
def test_format_delete_note_failure(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {"success": False, "error": "No encontré ninguna nota que contenga 'x' en Septiembre."}
    formatted = brain.format_query_response("delete_note", data)
    assert "No pude borrar la nota" in formatted


@patch("google.genai.Client")
def test_format_add_note_business_failure_is_not_confused_with_connection_error(mock_client_cls):
    """
    Regresión: add_note/delete_note reportan sus propios fallos de negocio
    (nota vacía, no encontrada...) con {"success": False, "error": ...}. El
    chequeo genérico de "fallo de lectura de Sheets" no debe interceptarlos
    y mostrar un falso "error de conexión" en su lugar.
    """
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {"success": False, "error": "El texto de la nota está vacío."}
    formatted = brain.format_query_response("add_note", data)

    assert "Error al guardar la nota" in formatted
    assert "conexión" not in formatted.lower()


@patch("google.genai.Client")
def test_format_query_reports_read_failure_distinctly_from_zero(mock_client_cls):
    """El fallo de lectura de Sheets (dict SIN 'success') sí debe avisar de un error de conexión."""
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    formatted = brain.format_query_response("monthly_summary", {"error": "API caída"})
    assert "No pude leer tus datos" in formatted


@patch("google.genai.Client")
def test_format_monthly_expenses_shows_only_expense_total(mock_client_cls):
    """'Cuánto he gastado este mes' debe centrarse en el gasto, no dar el balance completo."""
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {
        "month_name": "Septiembre",
        "total_ingresos": 2369.49,
        "total_gastos_vitales": 811.57,
        "total_gastos_ocio": 693.68,
        "total_gastos": 1505.25,
        "ahorro_neto": 704.24,
        "tasa_ahorro": 29.7,
    }
    formatted = brain.format_query_response("monthly_expenses", data)

    assert "1.505,25€" in formatted
    assert "811,57€" in formatted
    assert "693,68€" in formatted
    # No debe mezclar el balance completo (ingresos/ahorro) en esta respuesta centrada en gasto
    assert "Ingresos" not in formatted
    assert "Ahorro" not in formatted


@patch("google.genai.Client")
def test_format_section_breakdown_with_expenses(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {
        "month_name": "Septiembre",
        "section_name": "Gastos Vitales",
        "items": [
            {"categoria": "Alquiler", "total": 500.0},
            {"categoria": "Supermercado", "total": 120.5},
            {"categoria": "Gimnasio", "total": 0.0},
        ],
        "total": 620.5,
    }
    formatted = brain.format_query_response("section_breakdown", data)

    assert "Alquiler" in formatted
    assert "500,00€" in formatted
    assert "Gimnasio" not in formatted  # categorías sin gasto no deben listarse
    assert "620,50€" in formatted


@patch("google.genai.Client")
def test_format_section_breakdown_empty_section(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {"month_name": "Octubre", "section_name": "Ocio y Extras", "items": [], "total": 0.0}
    formatted = brain.format_query_response("section_breakdown", data)

    assert "No hay gastos registrados" in formatted


@patch("google.genai.Client")
def test_format_yearly_average_with_data(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {
        "meses_computados": 2,
        "media_ingresos": 3100.0,
        "media_gastos": 1235.0,
        "media_ahorro": 1865.0,
    }
    formatted = brain.format_query_response("yearly_average", data)

    assert "3.100,00€" in formatted
    assert "1.235,00€" in formatted
    assert "1.865,00€" in formatted
    assert "2 meses" in formatted


@patch("google.genai.Client")
def test_format_yearly_average_no_data_yet(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {"meses_computados": 0, "media_ingresos": 0.0, "media_gastos": 0.0, "media_ahorro": 0.0}
    formatted = brain.format_query_response("yearly_average", data)

    assert "Todavía no hay suficientes meses" in formatted


@patch("google.genai.Client")
def test_format_expenses_breakdown(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    brain = SentinelBrain()

    data = {
        "month_name": "Octubre",
        "vitales": {
            "section_name": "Gastos Vitales",
            "items": [
                {"categoria": "Alquiler", "total": 325.0},
                {"categoria": "Farmacia / Salud", "total": 64.76},
            ],
            "total": 389.76,
        },
        "ocio": {
            "section_name": "Ocio y Extras",
            "items": [
                {"categoria": "Viajes", "total": 170.0},
                {"categoria": "Fiesta", "total": 75.15},
                {"categoria": "Clases particulares", "total": 70.0},
            ],
            "total": 315.15,
        },
        "total_gastos": 704.91,
    }
    formatted = brain.format_query_response("expenses_breakdown", data)

    assert "Desglose de Gastos — Octubre" in formatted
    assert "Gastos Vitales:" in formatted
    assert "Alquiler: 325,00€" in formatted
    assert "Subtotal Vitales: 389,76€" in formatted
    assert "Ocio y Extras:" in formatted
    assert "Viajes: 170,00€" in formatted
    assert "Subtotal Ocio: 315,15€" in formatted
    assert "Total Gastos:" in formatted
    assert "704,91€" in formatted



