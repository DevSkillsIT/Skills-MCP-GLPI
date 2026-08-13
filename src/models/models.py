"""
Modelos Pydantic para validação de dados GLPI.
"""

import re

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


def _coerce_glpi_id(v):
    """Extrai o id inteiro de um campo GLPI que pode vir expandido.

    GLPI com expand_dropdowns=true retorna foreign keys como texto no
    formato 'NOME (#id)' — por exemplo 'Matriz (#0)' ou 'a.silva (#378)' —
    em vez do id cru. Aceita tambem int, string numerica e o dict de
    dropdown ({'id': N}). Retorna None quando nao ha id parseavel.
    """
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        return _coerce_glpi_id(v.get("id"))
    if isinstance(v, str):
        # 'Nome (#123)' -> 123
        m = re.search(r"#(\d+)", v)
        if m:
            return int(m.group(1))
        # string puramente numerica
        if v.strip().lstrip("-").isdigit():
            return int(v.strip())
        return None
    return None


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
    """Entidade base do GLPI 11 — campos opcionais e extras permitidos."""
    model_config = ConfigDict(extra="allow")  # GLPI retorna 80+ fields, nao queremos rejeitar
    id: int = Field(..., description="ID da entidade")
    name: Optional[str] = Field(default="", description="Nome da entidade")


class Ticket(GLPIEntity):
    """Modelo de Ticket — permissivo para o shape do GLPI 11.

    @MX:NOTE: GLPI 11 retorna `status: int` (1=Novo..6=Fechado) e nao tem `title`
    (usa `name`). Campos opcionais para tolerar variacoes do payload.
    @MX:REASON: Prompts (glpi_ticket_summary etc.) crashavam com pydantic
    ValidationError porque o model legacy era estrito demais.
    """
    title: Optional[str] = Field(default=None, description="Alias legado de name")
    content: Optional[str] = None
    description: Optional[str] = None
    status: Optional[int] = Field(default=None, description="Status code GLPI (1-6)")
    priority: Optional[int] = Field(default=None, description="Prioridade (1-6)")
    urgency: Optional[int] = None
    impact: Optional[int] = None
    requesters: List[int] = Field(default_factory=list)
    assigned_to: Optional[int] = None
    entities_id: Optional[int] = None
    users_id_recipient: Optional[int] = None
    date: Optional[str] = None
    date_mod: Optional[str] = None
    time_to_resolve: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("priority", "status", "urgency", "impact", mode="before")
    @classmethod
    def coerce_to_int(cls, v):
        """Coerce numeric strings to int (GLPI as vezes retorna string)."""
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @field_validator("entities_id", "users_id_recipient", "assigned_to", mode="before")
    @classmethod
    def coerce_fk_id(cls, v):
        """Aceita FKs expandidas no formato 'NOME (#id)' alem de id cru.

        @MX:REASON: get_ticket usa expand_dropdowns; sem isto os prompts
        glpi_ticket_summary e glpi_incident_investigation crashavam com
        int_parsing ao receber 'Matriz (#0)' / 'a.silva (#378)'.
        """
        return _coerce_glpi_id(v)


class Asset(GLPIEntity):
    """Modelo de Asset — permissivo para o shape do GLPI 11."""
    asset_type: Optional[str] = Field(default=None, description="Tipo (Computer, Monitor, ...)")
    serial: Optional[str] = None
    serial_number: Optional[str] = None
    otherserial: Optional[str] = None  # patrimonio no GLPI
    model: Optional[str] = None
    models_id: Optional[int] = None
    manufacturer: Optional[str] = None
    manufacturers_id: Optional[int] = None
    status: Optional[int] = None
    states_id: Optional[int] = None
    location_id: Optional[int] = None
    locations_id: Optional[int] = None
    entities_id: Optional[int] = None
    users_id: Optional[int] = None


class User(GLPIEntity):
    """Modelo de Usuário — permissivo para o shape do GLPI 11."""
    firstname: Optional[str] = Field(default=None, description="Primeiro nome")
    lastname: Optional[str] = Field(default=None, description="Último nome")
    realname: Optional[str] = None  # alias legado do lastname
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[int] = Field(default=1)
    entities_id: Optional[int] = None


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


