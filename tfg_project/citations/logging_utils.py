# Utilidades de logging: request_id por ContextVar, temporizadores de fases y helpers de logger con contexto.
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# ContextVar para almacenar el ID de la petición de forma segura en entornos asíncronos o con threads
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Devuelve el ID de la petición actual, o '-' si no hay ninguna."""
    return request_id_var.get()


def generate_request_id() -> str:
    """Genera un nuevo ID de petición."""
    return str(uuid.uuid4())


def get_logger(name: str) -> logging.Logger:
    """Obtiene un logger preconfigurado con el nombre dado."""
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, message: str, **context: Any) -> None:
    """
    Loggea un evento con un diccionario de contexto adicional de forma estructurada.
    """
    if not logger.isEnabledFor(level):
        return

    # Preparamos el mensaje añadiendo los metadatos del contexto si existen
    if context:
        # truncamos valores largos en strings si los hay
        safe_context = {}
        for k, v in context.items():
            if isinstance(v, str) and len(v) > 500:
                safe_context[k] = v[:497] + "..."
            else:
                safe_context[k] = v

        ctx_str = " ".join([f"{k}={v}" for k, v in safe_context.items()])
        message = f"{message} | {ctx_str}"

    logger.log(level, message, extra={"event_context": context})


def log_phase_start(logger: logging.Logger, phase: str, **kwargs: Any) -> float:
    """Loggea el inicio de una fase y devuelve el tiempo de inicio."""
    log_event(logger, logging.DEBUG, f"Empezando fase: {phase}", phase=phase, **kwargs)
    return time.monotonic()


def log_phase_end(
    logger: logging.Logger,
    phase: str,
    start_time: float,
    level: int = logging.INFO,
    **kwargs: Any,
) -> float:
    """Loggea el fin de una fase incluyendo el tiempo invertido en milisegundos."""
    elapsed_ms = (time.monotonic() - start_time) * 1000.0
    log_event(
        logger,
        level,
        f"Fase completada: {phase}",
        phase=phase,
        elapsed_ms=round(elapsed_ms, 2),
        **kwargs,
    )
    return elapsed_ms


@contextmanager
def log_phase(logger: logging.Logger, phase: str, **kwargs: Any):
    """
    Context manager para medir e informar del ciclo de vida de una fase.
    Ejemplo:
        with log_phase(logger, "extract_pdf", pdf=pdf_name):
            ...
    """
    start_time = log_phase_start(logger, phase, **kwargs)
    try:
        yield
    except Exception as e:
        log_event(
            logger,
            logging.ERROR,
            f"Fase fallida: {phase}",
            phase=phase,
            error=str(e),
            **kwargs,
        )
        raise
    finally:
        # Usamos INFO por defecto si termina correctamente, pero podría ser DEBUG
        log_phase_end(logger, phase, start_time, level=logging.DEBUG, **kwargs)
