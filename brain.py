import os
import re
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class SentinelBrain:
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ ERROR: No se encontró GOOGLE_API_KEY en .env")
        
        genai.configure(api_key=api_key)
        self.system_prompt_path = os.path.join("prompts", "system_prompt.txt")
        self.instructions = self._load_system_prompt()
        self.model = genai.GenerativeModel('gemini-flash-latest')

    def _load_system_prompt(self):
        try:
            with open(self.system_prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return "Eres Sentinel. Clasifica movimientos financieros en categorías exactas."

    def process_transaction(self, sanitized_input):
        """
        Procesa el mensaje y devuelve: (Texto para Telegram, Lista de movimientos)
        """
        try:
            full_prompt = f"{self.instructions}\n\nMENSAJE DEL USUARIO:\n{sanitized_input}"
            response = self.model.generate_content(full_prompt)
            full_text = response.text

            # Buscamos todos los bloques que comiencen por --- y contengan la info
            # El regex busca bloques individuales para poder procesarlos en bucle
            bloques = re.findall(r"💰 Movimiento:.*?(?=💰|---|$)", full_text, re.DOTALL)
            
            extracted_items = []
            for bloque in bloques:
                item = {
                    "concepto": self._regex_extract(r"💰 Movimiento: (.+)", bloque),
                    "categoria": self._regex_extract(r"🏷️ Categoría: (.+)", bloque),
                    "importe": self._regex_extract(r"📉 Importe: -?([\d.,]+)", bloque)
                }
                # Solo añadimos si hemos conseguido extraer un importe válido
                if item["importe"] != "N/A":
                    extracted_items.append(item)

            return full_text, extracted_items
        except Exception as e:
            return f"❌ Error en el núcleo de Gemini: {str(e)}", []

    def _regex_extract(self, pattern, text):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
        return "N/A"