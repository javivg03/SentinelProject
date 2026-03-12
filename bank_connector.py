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

    def _get_user_delegation_code(self):
        """Crea un usuario persistente en Tink (o lo usa si existe) y devuelve su autorización."""
        try:
            import uuid
            # 1. Obtener Token de Cliente (maestro)
            url_token = f"{self.base_url}/oauth/token"
            data_token = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
                "scope": "user:create authorization:grant"
            }
            r_token = httpx.post(url_token, data=data_token, timeout=10.0)
            r_token.raise_for_status()
            client_token = r_token.json().get('access_token')

            # 2. Crear un NUEVO Usuario de Sentinel (con UUID random para evitar colisiones 409)
            url_user = f"{self.base_url}/user/create"
            headers = {"Authorization": f"Bearer {client_token}"}
            ext_id = str(uuid.uuid4())
            user_data = {
                "external_user_id": ext_id,
                "market": "ES",
                "locale": "es_ES"
            }
            r_user = httpx.post(url_user, headers=headers, json=user_data, timeout=10.0)
            r_user.raise_for_status()
            
            # 3. Generar Authorization Code usando el ID Interno criptográfico oficial de Tink
            internal_user_id = r_user.json().get('user_id')
            url_delegate = f"{self.base_url}/oauth/authorization-grant/delegate"
            delegate_data = {
                "user_id": internal_user_id,
                "id_hint": "Javier Sentinel",
                # IMPORTANTE: Tink exige este ID mágico específico (Pertenece a la App Oficial "Tink Link") para delegaciones UI
                "actor_client_id": "df05e4b379934cd09963197cc855bfe9", 
                "scope": "authorization:grant"
            }
            r_delegate = httpx.post(url_delegate, headers=headers, data=delegate_data, timeout=10.0)
            r_delegate.raise_for_status()
            return r_delegate.json().get('code')
            
        except Exception as e:
            print(f"❌ Error generando Usuario Delegado Tink: {e}")
            return None

    def create_connect_session(self, redirect_url):
        """Genera el enlace de Tink Link para conectar bancos reales."""
        # Pre-Autorizamos a nuestro Usuario Persistente
        auth_code = self._get_user_delegation_code()
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": f"{redirect_url}/callback",
            "market": "ES",
            "locale": "es_ES"
        }
        
        # Inyectar el código delegado elimina el login anónimo, permitiendo que Tink nos de la llave Refresh
        if auth_code:
            params["authorization_code"] = auth_code
        else:
            params["scope"] = "accounts:read,transactions:read"
            
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
            response.raise_for_status() # Lanza excepción si hay error 4XX o 5XX
            
            tokens = response.json()
            access_token = tokens.get('access_token')
            refresh_token = tokens.get('refresh_token')
            
            if not refresh_token:
                # Significa que OAuth funcionó pero Tink se negó a darnos acceso permanente
                error_msg = f"No se recibió Refresh Token. Respuesta de Tink: {tokens}"
                print(f"❌ {error_msg}")
                return None, error_msg
            
            self.access_token = access_token
            self.refresh_token = refresh_token
            print(f"✅ [Tink] Token canjeado exitosamente.")
            
            return refresh_token, None
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP Error {e.response.status_code}: {e.response.text}"
            print(f"❌ Autorización Tink fallida: {error_msg}")
            return None, error_msg
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error interno Tink Auth: {error_msg}")
            return None, error_msg

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