import httpx
import os

class BankConnector:
    def __init__(self):
        # Cargamos credenciales desde el entorno para máxima seguridad
        self.app_id = os.getenv("SALTEDGE_APP_ID")
        self.secret = os.getenv("SALTEDGE_SECRET")
        self.customer_id = os.getenv("SALTEDGE_CUSTOMER_ID")
        self.base_url = "https://www.saltedge.com/api/v6"
        
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "App-id": self.app_id,
            "Secret": self.secret
        }

    def create_connect_session(self, redirect_url):
        """Genera la URL oficial para que el usuario vincule su banco (PSD2)."""
        url = f"{self.base_url}/connections/connect"
        payload = {
            "data": {
                "customer_id": self.customer_id,
                "consent": {
                    "scopes": ["account_details", "transactions_details"]
                },
                "attempt": {
                    "return_to": redirect_url
                }
            }
        }
        
        try:
            response = httpx.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            # Esta URL es la pasarela segura donde elegirás tu banco
            return response.json().get("data", {}).get("connect_url")
        except Exception as e:
            print(f"❌ Error en Salt Edge v6: {e}")
            return None