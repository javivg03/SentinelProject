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
        MOCK DATA: Simulamos una conexión activa para evitar consumir la API real.
        """
        print("🔗 [MOCK] Solicitando conexiones activas...")
        return [{"id": "conn_mock_123", "status": "ACTIVE"}]

    def list_accounts(self, connection_id):
        """
        MOCK DATA: Simulamos cuentas bancarias.
        """
        print(f"🏦 [MOCK] Solicitando cuentas para la conexión {connection_id}...")
        return [{"id": "acc_mock_456", "name": "Cuenta Corriente Personal", "balance": 1500.50}]

    def fetch_transactions(self, connection_id, account_id):
        """
        MOCK DATA: Simulamos descargas de transacciones. 
        Esto servirá en el futuro para eventos Proactivos (Notificar de gastos en Ocio).
        """
        print(f"💸 [MOCK] Descargando transacciones de cuenta {account_id}...")
        return [
            {"amount": -50.0, "currency_code": "EUR", "description": "Compra Mercadona"},
            {"amount": -15.5, "currency_code": "EUR", "description": "UBER EATS"},
            {"amount": -120.0, "currency_code": "EUR", "description": "ZARA OCIO"}
        ]