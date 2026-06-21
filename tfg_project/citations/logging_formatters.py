# Formateadores de logging: colores para consola y salida JSON estructurada para ficheros de log.
import json
import logging

from .logging_utils import get_request_id


class ColorFormatter(logging.Formatter):
    """
    Formateador de logs que añade colores a la salida de consola usando códigos ANSI.
    Formato: [TIMESTAMP] [NIVEL] [LOGGER] [REQ_ID] MENSAJE
    """

    grey = "\x1b[38;20m"
    blue = "\x1b[34;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    format_str = "%(asctime)s %(levelname)-8s [%(name)s] [%(request_id)s] %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: green + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset,
    }

    def format(self, record):
        """
        Aplica el color correspondiente al nivel de log e inyecta el request_id.
        """
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()

        log_fmt = self.FORMATS.get(record.levelno, self.format_str)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)


class StructuredJsonFormatter(logging.Formatter):
    """
    Formateador de logs JSON estructurado para ficheros.
    """

    def format(self, record):
        """
        Formatea el registro como un objeto JSON unilineal.
        """
        req_id = getattr(record, "request_id", get_request_id())

        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": req_id,
        }

        # Extraemos contexto adicional de log_event si existe
        if hasattr(record, "event_context") and isinstance(record.event_context, dict):
            # Extraemos la "phase" si está presente, el resto lo metemos en "extra"
            ctx = record.event_context.copy()
            if "phase" in ctx:
                log_object["phase"] = ctx.pop("phase")
            if ctx:
                log_object["extra"] = ctx

        # Compatibilidad con los logs antiguos de citations.context que mandan dicts como mensaje
        if isinstance(record.msg, dict):
            log_object.update(record.msg)
            # Reemplazamos el mensaje para que no sea un string del diccionario
            log_object["message"] = "JSON Payload"

        if record.exc_info:
            log_object["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_object)
