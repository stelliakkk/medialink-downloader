"""Local diagnostics with no exception messages, payloads, URLs or user paths."""

from hashlib import sha256
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = logging.getLogger("medialink.diagnostics")
LOGGER.addHandler(logging.NullHandler())
LOGGER.propagate = False


def configure_diagnostics(directory: Path) -> None:
    try:
        handler = RotatingFileHandler(directory / "diagnostics.log", maxBytes=256 * 1024,
                                      backupCount=2, encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    for previous in LOGGER.handlers[:]:
        LOGGER.removeHandler(previous)
        previous.close()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.ERROR)


def unexpected_error(error: Exception, context: str) -> str:
    locations = []
    trace = error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        module = trace.tb_frame.f_globals.get("__name__", "unknown")
        locations.append(f"{module}.{code.co_name}:{trace.tb_lineno}")
        trace = trace.tb_next
    signature = f"{type(error).__name__}|{'|'.join(locations[-8:])}"
    identifier = "ML-" + sha256(signature.encode()).hexdigest()[:10].upper()
    # Never use exc_info, repr(error), exception messages, frame locals or absolute paths.
    try:
        LOGGER.error("id=%s operation=%s exception=%s locations=%s",
                     identifier, context, type(error).__name__, " > ".join(locations[-8:]))
    except OSError:
        pass
    return f"{context}未完成，请重试。若持续失败，请提供错误编号 {identifier}。"
