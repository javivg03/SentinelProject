import os
import pandas as pd
import pdfplumber

def parse_document(file_path: str) -> str:
    """
    Detecta el tipo de archivo y extrae su contenido en formato texto crudo
    para que sea fácilmente ingerible por Gemini AI.
    """
    ext = file_path.lower().split('.')[-1]
    
    if ext in ['xls', 'xlsx', 'csv']:
        return _parse_excel(file_path)
    elif ext == 'pdf':
        return _parse_pdf(file_path)
    else:
        raise ValueError(f"Formato no soportado: .{ext}")

def _parse_excel(file_path: str) -> str:
    """Extrae datos de Excel (incluso formato antiguo .xls) a string."""
    try:
        # Los bancos suelen dejar mucha basura arriba, así que leemos todo
        # usando xlrd si es .xls antiguo
        engine = 'xlrd' if file_path.endswith('.xls') else 'openpyxl'
        
        # Leemos el excel sin cabeceras estrictas para capturarlo todo
        df = pd.read_excel(file_path, engine=engine, header=None)
        
        # Eliminamos filas y columnas completamente vacías para ahorrar tokens
        df.dropna(how='all', inplace=True)
        df.dropna(axis=1, how='all', inplace=True)
        
        # Convertimos a CSV como string plano (muy amigable para Gemini)
        raw_text = df.to_csv(index=False, header=False)
        return f"=== INICIO DATOS EXCEL ===\n{raw_text}\n=== FIN DATOS EXCEL ==="
    except Exception as e:
        raise RuntimeError(f"Error procesando Excel: {e}")

def _parse_pdf(file_path: str) -> str:
    """Extrae todo el texto de un documento PDF."""
    try:
        text_content = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_content.append(text)
                    
        full_text = "\n".join(text_content)
        return f"=== INICIO DATOS PDF ===\n{full_text}\n=== FIN DATOS PDF ==="
    except Exception as e:
        raise RuntimeError(f"Error procesando PDF: {e}")
