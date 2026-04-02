import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# ContextVar para almacenar el ID de la petición de forma segura en entornos asíncronos o con threads
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


def get_request_id() -> str:
    """Devuelve el ID de la petición actual, o '-' si no hay ninguna."""
    return request_id_var.get()


def get_trace_id() -> str:
    """Devuelve el ID de la traza actual, o '-' si no hay ninguna."""
    return trace_id_var.get()


def generate_id() -> str:
    """Genera un nuevo ID aleatorio."""
    return str(uuid.uuid4())


@contextmanager
def bind_trace_context(trace_id: str | None = None):
    """
    Context manager para establecer un nuevo trace_id independiente.
    Útil para operaciones largas o en background que no tienen request_id HTTP.
    Si no se proporciona un trace_id, se generará uno nuevo.
    """
    new_trace_id = trace_id or generate_id()
    token = trace_id_var.set(new_trace_id)
    try:
        yield new_trace_id
    finally:
        trace_id_var.reset(token)


def get_logger(name: str) -> logging.Logger:
    """Obtiene un logger preconfigurado con el nombre dado."""
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str = "",
    exc_info: bool | Exception = False,
    **extra: Any,
) -> None:
    """
    Loggea un evento de forma estructurada.
    'event' es el identificador principal machine-friendly (ej: api_extract_citations_started).
    'message' es opcional y para lectura humana.
    """
    if not logger.isEnabledFor(level):
        return

    context = {"event": event}
    if extra:
        context.update(extra)

    # El formateador se encargará de sanitizar, aquí simplemente usamos el extra.
    # Evitamos formatear strings para la consola si estamos usando JSON en producción,
    # el JSONFormatter se encarga del truncado de `extra`.
    # Para ColorFormatter podemos mantener una salida razonable:
    logger.log(
        level, message or event, extra={"event_context": context}, exc_info=exc_info
    )


@contextmanager
def log_phase(
    logger: logging.Logger, phase: str, level: int = logging.INFO, **extra: Any
):
    """
    Context manager para medir e informar del ciclo de vida de una fase.
    Emite un evento de inicio (_started) y uno de fin (_completed) o fallo (_failed).
    """
    start_time = time.monotonic()

    # Evento de inicio
    log_event(
        logger,
        logging.DEBUG,
        f"{phase}_started",
        message=f"Starting phase: {phase}",
        **extra,
    )

    try:
        yield

        # Evento de fin
        duration_ms = round((time.monotonic() - start_time) * 1000.0, 2)
        log_event(
            logger,
            level,
            f"{phase}_completed",
            message=f"Completed phase: {phase}",
            duration_ms=duration_ms,
            **extra,
        )

    except Exception as e:
        # Evento de fallo
        duration_ms = round((time.monotonic() - start_time) * 1000.0, 2)
        log_event(
            logger,
            logging.ERROR,
            f"{phase}_failed",
            message=f"Failed phase: {phase}",
            exc_info=True,
            duration_ms=duration_ms,
            error=str(e),
            **extra,
        )
        raise
