import re

class DataSanitizer:
    def __init__(self):
        self.patterns = {
            'IBAN': r'ES\d{22}',
            'CREDIT_CARD': r'\b(?:\d{4}[ -]?){3}\d{4}\b',
            'EMAIL': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            'DNI': r'\b\d{8}[A-Za-z]\b'
        }

    def clean(self, text: str) -> str:
        if not text: return ""
        sanitized_text = text
        for label, pattern in self.patterns.items():
            sanitized_text = re.sub(pattern, f"[REDACTED:{label}]", sanitized_text)
        return sanitized_text.strip()