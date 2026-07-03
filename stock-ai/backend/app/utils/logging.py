from __future__ import annotations

import logging


def configure_logging(log_level: str) -> None:
    """Configure console logging once for the entire application."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.setLevel(log_level)
        return

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
