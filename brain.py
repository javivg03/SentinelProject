import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

class SentinelBrain:
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ ERROR: No se encontró GOOGLE_API_KEY")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = 'gemini-2.5-flash'
        self.system_prompt_path = os.path.join("prompts", "system_prompt.txt")

    def _load_system_prompt(self):
        try:
            with open(self.system_prompt_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except:
            return "Eres Sentinel. Clasifica movimientos en JSON."

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    def _call_api(self, prompt):
        return self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

    def process_transaction(self, current_input, history=""):
        try:
            instructions = self._load_system_prompt()
            full_prompt = f"{instructions}\n\n--- HISTORIAL ---\n{history}\n\n--- ACTUAL ---\n{current_input}"
            
            response = self._call_api(full_prompt)
            
            data = json.loads(response.text)
            
            if data.get("duda"):
                return data["duda"], "DOUBT"
            
            return data.get("movimientos", []), "SUCCESS"

        except Exception as e:
            return f"Error en IA: {str(e)}", "ERROR"

    def process_batch_transactions(self, transactions_list):
        """Procesa una lista de transacciones bancarias en un solo prompt (Batching temporal)."""
        if not transactions_list:
            return [], "SUCCESS"
            
        try:
            instructions = self._load_system_prompt()
            prompt = f"{instructions}\n\n--- MODO BATCH (LOTE MASIVO) ---\n"
            prompt += "Clasifica TODA la siguiente lista de transacciones de golpe. Devuelve un JSON EXCLUYENTEMENTE respetando el formato {'movimientos': [{concepto, categoria, importe}...]} con todas procesadas.\n"
            prompt += json.dumps(transactions_list, indent=2)
            
            response = self._call_api(prompt)
            data = json.loads(response.text)
            
            return data.get("movimientos", []), "SUCCESS"
            
        except Exception as e:
            print(f"❌ Error interno Gemini Batch: {e}")
            return [], "ERROR"

    def process_raw_document(self, raw_text):
        """Procesa el texto crudo extraído de un PDF o Excel bancario para buscar transacciones."""
        if not raw_text or len(raw_text.strip()) == 0:
            return [], "SUCCESS"
            
        try:
            instructions = self._load_system_prompt()
            prompt = f"{instructions}\n\n--- MODO LECTOR DE DOCUMENTOS BANCARIOS ---\n"
            prompt += "El usuario ha subido un extracto bancario en crudo (Excel o PDF). Tu objetivo es analizar todas las líneas de datos y encontrar TODAS las transacciones de GASTO.\n"
            prompt += "Ignora los ingresos (a menos que parezcan devoluciones). Extrae el concepto y el importe exacto. "
            prompt += "El importe de un gasto debe ser devuelto siempre como un número positivo en el JSON.\n"
            prompt += "Devuelve un JSON EXCLUYENTEMENTE respetando el formato {'movimientos': [{concepto, categoria, importe, tipo}...]} con todas las transacciones procesadas.\n\n"
            prompt += f"--- DATOS CRUDOS DEL BANCO ---\n{raw_text}\n"
            
            print(f"🧠 Enviando a Gemini documento de {len(raw_text)} caracteres...")
            response = self._call_api(prompt)
            data = json.loads(response.text)
            
            return data.get("movimientos", []), "SUCCESS"
            
        except Exception as e:
            print(f"❌ Error en Gemini Document Parsing: {e}")
            return [], "ERROR"

    def evaluate_spending(self, transactions, dynamic_profile):
        """Analiza transacciones contra el perfil vivo del usuario para buscar gastos críticos."""
        try:
            prompt = f"Eres un Asesor Financiero Proactivo muy estricto y severo.\n"
            prompt += f"Este es el perfil de gasto histórico mensual (media aritmética) de tu cliente obtenido vía Aprendizaje Continuo:\n{json.dumps(dynamic_profile, indent=2)}\n\n"
            prompt += f"Revisa las siguientes compras que se acaban de hacer:\n{json.dumps(transactions, indent=2)}\n\n"
            prompt += "Instrucciones críticas:\n"
            prompt += "1. Busca si ha hecho un gasto impulsivo en sus categorías críticas (Ocio, Alcohol, Tabaco, Fiesta).\n"
            prompt += "2. Si un solo gasto supera el 30% de su media mensual en esa categoría, emite alerta.\n"
            prompt += "3. Responde ESTRICTAMENTE con JSON. Formato: {'alerta': true/false, 'motivo': 'Mensaje amigable pero severo del asesor con emojis.'}\n"
            prompt += "Ejemplo si es correcto: {'alerta': false, 'motivo': ''}\n"
            
            response = self._call_api(prompt)
            data = json.loads(response.text)
            
            return data.get("alerta", False), data.get("motivo", "")
            
        except Exception as e:
            print(f"❌ Error en evaluación proactiva IA: {e}")
            return False, ""