import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sheets_connector import _normalize_text, SheetsConnector


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
