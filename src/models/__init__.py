"""
Models Package - Modelos e exceções do MCP GLPI
"""

from .exceptions import (
    GLPIError,
    NotFoundError,
    ValidationError,
    SimilarityError,
    AuthenticationError,
    MethodNotFoundError,
    InvalidRequestError,
    TimeoutError,
    HTTP_TO_JSONRPC
)
from .models import (
    MCPRequest,
    MCPResponse,
    Tool,
    ToolsListResponse,
    GLPIEntity,
    Ticket,
    Asset,
    User,
    Group,
    Entity,
    Location
)

__all__ = [
    "GLPIError",
    "NotFoundError", 
    "ValidationError",
    "SimilarityError",
    "AuthenticationError",
    "MethodNotFoundError",
    "InvalidRequestError",
    "TimeoutError",
    "HTTP_TO_JSONRPC",
    "MCPRequest",
    "MCPResponse",
    "Tool",
    "ToolsListResponse",
    "GLPIEntity",
    "Ticket",
    "Asset",
    "User",
    "Group",
    "Entity",
    "Location"
]
