"""Logging setup shared by the API and the worker."""

import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("reviewcrew").setLevel(level)
    # arq reports each job's start, result and duration at INFO.
    logging.getLogger("arq").setLevel(level)
