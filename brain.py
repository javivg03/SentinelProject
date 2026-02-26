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
        # Mantenemos el modelo flash-latest por estabilidad de cuota
        self.model_name = 'gemini-flash-latest'
        self.system_prompt_path = os.path.join("prompts", "system_prompt.txt")
        self.model = genai.GenerativeModel(self.model_name)
        
        print(f"🧠 Sentinel [Brain]: Motor '{self.model_name}' con Memoria Contextual listo.")

    def _load_system_prompt(self):
        try:
            if os.path.exists(self.system_prompt_path):
                with open(self.system_prompt_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            return "Eres Sentinel. Clasifica gastos en JSON."
        except Exception as e:
            return "Eres Sentinel. Clasifica gastos en JSON."

    def process_transaction(self, current_input, history=""):
        try:
            instructions = self._load_system_prompt()
            full_prompt = (
                f"{instructions}\n\n"
                f"--- HISTORIAL RECIENTE ---\n{history}\n\n"
                f"--- MENSAJE ACTUAL ---\n{current_input}"
            )

            # Solicitamos respuesta en formato JSON
            response = self.model.generate_content(
                full_prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            data = json.loads(response.text)

            # Caso 1: La IA tiene una duda real
            if data.get("duda"):
                return data["duda"], "DOUBT"

            # Caso 2: Movimientos detectados
            return data.get("movimientos", []), "SUCCESS"

        except Exception as e:
            return f"❌ Error en el núcleo de Gemini: {str(e)}", "ERROR"