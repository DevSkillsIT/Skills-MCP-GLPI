from typing import Optional, Dict, Any

class GLPIError(Exception):
    """Erro genérico do GLPI."""
    def __init__(self, code: int, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class ValidationError(GLPIError):
    """Erro de validação."""
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(400, message, {"field": field})


class NotFoundError(GLPIError):
    """Erro de recurso não encontrado."""
    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            404,
            f"{resource} not found",
            {"resource": resource, "identifier": str(identifier)}
        )


class AuthenticationError(GLPIError):
    """Erro de autenticação."""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(401, message)


class PermissionError(GLPIError):
    """Erro de permissão."""
    def __init__(self, message: str = "Permission denied"):
        super().__init__(403, message)


class TimeoutError(GLPIError):
    def __init__(self, message: str = "Request timeout"):
        super().__init__(408, message)


class RateLimitError(GLPIError):
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(429, message)


class SimilarityError(GLPIError):
    def __init__(self, message: str = "Similarity check failed"):
        super().__init__(422, message)


class MethodNotFoundError(GLPIError):
    def __init__(self, method_name: str = "Method not found"):
        super().__init__( -32601, f"Method '{method_name}' not found")


class InvalidRequestError(GLPIError):
    def __init__(self, message: str = "Invalid request", details: Optional[Dict[str, Any]] = None):
        super().__init__(-32600, message, details)


# HTTP to JSON-RPC error mapping - Conforme SPEC.md/AC09 (BUG-CRIT-03)
HTTP_TO_JSONRPC = {
    400: -32602,  # Invalid params (ValidationError)
    401: -32001,  # Unauthorized (AuthenticationError)
    403: -32001,  # Forbidden (treated as auth error)
    404: -32004,  # Not found
    429: -32010,  # Rate limit exceeded
    500: -32099,  # Internal error
    502: -32003,  # Service unavailable
    503: -32003,  # Service unavailable
}
