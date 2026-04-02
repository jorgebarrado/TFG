import uuid
import logging
from contextvars import ContextVar

# Almacena el ID de la request actual en el contexto de ejecución
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIdFilter(logging.Filter):
    """
    Filtro de logging que inyecta el request_id actual en el registro del log,
    permitiendo que los formatters lo incluyan en la salida.
    """

    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


class RequestIdMiddleware:
    """
    Middleware que genera un UUID único por cada request entrante y
    lo almacena en una ContextVar para que sea accesible globalmente.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generar UUID para la request o tomarlo de un header si existe
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # Guardar en ContextVar
        token = request_id_var.set(req_id)

        try:
            response = self.get_response(request)
            # Opcional: devolver el request ID en los headers de respuesta
            response["X-Request-ID"] = req_id
            return response
        finally:
            request_id_var.reset(token)
