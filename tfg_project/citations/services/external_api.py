from __future__ import annotations

import requests


def build_external_api_session() -> requests.Session:
    """
    Crea una sesion HTTP para APIs externas ignorando proxies rotos del entorno local.
    """
    session = requests.Session()
    session.trust_env = False
    return session
