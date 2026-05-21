import logging
import logging.handlers
import os
import structlog


_SENSITIVE_KEYS = frozenset({"token", "authorization", "password", "api_token", "api_key", "secret"})


def _sanitize(logger, method, event_dict):
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in _SENSITIVE_KEYS):
            event_dict[key] = "***"
    return event_dict


def configure_logging(log_level: str = "INFO", log_file: str = "logs/bot.log") -> None:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _sanitize,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(json_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
            foreign_pre_chain=shared_processors,
        )
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
