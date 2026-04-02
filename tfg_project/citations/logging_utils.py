import logging
import time
from contextlib import contextmanager


def get_logger(name):
    """
    Devuelve un logger por nombre.
    (La configuración real está en settings.py o middleware)
    """
    return logging.getLogger(name)


@contextmanager
def log_phase(logger, phase_name, metadata=None):
    """
    Context manager que loguea el inicio y el final de una fase,
    calculando automáticamente el tiempo transcurrido (elapsed_ms).
    """
    if metadata is None:
        metadata = {}

    extra = {"phase": phase_name}
    extra.update(metadata)

    logger.debug(f"Starting phase: {phase_name}", extra=extra)

    start_time = time.time()
    try:
        yield
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        extra["elapsed_ms"] = elapsed_ms
        logger.debug(f"Completed phase: {phase_name}", extra=extra)
    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        extra["elapsed_ms"] = elapsed_ms
        logger.exception(f"Error in phase: {phase_name} - {str(e)}", extra=extra)
        raise


def log_phase_start(logger, phase_name, metadata=None):
    if metadata is None:
        metadata = {}
    extra = {"phase": phase_name}
    extra.update(metadata)
    logger.debug(f"Starting phase: {phase_name}", extra=extra)


def log_phase_end(logger, phase_name, start_time, metadata=None, success=True):
    if metadata is None:
        metadata = {}
    extra = {"phase": phase_name}
    extra.update(metadata)
    elapsed_ms = round((time.time() - start_time) * 1000, 2)
    extra["elapsed_ms"] = elapsed_ms
    extra["success"] = success
    if success:
        logger.debug(f"Completed phase: {phase_name}", extra=extra)
    else:
        logger.error(f"Failed phase: {phase_name}", extra=extra)
