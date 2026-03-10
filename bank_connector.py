import httpx
import os

class BankConnector:
    def __init__(self):
        # Usamos las nuevas variables de Tink que pusiste en Render
        self.client_id = os.getenv("TINK_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("TINK_CLIENT_SECRET", "").strip()
        self.base_url = "https://api.tink.com/api/v1"
        # URL base para conectar cuentas (Tink Link)
        self.auth_url = "https://link.tink.com/1.0/transactions/connect-accounts"

    def create_connect_session(self, redirect_url):
        """Genera el enlace de Tink Link para conectar bancos reales."""
        # Tink no necesita crear una sesión previa por API como Salt Edge,
        # se puede generar la URL directamente con tus parámetros.
        params = {
            "client_id": self.client_id,
            "redirect_uri": f"{redirect_url}/callback",
            "market": "ES",
            "locale": "es_ES",
            "test": "true" # Mantenlo en 'true' para probar bancos fake de Tink primero
        }
        # Construimos la URL de conexión
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{self.auth_url}?{query}"

    def list_connections(self):
        """
        NOTA: En Tink el flujo es un poco distinto. 
        Primero conectamos y luego pedimos permiso para leer.
        De momento, con que nos genere el enlace vamos bien.
        """
        return []