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

        self.logger = logging.getLogger("WeebotAgent")

        # When a custom path is given, always reconfigure handlers so that
        # each test/call gets handlers pointing at the requested file.
        # When using the default path, skip setup if handlers already exist
        # to avoid duplicates in normal application usage.
        if log_path is not None:
            # Remove existing handlers before adding new ones
            for handler in self.logger.handlers[:]:
                handler.close()
                self.logger.removeHandler(handler)
        elif self.logger.handlers:
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
