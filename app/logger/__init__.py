from .custom_logger import CustomLogger as _CustomLogger

try:
    from .custom_logger import CustomLogger 
except ImportError:
    CustomLogger = _CustomLogger

# Exposing a global structlog-style logger
GLOBAL_LOGGER = CustomLogger().get_logger(__name__)