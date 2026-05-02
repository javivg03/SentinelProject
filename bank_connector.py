import httpx
import os

"""
================================================================================
                        MODULO DEPRECADO (NORMATIVA PSD2)
================================================================================
Este módulo implementaba la conexión directa con entidades bancarias mediante 
APIs de Open Banking (Tink, GoCardless) para la lectura de movimientos en 
tiempo real.

Debido a la directiva europea PSD2, el acceso automatizado a cuentas bancarias 
reales está restringido a empresas con licencia (AISP/PISP) y las versiones 
gratuitas de estas APIs han sido bloqueadas para usuarios individuales/developers.

El código se mantiene comentado como demostración de la arquitectura inicial 
basada en OAuth2 y Webhooks, la cual fue exitosa en entornos "Sandbox". 
La solución actual ha pivotado hacia un sistema de ingestión Batch vía CSV/Excel 
desde Telegram para sortear la limitación legal.
================================================================================
"""

class BankConnector:
    def __init__(self):
        self.client_id = os.getenv("TINK_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("TINK_CLIENT_SECRET", "").strip()
        self.base_url = "https://api.tink.com/api/v1"
        self.auth_url = "https://link.tink.com/1.0/transactions/connect-accounts"
        
        self.access_token = None
        self.refresh_token = None

    def create_connect_session(self, redirect_url):
        """Genera el enlace de Tink Link para conectar bancos reales. (DESHABILITADO)"""
        print("❌ Funcionalidad deshabilitada por normativa PSD2.")
        return None
        # --- CÓDIGO ORIGINAL ---
        # params = {
        #     "client_id": self.client_id,
        #     "redirect_uri": f"{redirect_url}/callback",
        #     "market": "ES",
        #     "locale": "es_ES",
        #     "scope": "accounts:read,transactions:read",
        #     "test": "true" 
        # }
        # query = "&".join([f"{k}={v}" for k, v in params.items()])
        # return f"{self.auth_url}?{query}"

    def exchange_code_for_token(self, code):
        """Canjea el código de autorización que llega al Webhook. (DESHABILITADO)"""
        print("❌ Funcionalidad deshabilitada por normativa PSD2.")
        return None, "Blocked by PSD2"
        # --- CÓDIGO ORIGINAL ---
        # ... (Lógica de canjeo HTTP POST a Tink) ...

    def refresh_access_token(self):
        """Renueva el token de acceso expirado. (DESHABILITADO)"""
        print("❌ Funcionalidad deshabilitada por normativa PSD2.")
        return False

    def list_connections(self):
        """Devuelve las credenciales de conexión reales. (DESHABILITADO)"""
        print("❌ Funcionalidad deshabilitada por normativa PSD2.")
        return []

    def list_accounts(self, connection_id):
        """Obtiene las cuentas bancarias vinculadas. (DESHABILITADO)"""
        print("❌ Funcionalidad deshabilitada por normativa PSD2.")
        return []

    def fetch_transactions(self, connection_id, account_id):
        """Descarga las últimas transacciones reales. (DESHABILITADO)"""
        print("❌ Funcionalidad deshabilitada por normativa PSD2.")
        return []