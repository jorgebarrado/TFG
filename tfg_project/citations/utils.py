import xml.etree.ElementTree as ET

import requests


def get_articles_from_dblp(dblp_url):
    """
    Fetches a list of publications from a DBLP author URL.
    Obtiene una lista de publicaciones desde una URL de autor de DBLP.

    Args:
        dblp_url (str): The URL of the DBLP author page (HTML or XML).
                        La URL de la página de autor de DBLP (HTML o XML).

    Returns:
        list: A list of dictionaries, where each dictionary represents a
              publication with 'title', 'doi', and 'type'. Returns an empty
              list if an error occurs.
              Una lista de diccionarios, donde cada diccionario representa una
              publicación con 'title', 'doi' y 'type'. Devuelve una lista
              vacía si ocurre un error.
    """
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
    """
    Retrieves articles that cite a given DOI using the Semantic Scholar API.
    Recupera los artículos que citan un DOI determinado utilizando la API de
    Semantic Scholar.

    Args:
        doi (str): The DOI of the article to look up.
                   El DOI del artículo a buscar.

    Returns:
        list: A list of dictionaries, each representing a citing article with
              'title', 'authors', 'year', 'doi', and 'url'. Returns an empty
              list if the request fails or an error occurs.
              Una lista de diccionarios, cada uno representando un artículo
              citante con 'title', 'authors', 'year', 'doi' y 'url'. Devuelve
              una lista vacía si la solicitud falla o se produce un error.
    """
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
    """
    Checks if a given DOI has any citations via the Semantic Scholar API.
    Comprueba si un DOI determinado tiene alguna cita a través de la API de
    Semantic Scholar.

    Args:
        doi (str): The DOI of the article to check.
                   El DOI del artículo a comprobar.

    Returns:
        bool: True if the article has one or more citations, False otherwise.
              True si el artículo tiene una o más citas, False en caso
              contrario.
    """
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
    """
    Gets the citation count for a given DOI from the Semantic Scholar API.
    Obtiene el número de citas para un DOI determinado desde la API de
    Semantic Scholar.

    Args:
        doi (str): The DOI of the article.
                   El DOI del artículo.

    Returns:
        int: The number of citations for the article. Returns 0 if the
             request fails or an error occurs.
             El número de citas del artículo. Devuelve 0 si la solicitud falla
             o se produce un error.
    """
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
