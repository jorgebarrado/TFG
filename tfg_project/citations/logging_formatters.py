"""Formateadores de logs personalizados."""

import json
import logging


class JsonFormatter(logging.Formatter):
    """Formateador de logs que convierte el registro en una cadena JSON.

    Útil para ingestión de logs estructurados.
    """

    def format(self, record):
        """Formatea el registro como un objeto JSON.

        Args:
            record (logging.LogRecord): El registro de log a formatear.

        Returns:
            str: El registro formateado como una cadena JSON.
        """
        if isinstance(record.msg, dict):
            log_object = record.msg.copy()
        else:
            log_object = {"message": record.getMessage()}

        log_object["timestamp"] = self.formatTime(record, self.datefmt)
        log_object["level"] = record.levelname
        return json.dumps(log_object)
