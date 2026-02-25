import os
import google.generativeai as genai
from dotenv import load_dotenv

# Cargamos tu clave
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ Error: No se encuentra la GOOGLE_API_KEY en .env")
else:
    genai.configure(api_key=api_key)
    print("🔍 Preguntando a Google qué modelos tienes disponibles...")
    
    try:
        # Listamos todos los modelos que sirven para generar texto
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ MODELO VÁLIDO: {m.name}")
    except Exception as e:
        print(f"❌ Error fatal conectando con Google: {e}")