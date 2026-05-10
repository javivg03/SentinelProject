import os
import pandas as pd
import pdfplumber


def parse_document(file_path: str) -> str:
    """
    Detecta el tipo de archivo y extrae su contenido en texto plano.

    El texto resultante está pensado para ser ingerido por Gemini:
    sin formato complejo, con delimitadores claros de inicio/fin.

    Args:
        file_path: Ruta local al archivo descargado desde Telegram.

    Returns:
        String con el contenido textual del documento.

    Raises:
        ValueError: Si el formato del archivo no está soportado.
        RuntimeError: Si hay un error al leer el archivo.
    """
    ext = file_path.lower().split(".")[-1]

    if ext in ["xls", "xlsx", "csv"]:
        return _parse_excel(file_path, ext)
    elif ext == "pdf":
        return _parse_pdf(file_path)
    else:
        raise ValueError(f"Formato no soportado: .{ext}")


def _parse_excel(file_path: str, ext: str) -> str:
    """
    Extrae datos de Excel/CSV a texto plano en formato CSV.

    Usa el motor 'xlrd' para archivos .xls (formato binario antiguo de
    los bancos españoles como Unicaja) y 'openpyxl' para .xlsx modernos.
    Para .csv usa el parser nativo de pandas.

    Los bancos suelen añadir cabeceras con metadatos (nombre del titular,
    IBAN, período, etc.) antes de los datos reales. Leemos todo sin
    establecer una cabecera fija para que Gemini pueda interpretarlo.
    """
    try:
        if ext == "csv":
            # Intentamos detectar el separador automáticamente
            df = pd.read_csv(file_path, header=None, sep=None, engine="python")
        else:
            engine = "xlrd" if ext == "xls" else "openpyxl"
            df = pd.read_excel(file_path, engine=engine, header=None)

        # Eliminar filas y columnas completamente vacías para ahorrar tokens
        df.dropna(how="all", inplace=True)
        df.dropna(axis=1, how="all", inplace=True)

        raw_text = df.to_csv(index=False, header=False)
        return f"=== INICIO DATOS EXCEL ===\n{raw_text}\n=== FIN DATOS EXCEL ==="

    except Exception as e:
        raise RuntimeError(f"Error procesando Excel (.{ext}): {e}")


def _parse_pdf(file_path: str) -> str:
    """
    Extrae todo el texto de un documento PDF página a página.

    Usa pdfplumber, que maneja bien PDFs bancarios con tablas
    (como los extractos de Trade Republic).
    Las páginas sin texto detectable se omiten.
    """
    try:
        text_content = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text and text.strip():
                    text_content.append(f"--- Página {i + 1} ---\n{text}")

        if not text_content:
            raise RuntimeError("El PDF no contiene texto extraíble.")

        full_text = "\n\n".join(text_content)
        return f"=== INICIO DATOS PDF ===\n{full_text}\n=== FIN DATOS PDF ==="

    except Exception as e:
        raise RuntimeError(f"Error procesando PDF: {e}")
