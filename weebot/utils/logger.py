"""Logging utility for weebot."""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Union

LOG_FILE = Path("logs/agent.log")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB


class AgentLogger:
    def __init__(self, log_path: Union[Path, str, None] = None) -> None:
        self.log_path = Path(log_path) if log_path else LOG_FILE
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        if log_path is not None:
            # Use a unique logger name per custom path to avoid singleton interference
            logger_name = f"WeebotAgent.{Path(log_path).name}"
        else:
            logger_name = "WeebotAgent"
        self.logger = logging.getLogger(logger_name)

        if self.logger.handlers:
            return

        self.logger.setLevel(logging.DEBUG)

        # Rotating file handler: 5 MB max, 1 backup
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_path,
            maxBytes=MAX_BYTES,
            backupCount=1,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(module)-12s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        return self.logger


def get_logger(log_path: Union[Path, str, None] = None) -> logging.Logger:
    return AgentLogger(log_path=log_path).get_logger()
