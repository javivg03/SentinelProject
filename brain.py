import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

class SentinelBrain:
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ ERROR: No se encontró GOOGLE_API_KEY")
        
        genai.configure(api_key=api_key)
        self.model_name = 'gemini-1.5-flash'
        self.model = genai.GenerativeModel(self.model_name)
        self.system_prompt_path = os.path.join("prompts", "system_prompt.txt")

    def _load_system_prompt(self):
        try:
            with open(self.system_prompt_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except:
            return "Eres Sentinel. Clasifica movimientos en JSON."

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    def _call_api(self, prompt):
        return self.model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
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