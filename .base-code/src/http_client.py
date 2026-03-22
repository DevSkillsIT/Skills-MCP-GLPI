"""
Cliente HTTP para comunicação com GLPI API.
"""

import httpx
from typing import Optional, Dict, Any, List
from src.config import settings
from src.logger import logger
from src.models import (
    AuthenticationError,
    TimeoutError as GLPITimeoutError,
    GLPIError,
)
import asyncio


class HTTPClient:
    """Cliente HTTP assíncrono para GLPI."""

    def __init__(self):
        """Inicializa o cliente HTTP."""
        self._client: Optional[httpx.AsyncClient] = None
        self._session_token: Optional[str] = None

    async def __aenter__(self):
        """Context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.disconnect()

    async def connect(self):
        """Estabelece conexão com GLPI."""
        if self._client is None:
            logger.info("Connecting to GLPI at %s", settings.glpi_base_url)
            self._client = httpx.AsyncClient(
                base_url=settings.glpi_base_url,
                headers=settings.glpi_headers,
                timeout=settings.request_timeout,
            )

    async def disconnect(self):
        """Fecha conexão com GLPI."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("Disconnected from GLPI")

    async def _ensure_connected(self):
        """Garante que o cliente está conectado."""
        if self._client is None:
            await self.connect()

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Faz requisição GET."""
        await self._ensure_connected()
        try:
            logger.debug("GET %s with params %s", endpoint, params)
            response = await self._client.get(endpoint, params=params, **kwargs)
            return self._handle_response(response)
        except asyncio.TimeoutError:
            logger.error("Timeout on GET %s", endpoint)
            raise GLPITimeoutError()
        except Exception as e:
            logger.error("Error on GET %s: %s", endpoint, str(e))
            raise GLPIError(500, f"Request failed: {str(e)}")

    async def post(
        self,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Faz requisição POST."""
        await self._ensure_connected()
        try:
            logger.debug("POST %s with data %s", endpoint, json)
            response = await self._client.post(endpoint, json=json, **kwargs)
            return self._handle_response(response)
        except asyncio.TimeoutError:
            logger.error("Timeout on POST %s", endpoint)
            raise GLPITimeoutError()
        except Exception as e:
            logger.error("Error on POST %s: %s", endpoint, str(e))
            raise GLPIError(500, f"Request failed: {str(e)}")

    async def put(
        self,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Faz requisição PUT."""
        await self._ensure_connected()
        try:
            logger.debug("PUT %s with data %s", endpoint, json)
            response = await self._client.put(endpoint, json=json, **kwargs)
            return self._handle_response(response)
        except asyncio.TimeoutError:
            logger.error("Timeout on PUT %s", endpoint)
            raise GLPITimeoutError()
        except Exception as e:
            logger.error("Error on PUT %s: %s", endpoint, str(e))
            raise GLPIError(500, f"Request failed: {str(e)}")

    async def delete(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Faz requisição DELETE."""
        await self._ensure_connected()
        try:
            logger.debug("DELETE %s", endpoint)
            response = await self._client.delete(endpoint, **kwargs)
            return self._handle_response(response)
        except asyncio.TimeoutError:
            logger.error("Timeout on DELETE %s", endpoint)
            raise GLPITimeoutError()
        except Exception as e:
            logger.error("Error on DELETE %s: %s", endpoint, str(e))
            raise GLPIError(500, f"Request failed: {str(e)}")

    async def patch(
        self,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Faz requisição PATCH."""
        await self._ensure_connected()
        try:
            logger.debug("PATCH %s with data %s", endpoint, json)
            response = await self._client.patch(endpoint, json=json, **kwargs)
            return self._handle_response(response)
        except asyncio.TimeoutError:
            logger.error("Timeout on PATCH %s", endpoint)
            raise GLPITimeoutError()
        except Exception as e:
            logger.error("Error on PATCH %s: %s", endpoint, str(e))
            raise GLPIError(500, f"Request failed: {str(e)}")

    @staticmethod
    def _handle_response(response: httpx.Response) -> Dict[str, Any]:
        """Processa resposta HTTP e lida com erros."""
        logger.debug("Response status: %s", response.status_code)

        # Autenticação
        if response.status_code == 401:
            logger.error("Authentication error: Invalid token or credentials")
            raise AuthenticationError()

        # Permissão
        if response.status_code == 403:
            logger.error("Permission error: Access denied")
            raise GLPIError(403, "Permission denied")

        # Não encontrado
        if response.status_code == 404:
            logger.error("Not found: %s", response.text)
            raise GLPIError(404, "Resource not found")

        # Erro no servidor
        if response.status_code >= 500:
            logger.error("Server error: %s", response.text)
            raise GLPIError(response.status_code, "Server error")

        # Erro geral
        if not response.is_success:
            logger.error("Error response: %s", response.text)
            raise GLPIError(response.status_code, response.text)

        # Sucesso
        try:
            return response.json() if response.text else {}
        except Exception as e:
            logger.error("Failed to parse response JSON: %s", str(e))
            return {"status": "success", "data": response.text}


# Instância global
http_client = HTTPClient()
