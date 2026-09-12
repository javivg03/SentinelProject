import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sanitizer import DataSanitizer


def test_sanitize_iban():
    sanitizer = DataSanitizer()
    text = "Mi IBAN es ES1234567890123456789012 y quiero gastar 10€"
    result = sanitizer.clean(text)
    assert "ES1234567890123456789012" not in result
    assert "[REDACTED:IBAN]" in result


def test_sanitize_email():
    sanitizer = DataSanitizer()
    text = "hola@test.com gastó 20€"
    result = sanitizer.clean(text)
    assert "hola@test.com" not in result
    assert "[REDACTED:EMAIL]" in result


def test_sanitize_credit_card():
    sanitizer = DataSanitizer()
    text = "Pagué con la tarjeta 1234-5678-9012-3456 en amazon"
    result = sanitizer.clean(text)
    assert "1234-5678-9012-3456" not in result
    assert "[REDACTED:CREDIT_CARD]" in result


def test_sanitize_iban_with_spaces():
    """Los bancos casi siempre exportan el IBAN separado en grupos de 4."""
    sanitizer = DataSanitizer()
    text = "Titular IBAN ES50 2100 0813 1102 0012 3456 activo"
    result = sanitizer.clean(text)
    assert "2100 0813" not in result
    assert "[REDACTED:IBAN]" in result


def test_sanitize_credit_card_no_separators():
    sanitizer = DataSanitizer()
    text = "Tarjeta 1234567890123456 usada ayer"
    result = sanitizer.clean(text)
    assert "1234567890123456" not in result
    assert "[REDACTED:CREDIT_CARD]" in result


def test_sanitize_amex_card():
    """American Express usa agrupación 4-6-5, distinta de Visa/Mastercard."""
    sanitizer = DataSanitizer()
    text = "Amex 3714 496353 98431 cargo"
    result = sanitizer.clean(text)
    assert "3714 496353 98431" not in result
    assert "[REDACTED:CREDIT_CARD]" in result


def test_sanitize_phone_with_spaces_and_prefix():
    sanitizer = DataSanitizer()
    text = "Llámame al +34 612 34 56 78 cuando puedas"
    result = sanitizer.clean(text)
    assert "612 34 56 78" not in result
    assert "+34" not in result
    assert "[REDACTED:PHONE]" in result


def test_sanitize_phone_compact():
    sanitizer = DataSanitizer()
    text = "Mi numero es 612345678 fijo"
    result = sanitizer.clean(text)
    assert "612345678" not in result
    assert "[REDACTED:PHONE]" in result


def test_sanitize_empty_and_none():
    sanitizer = DataSanitizer()
    assert sanitizer.clean("") == ""
    assert sanitizer.clean(None) == ""
