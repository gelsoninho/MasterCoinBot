import os
import sys
import logging
from loguru import logger

def setup_logging():
    """Configure logging settings for the application"""
    log_level = os.getenv("LOG_LEVEL", "INFO")
    
    # Remove default loguru handler
    logger.remove()
    
    # Add console handler
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # Add file handler
    logger.add(
        "logs/copy_trader_{time}.log",
        rotation="500 MB",
        retention="10 days",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )
    
    # Configure logging for 3rd party libraries
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # Explicitly set levels for some chatty libraries
    for logger_name in ("asyncio", "telegram", "urllib3", "matplotlib", "binance"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


class InterceptHandler(logging.Handler):
    """Intercept standard logging messages toward Loguru"""
    
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )
