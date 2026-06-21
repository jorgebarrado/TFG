# Middleware que asigna un UUID único a cada petición HTTP y lo propaga via ContextVar para el logging.
import uuid
from typing import Callable

from django.http import HttpRequest, HttpResponse

from .logging_utils import request_id_var


class RequestIdMiddleware:
    """
    Middleware que genera y asocia un request_id único para cada petición.
    Este ID se guarda en un ContextVar para que esté disponible para el logging
    de forma segura en hilos o llamadas asíncronas.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Recuperamos o generamos el request_id
        req_id = request.headers.get("X-Request-Id")
        if not req_id:
            req_id = str(uuid.uuid4())

        # Almacenamos el request_id en la variable de contexto local (safe thread/async)
        token = request_id_var.set(req_id)

        # Opcional: inyectar el request_id en el propio request por si alguna vista lo necesita
        request.request_id = req_id

        try:
            response = self.get_response(request)
            # Inyectamos el request_id en la respuesta para visibilidad en el cliente
            response["X-Request-Id"] = req_id
            return response
        finally:
            # Restauramos el contexto
            request_id_var.reset(token)
