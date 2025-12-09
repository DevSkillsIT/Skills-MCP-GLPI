"""
Modelos Pydantic para validação de dados GLPI.
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class MCPRequest(BaseModel):
    """
    Requisição JSON-RPC 2.0.

    IMPORTANTE: No JSON-RPC 2.0, o campo 'id' é opcional.
    - Requests: têm 'id' (esperam resposta)
    - Notifications: NÃO têm 'id' (não esperam resposta)

    O Claude Code envia 'notifications/initialized' SEM id.
    """
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[int] = None


class MCPResponse(BaseModel):
    """
    Resposta JSON-RPC 2.0.

    IMPORTANTE: Conforme especificação JSON-RPC 2.0:
    - 'result' e 'error' são mutuamente exclusivos
    - 'id' é opcional (notificações não têm id)

    O exclude_none=True garante que campos None não sejam serializados.
    """
    model_config = ConfigDict(exclude_none=True)

    jsonrpc: str = "2.0"
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[int] = None


class Tool(BaseModel):
    """Definição de uma tool MCP."""
    name: str
    description: str
    inputSchema: Dict[str, Any]


class ToolsListResponse(BaseModel):
    """Resposta da listagem de tools."""
    tools: List[Tool]


class GLPIEntity(BaseModel):
    """Entidade base do GLPI."""
    id: int = Field(..., description="ID da entidade")
    name: str = Field(..., description="Nome da entidade")


class Ticket(GLPIEntity):
    """Modelo de Ticket."""
    title: str = Field(..., description="Título do ticket")
    description: Optional[str] = None
    status: str = Field(default="new", description="Status do ticket")
    priority: int = Field(default=3, description="Prioridade (1-5)")
    requesters: List[int] = Field(default_factory=list, description="IDs dos solicitantes")
    assigned_to: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        """Valida prioridade (1-5)."""
        if not 1 <= v <= 5:
            raise ValueError("Priority must be between 1 and 5")
        return v


class Asset(GLPIEntity):
    """Modelo de Asset."""
    asset_type: str = Field(..., description="Tipo de asset (Computer, Monitor, Printer)")
    serial_number: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    status: str = Field(default="active", description="Status do asset")
    location_id: Optional[int] = None


class User(GLPIEntity):
    """Modelo de Usuário."""
    firstname: str = Field(..., description="Primeiro nome")
    lastname: str = Field(..., description="Último nome")
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = Field(default=True)


class Group(GLPIEntity):
    """Modelo de Grupo."""
    comment: Optional[str] = None
    is_active: bool = Field(default=True)


class Entity(GLPIEntity):
    """Modelo de Entidade/Organização."""
    completename: Optional[str] = None
    type: Optional[str] = None
    phone: Optional[str] = None


class Location(GLPIEntity):
    """Modelo de Localização."""
    completename: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


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
    """Erro de timeout."""
    def __init__(self, message: str = "Request timeout"):
        super().__init__(504, message)
