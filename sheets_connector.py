import gspread
from google.oauth2.service_account import Credentials
import datetime
import traceback

class SheetsConnector:
    def __init__(self):
        try:
            # 1. Configuración de acceso
            self.scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            self.creds = Credentials.from_service_account_file("service_account.json", scopes=self.scope)
            self.client = gspread.authorize(self.creds)
            
            # 2. ID del archivo (Asegúrate de que sea el del archivo convertido a Google Sheets)
            self.spreadsheet_id = "1GacUZdpV3vrq1hKUSbXquIw3Yp1A1bnuAITDf3NceOY"
            self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            self.sheet = self.spreadsheet.worksheet("Presupuesto")
            
            # 3. Mapeo de meses (Enero=Col B, Febrero=Col C...)
            self.month_columns = {
                1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 
                7: 8, 8: 9, 9: 10, 10: 11, 11: 12, 12: 13
            }
            print("✅ Conexión con Google Sheets lista.")
        except Exception as e:
            print(f"❌ Error al conectar: {e}")
            traceback.print_exc()
            raise e

    def _clean_value(self, val):
        """Limpia el valor de la celda para que Python pueda sumar"""
        if not val: return 0.0
        try:
            # Quitamos €, espacios y pasamos coma a punto
            return float(str(val).replace('€', '').replace(' ', '').replace(',', '.').strip())
        except ValueError:
            return 0.0

    def log_expense(self, concept, category, amount):
        try:
            # 1. Obtener coordenadas
            now = datetime.datetime.now()
            col = self.month_columns[now.month]
            
            # 2. Buscar la fila de la categoría (Columna A)
            # Buscamos de forma exacta para evitar errores de mapeo
            cell_list = self.sheet.col_values(1)
            target_row = -1
            for i, cell_val in enumerate(cell_list):
                if cell_val.strip().lower() == category.strip().lower():
                    target_row = i + 1
                    break
            
            if target_row == -1:
                print(f"❌ Categoría '{category}' no encontrada en el Excel")
                return False

            # 3. Obtener valor actual, sumar y limpiar
            current_cell_val = self.sheet.cell(target_row, col).value
            current_val = self._clean_value(current_cell_val)
            amount_val = self._clean_value(amount)
            
            new_val = current_val + amount_val

            # 4. Actualizar la celda con el número puro
            self.sheet.update_cell(target_row, col, new_val)
            print(f"💰 {category}: {current_val}€ + {amount_val}€ = {new_val}€")
            return True

        except Exception as e:
            print(f"❌ Error en la cirugía de Excel: {e}")
            traceback.print_exc()
            return False