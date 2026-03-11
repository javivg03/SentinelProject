import httpx
import os

class BankConnector:
    def __init__(self):
        # Usamos las nuevas variables de Tink que pusiste en Render
        self.client_id = os.getenv("TINK_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("TINK_CLIENT_SECRET", "").strip()
        self.base_url = "https://api.tink.com/api/v1"
        self.auth_url = "https://link.tink.com/1.0/transactions/connect-accounts"
        
        # Para tokens dinámicos en Produccion
        self.access_token = None
        self.refresh_token = None

    def create_connect_session(self, redirect_url):
        """Genera el enlace de Tink Link para conectar bancos reales."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": f"{redirect_url}/callback",
            "market": "ES",
            "locale": "es_ES",
            "scope": "accounts:read,transactions:read",
            "test": "true" # Mantener a 'true' para fase inicial de pruebas en Tink
        }
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{self.auth_url}?{query}"

    def exchange_code_for_token(self, code):
        """Canjea el código de autorización que llega al Webhook por un Token de Acceso Real."""
        try:
            url = f"{self.base_url}/oauth/token"
            data = {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "authorization_code"
            }
            
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            
            # Petición HTTP síncrona real a Tink Web API
            response = httpx.post(url, data=data, headers=headers, timeout=10.0)
            response.raise_for_status()
            
            tokens = response.json()
            # El Refresh Token es el valioso, el que permite conexiones permanentes sin preguntar al usuario
            access_token = tokens.get('access_token')
            refresh_token = tokens.get('refresh_token')
            
            self.access_token = access_token
            # Guardamos también internamente el refresh token para autorrenovaciones
            self.refresh_token = refresh_token
            print(f"✅ [Tink] Token canjeado exitosamente.")
            
            return refresh_token
            
        except httpx.HTTPStatusError as e:
            print(f"❌ Autorización Tink fallida: {e.response.text}")
            return None
        except Exception as e:
            print(f"❌ Error interno Tink Auth: {e}")
            return None

    def refresh_access_token(self):
        """Renueva el token de acceso expirado usando el Refresh Token permanente."""
        if not self.refresh_token:
            return False
            
        try:
            url = f"{self.base_url}/oauth/token"
            data = {
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token"
            }
            
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            response = httpx.post(url, data=data, headers=headers, timeout=10.0)
            response.raise_for_status()
            
            self.access_token = response.json().get('access_token')
            print("🔄 [Tink] Access Token renovado automáticamente con éxito.")
            return True
        except Exception as e:
            print(f"❌ Error renovando token Tink: {e}")
            return False

    def list_connections(self):
        """Devuelve las credenciales de conexión reales a Tink si el Token existe."""
        if not self.access_token:
            print("❌ [Tink] No hay token de acceso. Ejecuta /conectar primero.")
            return []
            
        print("🔗 [Tink] Usando conexión activa.")
        return [{"id": "tink_user_conn", "status": "ACTIVE"}]

    def list_accounts(self, connection_id):
        """Obtiene las cuentas bancarias vinculadas desde la API real de Tink."""
        # Intentamos renovar el token antes de cada llamada importante por si caducó
        if not self.access_token:
            if not self.refresh_access_token():
                return []
            
        try:
            url = f"{self.base_url}/accounts"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = httpx.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            
            data = response.json()
            accounts = []
            for acc in data.get('accounts', []):
                accounts.append({
                    "id": acc.get('id'),
                    "name": acc.get('name', 'Cuenta desconocida'),
                    "balance": acc.get('balances', {}).get('available', {}).get('amount', {}).get('value', {}).get('unscaledValue', 0)
                })
            print(f"🏦 [Tink] Extraídas {len(accounts)} cuentas reales.")
            return accounts
        except httpx.HTTPStatusError as e:
            print(f"❌ Error Tink list_accounts: {e.response.text}")
            return []
        except Exception as e:
            print(f"❌ Error Interno list_accounts: {e}")
            return []

    def fetch_transactions(self, connection_id, account_id):
        """Descarga las últimas transacciones reales de esa cuenta desde Tink."""
        if not self.access_token: return []
        
        try:
            url = f"{self.base_url}/transactions"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            # Opciones de paginación para coger los últimos 50 (semanal/mensual)
            params = {"accountId": account_id, "pageSize": 50} 
            
            response = httpx.get(url, headers=headers, params=params, timeout=10.0)
            response.raise_for_status()
            
            data = response.json()
            transactions = []
            for tx in data.get('transactions', []):
                # Extraemos y purificamos la estructura compleja de Tink API
                desc = tx.get('descriptions', {}).get('display', tx.get('descriptions', {}).get('original', 'Transacción'))
                amount_info = tx.get('amount', {}).get('value', {})
                scale = amount_info.get('scale', 0)
                unscaled_value = amount_info.get('unscaledValue', 0)
                currency = tx.get('amount', {}).get('currencyCode', 'EUR')
                
                # Cálculo de Tink (ej: unscaled = -1550, scale = 2 -> -15.50)
                # En Tink el signo negativo significa Gasto (lo normal para nuestro cerebro AI)
                real_amount = float(unscaled_value) / (10 ** scale) if scale > 0 else float(unscaled_value)
                
                transactions.append({
                    "id": tx.get('id'),
                    "amount": real_amount,
                    "currency_code": currency,
                    "description": desc
                })
            
            print(f"💸 [Tink] Descargadas {len(transactions)} transacciones de cuenta {account_id}.")
            return transactions
            
        except httpx.HTTPStatusError as e:
            print(f"❌ Error Tink fetch_transactions: {e.response.text}")
            return []
        except Exception as e:
            print(f"❌ Error Interno fetch_transactions: {e}")
            return []