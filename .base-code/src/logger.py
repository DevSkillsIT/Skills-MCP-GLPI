"""
Sistema de logging centralizado para MCP GLPI.
"""

import logging
import logging.handlers
from pathlib import Path
from src.config import settings


class LoggerService:
    """Serviço de logging com suporte a arquivos e console."""

    _instance = None
    _logger = None

    def __new__(cls):
        """Implementação do padrão Singleton."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Inicializa o logger."""
        self._logger = logging.getLogger("mcp-glpi")
        self._logger.setLevel(getattr(logging, settings.log_level))

        # Cria diretório de logs se não existir
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Handler para arquivo
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)

        # Handler para console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, settings.log_level))

        # Formato
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Adiciona handlers
        if not self._logger.handlers:
            self._logger.addHandler(file_handler)
            self._logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        """Retorna a instância do logger."""
        return self._logger

    def debug(self, message: str, *args, **kwargs):
        """Log de debug."""
        self._logger.debug(message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        """Log de informação."""
        self._logger.info(message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        """Log de aviso."""
        self._logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        """Log de erro."""
        self._logger.error(message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs):
        """Log crítico."""
        self._logger.critical(message, *args, **kwargs)


# Instância global
logger = LoggerService()
