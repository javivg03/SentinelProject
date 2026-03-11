import pytest
import google.generativeai as genai
from unittest.mock import patch
from brain import SentinelBrain

class MockResponse:
    def __init__(self, text):
        self.text = text

# Saltamos el chequeo real de la apikey para poder testear sin conexión
@patch('google.generativeai.configure')
@patch('google.generativeai.GenerativeModel.generate_content')
def test_brain_success(mock_generate, mock_configure):
    mock_generate.return_value = MockResponse('{"movimientos": [{"concepto": "Cena", "categoria": "Ocio", "importe": 20}]}')
    
    # Inyectamos una API KEY falsa al entorno para que no falle la inicializacion
    import os
    os.environ["GOOGLE_API_KEY"] = "fake-key"
    
    brain = SentinelBrain()
    res, status = brain.process_transaction("Me gasté 20 en cena")
    assert status == "SUCCESS"
    assert len(res) == 1
    assert res[0]["concepto"] == "Cena"

@patch('google.generativeai.configure')
@patch('google.generativeai.GenerativeModel.generate_content')
def test_brain_doubt(mock_generate, mock_configure):
    mock_generate.return_value = MockResponse('{"duda": "¿Qué moneda usaste?"}')
    
    import os
    os.environ["GOOGLE_API_KEY"] = "fake-key"
    
    brain = SentinelBrain()
    res, status = brain.process_transaction("Me gasté 20")
    assert status == "DOUBT"
    assert res == "¿Qué moneda usaste?"
