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
