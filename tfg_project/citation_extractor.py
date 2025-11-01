import re
import argparse
from pypdf import PdfReader
import io
import json

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extracts text from a PDF file.
    Extrae texto de un archivo PDF.

    Args:
        pdf_path (str): The path to the PDF file.
                        La ruta al archivo PDF.

    Returns:
        str: The extracted text from the PDF.
             El texto extraído del PDF.
    """
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Error reading PDF file: {e}")
        return ""

def extract_citation_snippets(text: str) -> dict:
    """
    Extracts citation snippets from a given text.
    Extrae fragmentos de citación de un texto dado.

    This function processes a string of text from a manuscript, identifies both
    numeric and author-year citations, and extracts the paragraphs and snippets
    where these citations appear.
    Esta función procesa una cadena de texto de un manuscrito, identifica
    citaciones tanto numéricas como de autor-año, y extrae los párrafos y
    fragmentos donde aparecen estas citaciones.

    Args:
        text (str): The text of the manuscript.
                    El texto del manuscrito.

    Returns:
        dict: A dictionary with the citation snippets, in the specified format.
              Un diccionario con los fragmentos de citación, en el formato especificado.
    """
    # Split the text into paragraphs.
    # Dividir el texto en párrafos.
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

    # Regex for numeric and author-year citations.
    # Regex para citaciones numéricas y de autor-año.
    numeric_style = r'\[\s*\d+(?:\s*,\s*\d+)*\s*\]'
    author_year_style = r'\(\s*[A-Za-z]+\s*(?:et al\.\s*)?,\s*\d{4}\s*\)'
    citation_pattern = re.compile(f'({numeric_style}|{author_year_style})')

    citation_data = {}

    for para in paragraphs:
        for match in citation_pattern.finditer(para):
            citation_key = match.group(0)
            start, end = match.span()

            # Extract snippet of ±120 characters around the citation.
            # Extraer un fragmento de ±120 caracteres alrededor de la citación.
            snippet_start = max(0, start - 120)
            snippet_end = min(len(para), end + 120)
            snippet = para[snippet_start:snippet_end]

            # Create the data structure for the citation.
            # Crear la estructura de datos para la citación.
            if citation_key not in citation_data:
                citation_data[citation_key] = []

            citation_data[citation_key].append({
                "paragraph": para,
                "snippet": snippet,
                "start": start,
                "end": end
            })

    return citation_data

def process_manuscript(manuscript_path: str) -> dict:
    """
    Processes a manuscript file (PDF or TXT) and extracts citation snippets.
    Procesa un archivo de manuscrito (PDF o TXT) y extrae fragmentos de citación.

    Args:
        manuscript_path (str): The path to the manuscript file.
                               La ruta al archivo del manuscrito.

    Returns:
        dict: A dictionary with the citation snippets.
              Un diccionario con los fragmentos de citación.
    """
    if manuscript_path.lower().endswith('.pdf'):
        content = extract_text_from_pdf(manuscript_path)
    else:
        try:
            with open(manuscript_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            print(f"Error: The file '{manuscript_path}' was not found.")
            return {}
        except Exception as e:
            print(f"An error occurred while reading the file: {e}")
            return {}

    if not content:
        return {}

    return extract_citation_snippets(content)

if __name__ == '__main__':
    # This block allows the script to be run from the command line for testing.
    # Este bloque permite que el script se ejecute desde la línea de comandos para realizar pruebas.
    #
    # To integrate with Django, you would typically import the `extract_citation_snippets`
    # function into your `views.py` file and call it from a view.
    # Para integrarlo con Django, normalmente importarías la función `extract_citation_snippets`
    # en tu archivo `views.py` y la llamarías desde una vista.
    #
    # Example Django view:
    # Ejemplo de vista en Django:
    #
    # from django.http import JsonResponse
    # from .citation_extractor import extract_citation_snippets
    #
    # def my_view(request):
    #     if request.method == 'POST' and request.FILES.get('manuscript'):
    #         uploaded_file = request.FILES['manuscript']
    #         if uploaded_file.name.endswith('.pdf'):
    #             # Handle PDF file
    #             # You might need to save it temporarily to pass a path to a PDF reader function
    #             pass
    #         else:
    #             text = uploaded_file.read().decode('utf-8')
    #             snippets = extract_citation_snippets(text)
    #             return JsonResponse(snippets)
    #     return JsonResponse({'error': 'Invalid request'}, status=400)

    parser = argparse.ArgumentParser(
        description='Extract citation snippets from a scientific manuscript.'
    )
    parser.add_argument(
        'manuscript_path',
        type=str,
        help='The path to the manuscript file (plain text or PDF).'
    )
    args = parser.parse_args()

    citation_data = process_manuscript(args.manuscript_path)

    if citation_data:
        print(json.dumps(citation_data, indent=2))
    else:
        print("No citation snippets were found.")
