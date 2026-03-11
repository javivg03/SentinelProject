import pytest
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
