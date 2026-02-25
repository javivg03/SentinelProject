import gspread
import os
import json
import datetime
import traceback
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# Cargamos variables de entorno por si se ejecuta este archivo de forma aislada
load_dotenv()

class SheetsConnector:
    def __init__(self):
        try:
            # 1. Configuración de alcances (Scopes)
            self.scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            
            # 2. Lógica de Autenticación Dual (Local vs Nube)
            # Priorizamos el archivo local si existe, si no, buscamos en el entorno
            if os.path.exists("service_account.json"):
                self.creds = Credentials.from_service_account_file("service_account.json", scopes=self.scope)
                print("🔑 Sentinel [Sheets]: Usando service_account.json local.")
            else:
                env_creds = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
                if not env_creds:
                    raise EnvironmentError("❌ No se encontró 'service_account.json' ni la variable 'GOOGLE_SERVICE_ACCOUNT_JSON'.")
                
                info = json.loads(env_creds)
                self.creds = Credentials.from_service_account_info(info, scopes=self.scope)
                print("☁️ Sentinel [Sheets]: Usando credenciales de variable de entorno.")

            self.client = gspread.authorize(self.creds)
            
            # 3. Identificación del Libro (ID desde el entorno)
            self.spreadsheet_id = os.getenv("SPREADSHEET_ID")
            if not self.spreadsheet_id:
                raise ValueError("❌ La variable 'SPREADSHEET_ID' no está definida en el archivo .env")

            self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            self.sheet = self.spreadsheet.worksheet("Presupuesto")
            
            # 4. Mapeo Cronológico (Mes -> Columna)
            # Enero es Col B (2), Febrero Col C (3), etc.
            self.month_columns = {m: m + 1 for m in range(1, 13)}
            
            print(f"✅ Conexión establecida con la hoja: '{self.spreadsheet.title}'")

        except Exception as e:
            print(f"❌ Error crítico en SheetsConnector: {e}")
            traceback.print_exc()
            raise e

    def _clean_value(self, val):
        """Convierte valores de celda (texto/moneda) en float operable."""
        if val is None or str(val).strip() == "":
            return 0.0
        try:
            # Eliminamos símbolos comunes y normalizamos decimales
            sanitized = str(val).replace('€', '').replace(' ', '').replace(',', '.').strip()
            return float(sanitized)
        except ValueError:
            return 0.0

    def log_expense(self, concept, category, amount):
        """Localiza la categoría y suma el importe al mes actual."""
        try:
            now = datetime.datetime.now()
            col = self.month_columns.get(now.month)
            
            # 1. Búsqueda de Categoría en Columna A
            # Obtenemos todos los valores de la columna 1 para buscar localmente (más rápido)
            categories = self.sheet.col_values(1)
            target_row = -1
            clean_category = category.strip().lower()
            
            for i, val in enumerate(categories):
                if val.strip().lower() == clean_category:
                    target_row = i + 1
                    break
            
            if target_row == -1:
                print(f"⚠️ Categoría '{category}' no encontrada. Abortando registro.")
                return False

            # 2. Operación de actualización (Lectura -> Suma -> Escritura)
            current_cell_val = self.sheet.cell(target_row, col).value
            current_val = self._clean_value(current_cell_val)
            amount_to_add = self._clean_value(amount)
            
            new_total = current_val + amount_to_add

            # 3. Commit a Google Sheets
            self.sheet.update_cell(target_row, col, new_total)
            print(f"💰 Registro exitoso: {category} | {current_val}€ -> {new_total}€")
            return True

        except Exception as e:
            print(f"❌ Error al registrar gasto en Sheets: {e}")
            return False