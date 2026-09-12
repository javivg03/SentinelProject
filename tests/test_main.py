import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# main.py instancia SentinelBrain/SheetsConnector/DataSanitizer a nivel de
# módulo (líneas 1 vez al arrancar). Se mockean ANTES de importar para poder
# testear la lógica de autorización sin credenciales reales de Google/Gemini.
with patch("brain.SentinelBrain"), patch("sheets_connector.SheetsConnector"), patch("sanitizer.DataSanitizer"):
    import main


def _fake_update(chat_id):
    update = MagicMock()
    update.effective_chat.id = chat_id
    return update


def test_is_authorized_true_when_chat_id_matches(monkeypatch):
    monkeypatch.setattr(main, "ALLOWED_CHAT_ID", "12345")
    assert main._is_authorized(_fake_update(12345)) is True
    assert main._is_authorized(_fake_update("12345")) is True


def test_is_authorized_false_when_chat_id_differs(monkeypatch):
    monkeypatch.setattr(main, "ALLOWED_CHAT_ID", "12345")
    assert main._is_authorized(_fake_update(99999)) is False


def test_is_authorized_false_when_not_configured():
    """
    Sin ALLOWED_CHAT_ID configurado, Sentinel debe rechazar a todo el mundo
    por defecto (fail-closed) en vez de aceptar a cualquiera.
    """
    with patch.object(main, "ALLOWED_CHAT_ID", None):
        assert main._is_authorized(_fake_update(12345)) is False


def test_is_authorized_false_without_effective_chat(monkeypatch):
    monkeypatch.setattr(main, "ALLOWED_CHAT_ID", "12345")
    update = MagicMock()
    update.effective_chat = None
    assert main._is_authorized(update) is False
