import re


class DataSanitizer:
    """
    Filtro de privacidad Zero-Trust para Sentinel.

    Elimina datos personales sensibles de cualquier texto antes de que
    salga del servidor hacia APIs de terceros (Google Gemini).

    Los datos detectados se sustituyen por un placeholder legible:
    [REDACTED:TIPO] — así la IA sabe que había un dato pero no puede leerlo.

    Patrones detectados:
    - IBAN      : Números de cuenta bancaria europeos (ej: ES50 2103 ...)
    - CREDIT_CARD: Grupos de 4 dígitos típicos de tarjetas
    - EMAIL     : Direcciones de correo electrónico
    - DNI       : DNI español (8 dígitos + letra)
    - PHONE     : Teléfonos móviles españoles (+34, 6xx, 7xx, 8xx, 9xx)
    """

    # Cada patrón está compilado una sola vez al instanciar la clase
    # para máximo rendimiento en procesamiento de documentos largos.
    PATTERNS = {
        "IBAN": re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}"),
        "CREDIT_CARD": re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
        "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "DNI": re.compile(r"\b\d{8}[A-Za-z]\b"),
        "PHONE": re.compile(r"\b(\+34|0034)?[6789]\d{8}\b"),
    }

    def clean(self, text: str) -> str:
        """
        Sanitiza el texto sustituyendo datos sensibles por placeholders.

        Args:
            text: Texto original (puede ser texto natural o volcado bancario)

        Returns:
            Texto con todos los datos sensibles redactados.
            Devuelve string vacío si el input es None o vacío.
        """
        if not text:
            return ""

        sanitized = text
        for label, pattern in self.PATTERNS.items():
            sanitized = pattern.sub(f"[REDACTED:{label}]", sanitized)

        return sanitized.strip()