import logging
import os


# Configure the log format
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "DEBUG").upper(),
    format='%(asctime)s - %(module)s - %(lineno)d - %(levelname)s - %(message)s'
)

_logger = logging.getLogger(__name__)

__all__ = ["_logger"]
