import json
import logging
from .logging_utils import get_request_id, get_trace_id


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
        Aplica el color correspondiente al nivel de log e inyecta el request_id y el trace_id.
        """
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()

        trace_id = get_trace_id()
        if trace_id and trace_id != record.request_id:
            record.request_id = f"{record.request_id[:8]}...|T:{trace_id[:8]}..."

        log_fmt = self.FORMATS.get(record.levelno, self.format_str)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)


def safe_serialize(
    obj,
    max_str_len=2000,
    max_list_items=50,
    max_dict_items=50,
    max_depth=3,
    _current_depth=0,
):
    """
    Serializa objetos de forma segura y acotada.
    Trunca strings muy largos, limita elementos de listas y dicts y previene recursión infinita.
    """
    if _current_depth > max_depth:
        return "<max_depth_reached>"

    if isinstance(obj, str):
        if len(obj) > max_str_len:
            return obj[:max_str_len] + f"... <truncated {len(obj) - max_str_len} chars>"
        return obj
    elif isinstance(obj, (int, float, bool, type(None))):
        return obj
    elif isinstance(obj, (list, tuple, set)):
        lst = list(obj)
        truncated_list = [
            safe_serialize(
                item,
                max_str_len,
                max_list_items,
                max_dict_items,
                max_depth,
                _current_depth + 1,
            )
            for item in lst[:max_list_items]
        ]
        if len(lst) > max_list_items:
            truncated_list.append(f"<truncated {len(lst) - max_list_items} items>")
        return truncated_list
    elif isinstance(obj, dict):
        truncated_dict = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= max_dict_items:
                truncated_dict["_truncated"] = (
                    f"<{len(obj) - max_dict_items} keys truncated>"
                )
                break
            truncated_dict[str(k)] = safe_serialize(
                v,
                max_str_len,
                max_list_items,
                max_dict_items,
                max_depth,
                _current_depth + 1,
            )
        return truncated_dict
    else:
        # Fallback a representación por string truncada
        rep = str(obj)
        if len(rep) > max_str_len:
            return rep[:max_str_len] + f"... <truncated {len(rep) - max_str_len} chars>"
        return rep


class StructuredJsonFormatter(logging.Formatter):
    """
    Formateador de logs JSON estructurado para ficheros.
    """

    def format(self, record):
        """
        Formatea el registro como un objeto JSON unilineal.
        """
        req_id = getattr(record, "request_id", get_request_id())
        trace_id = getattr(record, "trace_id", get_trace_id())

        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "request_id": req_id,
            "trace_id": trace_id,
        }

        # Extraemos contexto adicional de log_event si existe
        if hasattr(record, "event_context") and isinstance(record.event_context, dict):
            ctx = record.event_context.copy()

            # Extraemos campos base al primer nivel
            if "event" in ctx:
                log_object["event"] = ctx.pop("event")
            if "duration_ms" in ctx:
                log_object["duration_ms"] = ctx.pop("duration_ms")
            if "error" in ctx:
                log_object["error"] = str(ctx.pop("error"))

            # Serializamos el resto de forma segura como `extra`
            if ctx:
                log_object["extra"] = safe_serialize(ctx)

        # Usamos record.getMessage() de forma segura, o como fallback si no hay evento
        msg = record.getMessage()
        if msg and msg != log_object.get("event"):
            log_object["message"] = safe_serialize(msg)

        # Compatibilidad con los logs antiguos de citations.context que mandan dicts como mensaje
        if isinstance(record.msg, dict):
            # En caso de que se pase un dict como mensaje lo volcamos sobre `extra`
            extra_msg = safe_serialize(record.msg)
            if "extra" in log_object:
                if isinstance(log_object["extra"], dict) and isinstance(
                    extra_msg, dict
                ):
                    log_object["extra"].update(extra_msg)
                else:
                    log_object["extra"] = {
                        "_context": log_object["extra"],
                        "_msg": extra_msg,
                    }
            else:
                log_object["extra"] = extra_msg
            log_object["message"] = "JSON Payload"

        if record.exc_info:
            log_object["exception"] = self.formatException(record.exc_info)

        # Siempre devuelve un json serializable usando default str por si acaso
        return json.dumps(log_object, default=str)
