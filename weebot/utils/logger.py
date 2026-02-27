"""Logging utility for weebot."""
import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("logs/agent.log")


class AgentLogger:
    def __init__(self):
        self.logger = logging.getLogger("WeebotAgent")
        self.logger.setLevel(logging.DEBUG)
        
        # Ensure logs directory exists
        LOG_FILE.parent.mkdir(exist_ok=True)
        
        # File Handler with detailed formatting
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(module)-12s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        
        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(console_format)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def get_logger(self):
        return self.logger


def get_logger():
    return AgentLogger().get_logger()
