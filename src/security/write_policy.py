"""
Per-operation write authorization for the GLPI MCP.

Why this exists
---------------
The MCP exposes roughly thirty state-changing actions across tickets, assets,
admin records and webhooks. Today an instance either has a GLPI token that can
write or it does not -- there is no way to say "this instance may comment on
tickets but must never create users". This module supplies that missing dial:
a global read-only switch plus one environment variable per operation.

How this relates to the other guards
------------------------------------
Three complementary layers, in the order a call passes through them:

1. `WritePolicy` (this module) answers "is this instance allowed to perform
   this class of write at all?". It is static configuration, decided by the
   operator, and it covers creation and mutation -- not just deletion.
2. `src/utils/safety_guard.py` answers "did a human deliberately confirm this
   specific destructive call?". It requires a confirmation token plus a written
   reason, and it only covers the five delete_* operations.
3. `src/security/idempotency.py` answers "did this exact call already happen?".

They are intentionally not merged. The policy is a coarse capability gate that
can be evaluated before any argument is parsed; the safety guard is a per-call
human-in-the-loop challenge that needs the caller's token and reason. This
module therefore never asks for a confirmation token and never re-implements
the guard's token comparison -- it only records, in `WriteOperationSpec.
safety_guard_operation`, which guard operation (if any) will run afterwards.
Every destructive operation now has a safety-guard counterpart. Until this
round, `location.delete` had none -- the guard covered ticket, asset, user and
webhook, while deleting a location or a group went through with no confirmation
at all. That gap was an accident of how the guard grew, not a decision, so both
operations were added on the guard side and linked here.

Configuration (environment only, never reads .env or credentials):
    GLPI_READ_ONLY                default "false"  -- blocks every write
    GLPI_ALLOW_<OPERATION>        one per operation, see WRITE_OPERATIONS

Every variable name is declared in `WRITE_OPERATIONS` rather than spelled out
at each call site, so `python -c "import ..."` can print the full contract.

Default policy
--------------
Non-destructive writes default to enabled, destructive writes (delete_*)
default to disabled. Rationale: turning every write off by default would break
existing tenants the moment this module is wired in, while an accidental
deletion is unrecoverable. Operators wanting a stricter posture apply
`PROFILE_READ_ONLY` or `PROFILE_TICKET_OPERATOR`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from src.models.exceptions import GLPIError

logger = logging.getLogger("mcp-glpi.security.write_policy")


ENV_READ_ONLY = "GLPI_READ_ONLY"
ENV_ALLOW_PREFIX = "GLPI_ALLOW_"

DEFAULT_READ_ONLY = False

_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "on", "sim"})
_FALSY = frozenset({"0", "false", "f", "no", "n", "off", "nao"})


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    logger.warning(
        "Invalid boolean for %s=%r; falling back to default %r", name, raw, default
    )
    return default


# ---------------------------------------------------------------------------
# Operation catalogue
# ---------------------------------------------------------------------------


class WriteOperation(str, Enum):
    """Every state-changing action the MCP can perform today.

    Values mirror the tool actions in src/tools/consolidated_*.py. Entities are
    absent on purpose: manage_admin(resource="entities") only supports "get".
    """

    # manage_tickets
    TICKET_CREATE = "ticket.create"
    TICKET_UPDATE = "ticket.update"
    TICKET_DELETE = "ticket.delete"
    TICKET_ASSIGN = "ticket.assign"
    TICKET_CLOSE = "ticket.close"
    TICKET_RESOLVE = "ticket.resolve"
    TICKET_ADD_FOLLOWUP = "ticket.add_followup"

    # manage_ai_analysis
    AI_ANALYSIS_TRIGGER = "ai_analysis.trigger"
    AI_ANALYSIS_PUBLISH = "ai_analysis.publish"

    # manage_assets
    ASSET_CREATE = "asset.create"
    ASSET_UPDATE = "asset.update"
    ASSET_DELETE = "asset.delete"
    ASSET_RESERVATION_CREATE = "asset.reservation_create"
    ASSET_RESERVATION_UPDATE = "asset.reservation_update"

    # manage_admin (resource="users" | "groups" | "locations")
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DELETE = "user.delete"
    GROUP_CREATE = "group.create"
    GROUP_UPDATE = "group.update"
    GROUP_DELETE = "group.delete"
    LOCATION_CREATE = "location.create"
    LOCATION_UPDATE = "location.update"
    LOCATION_DELETE = "location.delete"

    # manage_webhooks
    WEBHOOK_CREATE = "webhook.create"
    WEBHOOK_UPDATE = "webhook.update"
    WEBHOOK_DELETE = "webhook.delete"
    WEBHOOK_TEST = "webhook.test"
    WEBHOOK_TRIGGER = "webhook.trigger"
    WEBHOOK_ENABLE = "webhook.enable"
    WEBHOOK_DISABLE = "webhook.disable"
    WEBHOOK_RETRY = "webhook.retry"

    # -- ITIL records beyond the ticket ------------------------------------
    # One gate per record type: an operator may reasonably allow opening a
    # problem while keeping contracts and suppliers read-only, since those
    # carry commercial data maintained outside the service desk.
    ITIL_CREATE = "itil.create"
    ITIL_UPDATE = "itil.update"
    ITIL_ADD_FOLLOWUP = "itil.add_followup"
    ITIL_LINK_TICKET = "itil.link_ticket"
    # Exclusão tem um portão POR TIPO: liberar a exclusão de um problema é uma
    # decisão diferente de liberar a de um contrato, que carrega dado comercial
    # mantido fora do service desk.
    PROBLEM_DELETE = "problem.delete"
    CHANGE_DELETE = "change.delete"
    PROJECT_DELETE = "project.delete"
    CONTRACT_DELETE = "contract.delete"
    SUPPLIER_DELETE = "supplier.delete"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


def operation_env_var(operation: WriteOperation) -> str:
    """Environment variable that enables `operation`.

    "ticket.create" -> "GLPI_ALLOW_TICKET_CREATE".
    """
    return ENV_ALLOW_PREFIX + operation.value.upper().replace(".", "_")


@dataclass(frozen=True)
class WriteOperationSpec:
    """Everything an operator needs to know about one operation."""

    operation: WriteOperation
    env_var: str
    description: str  # pt-BR without accents (user facing)
    default_enabled: bool
    destructive: bool
    #: Matching key in SafetyGuard.PROTECTED_OPERATIONS, when one exists.
    safety_guard_operation: Optional[str] = None


def _spec(
    operation: WriteOperation,
    description: str,
    *,
    default_enabled: bool = True,
    destructive: bool = False,
    safety_guard_operation: Optional[str] = None,
) -> WriteOperationSpec:
    return WriteOperationSpec(
        operation=operation,
        env_var=operation_env_var(operation),
        description=description,
        default_enabled=default_enabled,
        destructive=destructive,
        safety_guard_operation=safety_guard_operation,
    )


_SPECS: tuple[WriteOperationSpec, ...] = (
    # -- tickets ------------------------------------------------------------
    _spec(WriteOperation.TICKET_CREATE, "Abrir chamado"),
    _spec(WriteOperation.TICKET_UPDATE, "Alterar chamado"),
    _spec(
        WriteOperation.TICKET_DELETE,
        "Excluir chamado",
        default_enabled=False,
        destructive=True,
        safety_guard_operation="delete_ticket",
    ),
    _spec(WriteOperation.TICKET_ASSIGN, "Atribuir chamado a tecnico ou grupo"),
    _spec(WriteOperation.TICKET_CLOSE, "Fechar chamado"),
    _spec(WriteOperation.TICKET_RESOLVE, "Resolver chamado"),
    _spec(WriteOperation.TICKET_ADD_FOLLOWUP, "Adicionar acompanhamento ao chamado"),
    # -- AI analysis --------------------------------------------------------
    _spec(WriteOperation.AI_ANALYSIS_TRIGGER, "Disparar analise de IA do chamado"),
    _spec(
        WriteOperation.AI_ANALYSIS_PUBLISH,
        "Publicar resposta da IA como acompanhamento",
    ),
    # -- assets -------------------------------------------------------------
    _spec(WriteOperation.ASSET_CREATE, "Cadastrar ativo"),
    _spec(WriteOperation.ASSET_UPDATE, "Alterar ativo"),
    _spec(
        WriteOperation.ASSET_DELETE,
        "Excluir ativo",
        default_enabled=False,
        destructive=True,
        safety_guard_operation="delete_asset",
    ),
    _spec(WriteOperation.ASSET_RESERVATION_CREATE, "Criar reserva de ativo"),
    _spec(WriteOperation.ASSET_RESERVATION_UPDATE, "Alterar reserva de ativo"),
    # -- admin --------------------------------------------------------------
    _spec(WriteOperation.USER_CREATE, "Cadastrar usuario"),
    _spec(WriteOperation.USER_UPDATE, "Alterar usuario"),
    _spec(
        WriteOperation.USER_DELETE,
        "Excluir usuario",
        default_enabled=False,
        destructive=True,
        safety_guard_operation="delete_user",
    ),
    _spec(WriteOperation.GROUP_CREATE, "Cadastrar grupo"),
    _spec(WriteOperation.GROUP_UPDATE, "Alterar grupo"),
    _spec(
        WriteOperation.GROUP_DELETE,
        "Excluir grupo",
        default_enabled=False,
        destructive=True,
        safety_guard_operation="delete_group",
    ),
    _spec(WriteOperation.LOCATION_CREATE, "Cadastrar localizacao"),
    _spec(WriteOperation.LOCATION_UPDATE, "Alterar localizacao"),
    _spec(
        WriteOperation.LOCATION_DELETE,
        "Excluir localizacao",
        default_enabled=False,
        destructive=True,
        safety_guard_operation="delete_location",
    ),
    # -- webhooks -----------------------------------------------------------
    _spec(WriteOperation.WEBHOOK_CREATE, "Cadastrar webhook"),
    _spec(WriteOperation.WEBHOOK_UPDATE, "Alterar webhook"),
    _spec(
        WriteOperation.WEBHOOK_DELETE,
        "Excluir webhook",
        default_enabled=False,
        destructive=True,
        safety_guard_operation="delete_webhook",
    ),
    _spec(WriteOperation.WEBHOOK_TEST, "Enviar payload de teste para webhook"),
    _spec(WriteOperation.WEBHOOK_TRIGGER, "Disparar evento para webhooks"),
    _spec(WriteOperation.WEBHOOK_ENABLE, "Ativar webhook"),
    _spec(WriteOperation.WEBHOOK_DISABLE, "Desativar webhook"),
    _spec(WriteOperation.WEBHOOK_RETRY, "Reenviar entregas de webhook"),
    # -- registros ITIL alem do chamado --------------------------------------
    # @MX:NOTE: sem estas entradas, as escritas ITIL ficavam fora do portao.
    # @MX:REASON: a politica foi ligada ao despacho cobrindo apenas chamados,
    # ativos, administrativo e webhooks. Criar um problema, uma mudanca ou um
    # contrato escapava tanto do modo somente-leitura quanto da protecao
    # contra repeticao — justamente os registros de maior peso gerencial.
    _spec(WriteOperation.ITIL_CREATE, "Cadastrar problema, mudanca, projeto, contrato ou fornecedor"),
    _spec(WriteOperation.ITIL_UPDATE, "Alterar registro ITIL"),
    _spec(WriteOperation.ITIL_ADD_FOLLOWUP, "Comentar em registro ITIL"),
    _spec(WriteOperation.ITIL_LINK_TICKET, "Vincular chamado a problema ou mudanca"),
    _spec(
        WriteOperation.PROBLEM_DELETE, "Excluir problema",
        default_enabled=False, destructive=True,
        safety_guard_operation="delete_problem",
    ),
    _spec(
        WriteOperation.CHANGE_DELETE, "Excluir mudanca",
        default_enabled=False, destructive=True,
        safety_guard_operation="delete_change",
    ),
    _spec(
        WriteOperation.PROJECT_DELETE, "Excluir projeto",
        default_enabled=False, destructive=True,
        safety_guard_operation="delete_project",
    ),
    _spec(
        WriteOperation.CONTRACT_DELETE, "Excluir contrato",
        default_enabled=False, destructive=True,
        safety_guard_operation="delete_contract",
    ),
    _spec(
        WriteOperation.SUPPLIER_DELETE, "Excluir fornecedor",
        default_enabled=False, destructive=True,
        safety_guard_operation="delete_supplier",
    ),
)

#: Single source of truth: operation -> spec (name of the env var included).
WRITE_OPERATIONS: Mapping[WriteOperation, WriteOperationSpec] = MappingProxyType(
    {spec.operation: spec for spec in _SPECS}
)

#: Convenience view: every environment variable this module understands.
WRITE_ENV_VARS: Mapping[str, WriteOperation] = MappingProxyType(
    {spec.env_var: spec.operation for spec in _SPECS}
)

DESTRUCTIVE_OPERATIONS: frozenset[WriteOperation] = frozenset(
    spec.operation for spec in _SPECS if spec.destructive
)


# ---------------------------------------------------------------------------
# Tool action resolution
# ---------------------------------------------------------------------------

#: (tool domain, action) -> operation. `resolve_operation` folds the admin
#: resource into the domain, e.g. domain="admin", resource="users".
_TOOL_ACTION_MAP: Mapping[tuple[str, str], WriteOperation] = MappingProxyType(
    {
        ("tickets", "create"): WriteOperation.TICKET_CREATE,
        ("tickets", "update"): WriteOperation.TICKET_UPDATE,
        ("tickets", "delete"): WriteOperation.TICKET_DELETE,
        ("tickets", "assign"): WriteOperation.TICKET_ASSIGN,
        ("tickets", "close"): WriteOperation.TICKET_CLOSE,
        ("tickets", "resolve"): WriteOperation.TICKET_RESOLVE,
        ("tickets", "add_followup"): WriteOperation.TICKET_ADD_FOLLOWUP,
        ("ai_analysis", "trigger"): WriteOperation.AI_ANALYSIS_TRIGGER,
        ("ai_analysis", "publish"): WriteOperation.AI_ANALYSIS_PUBLISH,
        ("assets", "create"): WriteOperation.ASSET_CREATE,
        ("assets", "update"): WriteOperation.ASSET_UPDATE,
        ("assets", "delete"): WriteOperation.ASSET_DELETE,
        ("assets", "create_reservation"): WriteOperation.ASSET_RESERVATION_CREATE,
        ("assets", "update_reservation"): WriteOperation.ASSET_RESERVATION_UPDATE,
        ("admin:users", "create"): WriteOperation.USER_CREATE,
        ("admin:users", "update"): WriteOperation.USER_UPDATE,
        ("admin:users", "delete"): WriteOperation.USER_DELETE,
        ("admin:groups", "create"): WriteOperation.GROUP_CREATE,
        ("admin:groups", "update"): WriteOperation.GROUP_UPDATE,
        ("admin:groups", "delete"): WriteOperation.GROUP_DELETE,
        ("admin:locations", "create"): WriteOperation.LOCATION_CREATE,
        ("admin:locations", "update"): WriteOperation.LOCATION_UPDATE,
        ("admin:locations", "delete"): WriteOperation.LOCATION_DELETE,
        ("webhooks", "create"): WriteOperation.WEBHOOK_CREATE,
        ("webhooks", "update"): WriteOperation.WEBHOOK_UPDATE,
        ("webhooks", "delete"): WriteOperation.WEBHOOK_DELETE,
        ("webhooks", "test"): WriteOperation.WEBHOOK_TEST,
        ("webhooks", "trigger"): WriteOperation.WEBHOOK_TRIGGER,
        ("webhooks", "enable"): WriteOperation.WEBHOOK_ENABLE,
        ("webhooks", "disable"): WriteOperation.WEBHOOK_DISABLE,
        ("webhooks", "retry"): WriteOperation.WEBHOOK_RETRY,
        ("itil", "create"): WriteOperation.ITIL_CREATE,
        ("itil", "update"): WriteOperation.ITIL_UPDATE,
        ("itil", "add_followup"): WriteOperation.ITIL_ADD_FOLLOWUP,
        ("itil", "link_ticket"): WriteOperation.ITIL_LINK_TICKET,
        ("itil:problems", "delete"): WriteOperation.PROBLEM_DELETE,
        ("itil:changes", "delete"): WriteOperation.CHANGE_DELETE,
        ("itil:projects", "delete"): WriteOperation.PROJECT_DELETE,
        ("itil:contracts", "delete"): WriteOperation.CONTRACT_DELETE,
        ("itil:suppliers", "delete"): WriteOperation.SUPPLIER_DELETE,
    }
)


def resolve_operation(
    domain: str, action: str, resource: Optional[str] = None
) -> Optional[WriteOperation]:
    """Map a tool call to a write operation.

    Args:
        domain: "tickets", "assets", "admin", "webhooks" or "ai_analysis".
        action: The tool's action argument, e.g. "create".
        resource: Required for domain="admin" ("users", "groups", "locations").

    Returns:
        The operation, or None for read-only actions ("get", "get_stats", ...)
        and for combinations the MCP does not support. None means "no write
        gate applies", so callers must not treat it as a denial.
    """
    key_domain = domain.strip().lower()
    if resource:
        key_domain = f"{key_domain}:{resource.strip().lower()}"
    return _TOOL_ACTION_MAP.get((key_domain, action.strip().lower()))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WriteNotAllowedError(GLPIError):
    """Raised when policy forbids the requested write.

    Uses HTTP 403 so the existing HTTP_TO_JSONRPC mapping turns it into the
    standard unauthorized JSON-RPC code.
    """

    def __init__(self, message: str, operation: WriteOperation, reason: str) -> None:
        super().__init__(
            403,
            message,
            {
                "operation": operation.value,
                "reason": reason,
                "env_var": operation_env_var(operation),
            },
        )
        self.operation = operation
        self.reason = reason


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

_READ_OPERATIONS: frozenset[WriteOperation] = frozenset()

_TICKET_OPERATOR_OPERATIONS: frozenset[WriteOperation] = frozenset(
    {
        WriteOperation.TICKET_CREATE,
        WriteOperation.TICKET_UPDATE,
        WriteOperation.TICKET_ASSIGN,
        WriteOperation.TICKET_CLOSE,
        WriteOperation.TICKET_RESOLVE,
        WriteOperation.TICKET_ADD_FOLLOWUP,
        WriteOperation.AI_ANALYSIS_TRIGGER,
        WriteOperation.AI_ANALYSIS_PUBLISH,
        WriteOperation.ASSET_RESERVATION_CREATE,
        WriteOperation.ASSET_RESERVATION_UPDATE,
    }
)

_ADMINISTRATOR_OPERATIONS: frozenset[WriteOperation] = frozenset(WRITE_OPERATIONS)


@dataclass(frozen=True)
class WriteProfile:
    """A named, ready-made posture the operator can apply.

    Not a config file format: `as_environment()` renders the profile into the
    same environment variables the policy already reads, so applying one is
    just exporting its output in the PM2 unit.
    """

    name: str
    description: str  # pt-BR without accents
    read_only: bool
    allowed: frozenset[WriteOperation]

    def as_environment(self) -> dict[str, str]:
        """Render the profile as an explicit env-var mapping.

        Every operation appears, enabled or not, so the resulting environment
        never depends on the module's built-in defaults.
        """
        env = {ENV_READ_ONLY: "true" if self.read_only else "false"}
        for spec in _SPECS:
            allowed = (not self.read_only) and spec.operation in self.allowed
            env[spec.env_var] = "true" if allowed else "false"
        return env


PROFILE_READ_ONLY = WriteProfile(
    name="read_only",
    description="Somente leitura: nenhuma escrita permitida",
    read_only=True,
    allowed=_READ_OPERATIONS,
)

PROFILE_TICKET_OPERATOR = WriteProfile(
    name="ticket_operator",
    description=(
        "Operador de chamados: abre, comenta, atribui, resolve e fecha "
        "chamados; sem exclusoes, sem cadastro de usuarios e sem webhooks"
    ),
    read_only=False,
    allowed=_TICKET_OPERATOR_OPERATIONS,
)

PROFILE_ADMINISTRATOR = WriteProfile(
    name="administrator",
    description="Administrador: todas as operacoes de escrita, incluindo exclusoes",
    read_only=False,
    allowed=_ADMINISTRATOR_OPERATIONS,
)

#: Lookup table for the three shipped profiles.
WRITE_PROFILES: Mapping[str, WriteProfile] = MappingProxyType(
    {
        PROFILE_READ_ONLY.name: PROFILE_READ_ONLY,
        PROFILE_TICKET_OPERATOR.name: PROFILE_TICKET_OPERATOR,
        PROFILE_ADMINISTRATOR.name: PROFILE_ADMINISTRATOR,
    }
)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

REASON_READ_ONLY = "read_only_mode"
REASON_DISABLED = "operation_disabled"


class WritePolicy:
    """Decides whether an instance may perform a given write operation.

    The environment is read once, at construction, and cached: policy is
    deployment configuration, so a change means a restart (or an explicit
    `reload()`), never a surprise mid-request flip.
    """

    def __init__(self, env: Optional[Mapping[str, str]] = None) -> None:
        self._env: Mapping[str, str] = env if env is not None else os.environ
        self._read_only: bool = DEFAULT_READ_ONLY
        self._enabled: dict[WriteOperation, bool] = {}
        self.reload()

    # -- loading --------------------------------------------------------------

    def reload(self) -> None:
        """Re-read the environment into the cached decision table."""
        self._read_only = _env_bool(self._env, ENV_READ_ONLY, DEFAULT_READ_ONLY)
        self._enabled = {
            spec.operation: _env_bool(self._env, spec.env_var, spec.default_enabled)
            for spec in _SPECS
        }
        if self._read_only:
            logger.info("Write policy: READ-ONLY mode (%s=true)", ENV_READ_ONLY)
        else:
            blocked = sorted(
                op.value for op, on in self._enabled.items() if not on
            )
            logger.info(
                "Write policy loaded: %d/%d operations enabled; blocked=%s",
                len(self._enabled) - len(blocked),
                len(self._enabled),
                blocked or "none",
            )

    # -- queries --------------------------------------------------------------

    @property
    def is_read_only(self) -> bool:
        """True when the global read-only switch blocks every write."""
        return self._read_only

    def describe(self, operation: WriteOperation) -> WriteOperationSpec:
        """Return the registry entry for `operation`."""
        return WRITE_OPERATIONS[operation]

    def is_enabled(self, operation: WriteOperation) -> bool:
        """True when `operation` may run under the current configuration."""
        if self._read_only:
            return False
        return self._enabled.get(operation, WRITE_OPERATIONS[operation].default_enabled)

    def check(self, operation: WriteOperation) -> None:
        """Authorize `operation` or raise.

        Raises:
            WriteNotAllowedError: with a pt-BR message naming the exact
                environment variable that would enable the call.
        """
        spec = WRITE_OPERATIONS[operation]
        if self._read_only:
            raise WriteNotAllowedError(
                (
                    f"Instancia em modo somente leitura: a operacao "
                    f"'{operation.value}' ({spec.description}) foi bloqueada. "
                    f"Para permitir escritas, defina {ENV_READ_ONLY}=false e "
                    f"{spec.env_var}=true."
                ),
                operation,
                REASON_READ_ONLY,
            )
        if not self.is_enabled(operation):
            raise WriteNotAllowedError(
                (
                    f"Operacao de escrita '{operation.value}' ({spec.description}) "
                    f"esta desabilitada nesta instancia. Para habilitar, defina "
                    f"a variavel de ambiente {spec.env_var}=true e reinicie o "
                    f"servidor."
                ),
                operation,
                REASON_DISABLED,
            )
        logger.debug("Write policy allowed %s", operation.value)

    def check_tool_action(
        self, domain: str, action: str, resource: Optional[str] = None
    ) -> Optional[WriteOperation]:
        """Resolve a tool call and authorize it in one step.

        Returns the resolved operation, or None when the action is a read and
        no gate applies.
        """
        operation = resolve_operation(domain, action, resource)
        if operation is None:
            return None
        self.check(operation)
        return operation

    def apply_profile(self, profile: WriteProfile) -> None:
        """Load a profile in place, ignoring the environment.

        Useful for tests and for wiring a posture programmatically. Persisting
        it means exporting `profile.as_environment()`.
        """
        self._read_only = profile.read_only
        self._enabled = {
            spec.operation: (not profile.read_only)
            and spec.operation in profile.allowed
            for spec in _SPECS
        }
        logger.info("Write policy profile applied: %s", profile.name)

    def status(self) -> dict[str, Any]:
        """Snapshot for health endpoints and troubleshooting."""
        return {
            "read_only": self._read_only,
            "read_only_env_var": ENV_READ_ONLY,
            "total_operations": len(_SPECS),
            "enabled_operations": sorted(
                op.value for op in self._enabled if self.is_enabled(op)
            ),
            "blocked_operations": sorted(
                op.value for op in self._enabled if not self.is_enabled(op)
            ),
            "env_vars": {spec.operation.value: spec.env_var for spec in _SPECS},
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_policy: Optional[WritePolicy] = None


def get_write_policy() -> WritePolicy:
    """Return the process-wide policy, building it on first use."""
    global _policy
    if _policy is None:
        _policy = WritePolicy()
    return _policy


def set_write_policy(policy: Optional[WritePolicy]) -> None:
    """Replace the singleton. Intended for tests and explicit wiring."""
    global _policy
    _policy = policy


def reset_write_policy() -> None:
    """Drop the singleton so the next call rebuilds it from the environment."""
    set_write_policy(None)


def require_write_allowed(operation: WriteOperation) -> None:
    """Module-level shortcut mirroring `require_safety_confirmation`.

    Raises:
        WriteNotAllowedError: when the operation is blocked.
    """
    get_write_policy().check(operation)
