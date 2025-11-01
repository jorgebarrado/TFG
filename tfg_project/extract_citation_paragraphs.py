import re
import argparse

def extract_citation_paragraphs(manuscript_path):
    """
    Extracts paragraphs from a manuscript that contain citations.

    This script is designed to process a plain text scientific manuscript, identify
    the reference list, and extract the paragraphs from the main body where each
    reference is cited. It is particularly useful for analyzing the context in
    which citations are made.

    The script performs the following steps:
    1.  Reads the content of the manuscript file.
    2.  Separates the main body from the reference list by looking for a
        'References' or 'Bibliography' section. If no such section is found,
        the entire file is treated as the body.
    3.  Parses the reference list to identify the reference identifiers (e.g., '[1]',
        '2.'). If the reference list is not found, it will look for citation
        patterns in the body (e.g., '[1]').
    4.  Splits the main body into paragraphs and identifies which paragraphs
        contain in-text citations.
    5.  Groups the paragraphs by the references they cite, ensuring that each
        paragraph is stored only once per reference, even if cited multiple
        times in the same paragraph.

    Args:
        manuscript_path (str): The path to the manuscript file (must be in plain
                               text format).

    Returns:
        dict: A dictionary where keys are the reference identifiers (as strings,
              e.g., '1') and values are lists of unique paragraphs that cite
              the corresponding reference. Returns an empty dictionary if no
              citations are found or if an error occurs.

    Limitations:
        - The script is designed for plain text files and may not work correctly
          with other formats (e.g., PDF, DOCX).
        - The reference parsing assumes a simple format (e.g., '[1]' or '1.').
          More complex reference styles may not be correctly identified.
        - The paragraph splitting is based on double newline characters ('\n\n'),
          which is a common convention but may not be universally applicable.
    """
    try:
        with open(manuscript_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: The file '{manuscript_path}' was not found.")
        return {}
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
        return {}

    # Separate the main body from the reference list.
    references_marker = re.search(r'^\s*(references|bibliography)\s*$', content, re.IGNORECASE | re.MULTLINE)
    if references_marker:
        body = content[:references_marker.start()]
        references_text = content[references_marker.end():]
    else:
        body = content
        references_text = ""

    # Parse the reference list to identify the reference identifiers.
    reference_identifiers = re.findall(r'^\s*(?:\[(\d+)\]|(\d+)\.)', references_text, re.MULTILINE)
    parsed_refs = {ref for group in reference_identifiers for ref in group if ref}

    # If no references are found in the reference list, look for citations in the body.
    if not parsed_refs:
        all_citations_in_body = re.findall(r'\[(\d+)\]', body)
        parsed_refs = set(all_citations_in_body)
        if not parsed_refs:
            return {}

    # Split the main body into paragraphs.
    paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]

    # A dictionary to store the paragraphs for each reference.
    citation_data = {ref: [] for ref in parsed_refs}

    # A regular expression to find in-text citations.
    citation_pattern = re.compile(r'\[(\d+)\]')

    # Iterate over the paragraphs and find the citations.
    for para in paragraphs:
        found_citations = set(citation_pattern.findall(para))
        for ref_num in found_citations:
            if ref_num in parsed_refs:
                # Add the paragraph to the list for the corresponding reference,
                # ensuring that it is not added more than once.
                if para not in citation_data[ref_num]:
                    citation_data[ref_num].append(para)

    # Remove references that have no corresponding citations in the body.
    final_citation_data = {ref: paras for ref, paras in citation_data.items() if paras}

    return final_citation_data

if __name__ == '__main__':
    # Set up the command-line argument parser.
    parser = argparse.ArgumentParser(
        description='Extract citation paragraphs from a scientific manuscript.'
    )
    parser.add_argument(
        'manuscript_path',
        type=str,
        help='The path to the manuscript file (plain text).'
    )
    args = parser.parse_args()

    # Extract the citation paragraphs from the manuscript.
    citation_data = extract_citation_paragraphs(args.manuscript_path)

    # Print the results.
    if citation_data:
        print(f"Found citations for {len(citation_data)} references.\n")
        for ref, paragraphs in sorted(citation_data.items(), key=lambda item: int(item[0])):
            print(f"Reference [{ref}]:")
            for i, para in enumerate(paragraphs, 1):
                print(f"  - Paragraph {i}: {para.replace('\n', ' ')}\n")
            print("-" * 40)
    else:
        print("No citation paragraphs were found.")
