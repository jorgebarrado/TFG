# Sesión HTTP compartida para llamadas a APIs externas, con bypass de proxies de entorno local rotos.
from __future__ import annotations

import requests


def build_external_api_session() -> requests.Session:
    """
    Crea una sesion HTTP para APIs externas ignorando proxies rotos del entorno local.
    """
    session = requests.Session()
    session.trust_env = False
    return session
