import os
import re
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class SentinelBrain:
    def __init__(self):
        # 1. Validación de API Key
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("❌ ERROR: No se encontró GOOGLE_API_KEY en .env")
        
        # 2. Configuración del modelo (Mantenemos el que NO da error de cuota)
        genai.configure(api_key=api_key)
        self.model_name = 'gemini-flash-latest'
        self.system_prompt_path = os.path.join("prompts", "system_prompt.txt")
        self.instructions = self._load_system_prompt()
        self.model = genai.GenerativeModel(self.model_name)
        
        print(f"🧠 Sentinel [Brain]: Motor '{self.model_name}' listo.")

    def _load_system_prompt(self):
        """Carga las reglas de comportamiento desde el archivo."""
        try:
            if os.path.exists(self.system_prompt_path):
                with open(self.system_prompt_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            return "Eres Sentinel. Clasifica gastos."
        except Exception as e:
            print(f"❌ Error al cargar prompt: {e}")
            return "Eres Sentinel. Clasifica gastos."

    def process_transaction(self, sanitized_input):
        """
        Procesa el input y detecta si hay movimientos claros o dudas.
        Devuelve: (texto_para_usuario, lista_movimientos)
        """
        try:
            # Incluimos las instrucciones en el prompt para este modelo
            full_prompt = f"{self.instructions}\n\nMENSAJE DEL USUARIO:\n{sanitized_input}"
            response = self.model.generate_content(full_prompt)
            full_text = response.text

            # 1. DETECCIÓN DE DUDA: Si la IA no está segura, abortamos registro
            if "❓ DUDA:" in full_text or "DUDA" in full_text.upper()[:15]:
                print("⚠️ La IA tiene dudas sobre este mensaje.")
                return full_text, "DOUBT"

            # 2. EXTRACCIÓN DE MOVIMIENTOS (Regex robusta)
            bloques = re.findall(r"💰 Movimiento:.*?(?=💰|---|$)", full_text, re.DOTALL)
            
            extracted_items = []
            for bloque in bloques:
                item = {
                    "concepto": self._regex_extract(r"💰 Movimiento:\s*(.+)", bloque),
                    "categoria": self._regex_extract(r"🏷️ Categoría:\s*(.+)", bloque),
                    "importe": self._regex_extract(r"📉 Importe:\s*(-?[\d.,]+)", bloque)
                }
                
                # Validación de seguridad: No guardamos nada con N/A
                if item["importe"] != "N/A" and item["categoria"] != "N/A":
                    extracted_items.append(item)

            return full_text, extracted_items

        except Exception as e:
            return f"❌ Error en el núcleo de Gemini: {str(e)}", []

    def _regex_extract(self, pattern, text):
        """Extracción segura sin asteriscos de Markdown."""
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Eliminamos asteriscos que Gemini a veces añade para negritas
            return match.group(1).replace('*', '').strip()
        return "N/A"