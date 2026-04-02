import json
import logging
from datetime import datetime, timezone


class StructuredJsonFormatter(logging.Formatter):
    """
    Formateador que emite logs como JSON estructurado,
    incluyendo siempre timestamp, nivel, logger, mensaje, y opcionalmente
    request_id, module, phase, elapsed_ms, y exception_info.
    """

    def format(self, record):
        # Campos obligatorios
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Extra campos que nos interesan
        if hasattr(record, "request_id") and record.request_id:
            log_record["request_id"] = record.request_id
        if hasattr(record, "module") and record.module:
            log_record["module"] = record.module
        elif hasattr(record, "name"):
            log_record["module"] = record.name

        if hasattr(record, "phase"):
            log_record["phase"] = record.phase
        if hasattr(record, "elapsed_ms"):
            log_record["elapsed_ms"] = record.elapsed_ms

        # Control de volumen de logs: Limitar strings largos si están presentes en extra.
        # Esto previene que se loggeen PDFs completos o textos muy grandes.
        MAX_STRING_LENGTH = 500

        # Inject extra attributes that might be passed via 'extra'
        # We skip standard LogRecord attributes to avoid duplication
        # See: https://docs.python.org/3/library/logging.html#logrecord-attributes
        standard_attrs = {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
            "request_id",
            "phase",
            "elapsed_ms",
        }

        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
                    log_record[key] = value[:MAX_STRING_LENGTH] + "... [TRUNCATED]"
                else:
                    log_record[key] = value

        # Excepciones
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)


class ColorFormatter(logging.Formatter):
    """
    Formateador simple con colores para desarrollo local (consola).
    """

    COLORS = {
        logging.DEBUG: "\033[94m",  # Azul
        logging.INFO: "\033[92m",  # Verde
        logging.WARNING: "\033[93m",  # Amarillo
        logging.ERROR: "\033[91m",  # Rojo
        logging.CRITICAL: "\033[91m\033[1m",  # Rojo negrita
    }
    RESET = "\033[0m"

    def format(self, record):
        log_fmt = f"{self.COLORS.get(record.levelno, self.RESET)}%(asctime)s - %(levelname)s - %(name)s - %(message)s{self.RESET}"
        if hasattr(record, "request_id") and record.request_id:
            log_fmt = f"{self.COLORS.get(record.levelno, self.RESET)}%(asctime)s - %(levelname)s - [%(request_id)s] %(name)s - %(message)s{self.RESET}"

        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)
