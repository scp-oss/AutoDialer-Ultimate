import logging
import sys
import uuid
from logging.handlers import RotatingFileHandler
from contextvars import ContextVar

correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='')

class CorrelationFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = correlation_id_var.get() or 'no-id'
        return True

def setup_logger(name: str, log_file: str = "/opt/autodialer/logs/autodialer.log"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s'
    )
    console.setFormatter(console_format)
    
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=10)
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s'
    )
    file_handler.setFormatter(file_format)
    
    console.addFilter(CorrelationFilter())
    file_handler.addFilter(CorrelationFilter())
    
    logger.addHandler(console)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logger("autodialer")
