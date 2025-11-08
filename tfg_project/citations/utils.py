import xml.etree.ElementTree as ET

import requests


def get_articles_from_dblp(dblp_url):
    try:
        # Convertir la URL HTML en URL XML
        if dblp_url.endswith(".html"):
            dblp_xml_url = dblp_url.replace(".html", ".xml")
        elif dblp_url.endswith(".xml"):
            dblp_xml_url = dblp_url
        else:
            return []

        response = requests.get(dblp_xml_url, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        publications = []
        for publ in root.findall("r"):
            entry = publ[0]

            title_elem = entry.find("title")
            doi_elem = entry.find("ee")

            title = title_elem.text if title_elem is not None else "Sin título"
            doi = doi_elem.text if doi_elem is not None else None
            if doi_elem is not None and doi_elem.text and "doi.org/" in doi_elem.text:
                doi = doi_elem.text.split("doi.org/")[-1].strip()
            else:
                doi = None

            publications.append(
                {
                    "title": title,
                    "doi": doi,
                    "type": entry.tag,
                }
            )

        return publications

    except Exception as e:
        print("Error al obtener publicaciones desde DBLP:", e)
        return []


def get_citing_articles(doi):
    try:
        headers = {"User-Agent": "Django-App"}
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/DOI:"
            f"{doi}"
            "?fields=title,citationCount,"
            "citations.title,citations.authors,"
            "citations.year,citations.doi,citations.url"
        )
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return []

        data = response.json()
        citations = data.get("citations", [])

        result = []
        for c in citations:
            result.append(
                {
                    "title": c.get("title"),
                    "authors": ", ".join(a["name"] for a in c.get("authors", [])),
                    "year": c.get("year"),
                    "doi": c.get("doi"),
                    "url": c.get("url"),
                }
            )

        return result

    except Exception as e:
        print("Error en Semantic Scholar:", e)
        return []


def check_doi_has_citations(doi):
    try:
        headers = {"User-Agent": "Django-App"}
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/DOI:"
            f"{doi}"
            "?fields=citationCount"
        )
        response = requests.get(url, headers=headers, timeout=10)

        print("→ Consultando DOI:", doi)
        print("→ Código de estado:", response.status_code)

        if response.status_code != 200:
            return False

        data = response.json()
        print("→ citationCount =", data.get("citationCount"))

        return data.get("citationCount", 0) > 0

    except Exception as e:
        print(f"Error consultando DOI {doi}: {e}")
        return False


def get_citation_count(doi):
    try:
        headers = {"User-Agent": "Django-App"}
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/DOI:"
            f"{doi}"
            "?fields=citationCount"
        )
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return 0

        data = response.json()
        return data.get("citationCount", 0)
    except Exception as e:
        print(f"Error al obtener citationCount para {doi}: {e}")
        return 0


from typing import List, Dict, Any
from papermage.recipes.core_recipe import CoreRecipe

def extract_augmented_snippets_with_papermage(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extracts citation snippets and their bounding box coordinates from a PDF using papermage.
    """
    recipe = CoreRecipe()
    doc = recipe.run(pdf_path)

    results = []

    if hasattr(doc, 'bibliographies'):
        for bib in doc.bibliographies:
            results.append({
                "text": bib.text,
                "boxes": [box.to_json() for box in bib.boxes]
            })

    return results
