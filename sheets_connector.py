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
            
            # 5. Mapeo de Categorías en Local O(1) para evitar iteración constante
            categories = self.sheet.col_values(1)
            self.category_map = {val.strip().lower(): i + 1 for i, val in enumerate(categories) if val.strip()}
            
            print(f"✅ Conexión establecida con la hoja: '{self.spreadsheet.title}'. Categorías cacheadas: {len(self.category_map)}")

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
            
            # 1. Búsqueda de Categoría O(1) desde el caché local
            clean_category = category.strip().lower()
            target_row = self.category_map.get(clean_category, -1)
            
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

    def batch_log_expenses(self, parsed_items):
        """
        Recibe una lista de movimientos procesados, los agrupa y escribe en lote en Google Sheets.
        Minimiza drásticamente las llamadas API y optimiza el tiempo de inserción.
        """
        if not parsed_items: return 0
            
        try:
            now = datetime.datetime.now()
            col = self.month_columns.get(now.month)
            
            # 1. Agrupar importes por categoría localmente (Reducción matemática)
            aggregated = {}
            for item in parsed_items:
                cat = str(item.get('categoria', '')).strip().lower()
                amt = self._clean_value(item.get('importe', 0))
                
                # Si la categoría que dicta Gemini no existe, forzamos a 'otros'
                target_cat = cat if cat in self.category_map else 'otros'
                aggregated[target_cat] = aggregated.get(target_cat, 0.0) + amt
                    
            if not aggregated:
                return 0
                
            # 2. Descargar toda la columna para lectura en 1 sola llamada (Lectura Masiva)
            col_data = self.sheet.col_values(col)
            
            # 3. Preparar array de Celdas (Objetos Cell de gspread) para escritura masiva
            cells_to_update = []
            
            for cat, amount_to_add in aggregated.items():
                target_row = self.category_map.get(cat)
                
                current_val = 0.0
                # Gspread indexa desde 1 matemáticamente pero python arrays desde 0
                if target_row <= len(col_data):
                    current_val = self._clean_value(col_data[target_row - 1])
                    
                new_total = round(current_val + amount_to_add, 2)
                
                cells_to_update.append(gspread.Cell(row=target_row, col=col, value=new_total))
                print(f"📦 Lote agrupado en memoria: {cat} | {current_val}€ -> {new_total}€")
                
            # 4. Batch Commit final a Google Sheets (1 SOLA LLAMADA API)
            self.sheet.update_cells(cells_to_update)
            print(f"✅ Batch completado: {len(parsed_items)} gastos consolidados en {len(cells_to_update)} categorías.")
            
            return len(parsed_items)
            
        except Exception as e:
            print(f"❌ Error al insertar lote en Sheets: {e}")
            return 0

    def calculate_dynamic_thresholds(self):
        """Descarga todos los datos de la hoja y calcula la media aritmética de categorías críticas."""
        try:
            print("📊 [Sentient] Calculando umbrales dinámicos (Aprendizaje Continuo)...")
            all_values = self.sheet.get_all_values()
            
            keywords = ['ocio', 'alcohol', 'tabaco', 'fiesta', 'restaurante']
            results = {}
            
            for row in all_values:
                if not row: continue
                cat = str(row[0]).lower().strip()
                if any(k in cat for k in keywords):
                    # Filtrar sólo los valores numéricos de los meses (columnas 1 en adelante)
                    numeric_vals = []
                    for val in row[1:]:
                        clean_val = self._clean_value(val)
                        if clean_val > 0:  # Ignorar meses vacíos o con 0
                            numeric_vals.append(clean_val)
                            
                    if numeric_vals:
                        media = sum(numeric_vals) / len(numeric_vals)
                        # Devolvemos el nombre original de la fila y su nueva media
                        results[str(row[0])] = round(media, 2)
                        
            print(f"🧠 Perfiles aprendidos: {results}")
            return results

        except Exception as e:
            print(f"❌ Error al calcular umbrales: {e}")
            return {}