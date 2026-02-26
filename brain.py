import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class SentinelBrain:
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ ERROR: No se encontró GOOGLE_API_KEY")
        
        genai.configure(api_key=api_key)
        self.model_name = 'gemini-flash-latest'
        self.model = genai.GenerativeModel(self.model_name)
        self.system_prompt_path = os.path.join("prompts", "system_prompt.txt")

    def _load_system_prompt(self):
        try:
            with open(self.system_prompt_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except:
            return "Eres Sentinel. Clasifica movimientos en JSON."

    def process_transaction(self, current_input, history=""):
        try:
            instructions = self._load_system_prompt()
            full_prompt = f"{instructions}\n\n--- HISTORIAL ---\n{history}\n\n--- ACTUAL ---\n{current_input}"
            
            response = self.model.generate_content(
                full_prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            data = json.loads(response.text)
            
            if data.get("duda"):
                return data["duda"], "DOUBT"
            
            return data.get("movimientos", []), "SUCCESS"

        except Exception as e:
            return f"Error en IA: {str(e)}", "ERROR"