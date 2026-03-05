import httpx
import os

class BankConnector:
    def __init__(self):
        self.app_id = os.getenv("SALTEDGE_APP_ID", "").strip()
        self.secret = os.getenv("SALTEDGE_SECRET", "").strip()
        self.customer_id = os.getenv("SALTEDGE_CUSTOMER_ID", "").strip()
        self.base_url = "https://www.saltedge.com/api/v6"
        
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "App-id": self.app_id,
            "Secret": self.secret
        }

    def create_connect_session(self, redirect_url):
        url = f"{self.base_url}/connections/connect"
        payload = {
            "data": {
                "customer_id": self.customer_id,
                "consent": {
                    "scopes": ["accounts", "transactions"]
                },
                "attempt": {
                    "return_to": redirect_url.strip()
                }
            }
        }
        try:
            response = httpx.post(url, json=payload, headers=self.headers)
            if response.status_code != 200:
                print(f"❌ Detalle del error Salt Edge: {response.text}")
            response.raise_for_status()
            return response.json().get("data", {}).get("connect_url")
        except Exception as e:
            print(f"❌ Error en Salt Edge v6: {e}")
            return None

    def list_connections(self):
        """Obtiene todas las conexiones bancarias del cliente."""
        url = f"{self.base_url}/connections?customer_id={self.customer_id}"
        try:
            response = httpx.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json().get("data", [])
        except Exception as e:
            print(f"❌ Error listando conexiones: {e}")
            return []

    def list_accounts(self, connection_id):
        """Obtiene las cuentas de una conexión específica."""
        url = f"{self.base_url}/accounts?connection_id={connection_id}"
        try:
            response = httpx.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json().get("data", [])
        except Exception as e:
            print(f"❌ Error listando cuentas: {e}")
            return []

    def fetch_transactions(self, connection_id, account_id):
        """Descarga transacciones de una cuenta."""
        url = f"{self.base_url}/transactions?connection_id={connection_id}&account_id={account_id}"
        try:
            response = httpx.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json().get("data", [])
        except Exception as e:
            print(f"❌ Error descargando transacciones: {e}")
            return []