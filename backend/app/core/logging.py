"""Логування через structlog.

У розробці: кольоровий рядок у консоль. У продакшні: один JSON-об'єкт на рядок
(зручно для збирання логів). Усі записи, включно зі стандартним `logging`
(uvicorn, sqlalchemy), проходять через той самий форматер.
`request_id` додається до кожного запису автоматично (див. core/middleware.py).
"""
import logging
import sys

import structlog


def dev_exception_formatter() -> structlog.dev.RichTracebackFormatter:
    """Форматер винятків для консолі розробника.

    За замовчуванням structlog/rich друкує ЛОКАЛЬНІ ЗМІННІ кожного кадру стека (до 100 кадрів).
    У типовому запиті через SQLAlchemy це кілька мегабайтів тексту на ОДИН виняток: сервер
    хвилинами тільки те й робить, що друкує, і здається завислим. Тому локальні змінні
    вимкнено, а кількість кадрів обмежено; для налагодження вистачає самого стека.
    (У продакшні логи JSON, там цього форматера немає.)
    """
    return structlog.dev.RichTracebackFormatter(show_locals=False, max_frames=30)


def configure_logging(level: str = 'INFO', json_logs: bool = False) -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt='iso', utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    if json_logs:
        final_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,  # у JSON винятки йдуть рядком
            structlog.processors.JSONRenderer(),
        ]
    else:
        final_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(
                colors=sys.stderr.isatty(),
                exception_formatter=dev_exception_formatter(),  # сам красиво друкує винятки
            ),
        ]
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=final_processors,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]  # заміна, а не додавання: повторний виклик не дублює рядки
    root.setLevel(level)

    # uvicorn пише через ті самі обробники; його access-лог замінює наш (middleware),
    # інакше кожен запит потрапляв би в лог двічі
    for name in ('uvicorn', 'uvicorn.error'):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    access = logging.getLogger('uvicorn.access')
    access.handlers.clear()
    access.propagate = False


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
