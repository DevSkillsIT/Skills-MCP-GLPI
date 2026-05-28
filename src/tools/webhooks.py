"""
MCP Tools - Webhooks (GLPI 11 Webhook integration)

@MX:ANCHOR: WebhookTools agora chama /apirest.php/Webhook do GLPI 11.
@MX:REASON: Bug #5 — storage in-memory criava webhooks fantasma que sumiam no
restart e nao geravam notificacoes reais. Substituido por backend GLPI nativo.

Mantem a assinatura publica original (webhook_tools.list_webhooks etc.) para
nao quebrar consolidated_webhooks.py.

Fields GLPI 11 Webhook (confirmados via src/Webhook.php upstream):
  id (int), name, is_active (int 0/1), itemtype (str: Ticket/Computer/User/...),
  event (str: new/update/delete), url, secret, clientsecret, http_method,
  custom_headers (json/array), payload, use_default_payload (bool),
  use_cra_challenge (bool), save_response_body (bool), entities_id,
  is_recursive (bool), webhookcategories_id, comment.

O schema MCP usa o vocabulario 'itemtype.event' (ex: 'ticket.created') para
manter compat com clients existentes; convertemos para os 2 fields nativos
no momento de create/update.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from src.models.exceptions import (
    GLPIError,
    NotFoundError,
    ValidationError,
)
from src.services.glpi_client import glpi_client
from src.utils.helpers import (
    input_sanitizer,
    logger,
    response_truncator,
)
from src.utils.safety_guard import require_safety_confirmation

# Mapeia o vocabulario do MCP (itemtype.acao) -> (itemtype, event) do GLPI 11.
# GLPI 11 NAO usa string 'Ticket.add' — usa 2 campos separados:
#   - itemtype: 'Ticket' | 'Computer' | 'User' | 'Group' | 'Reservation' | ...
#   - event:    'new' | 'update' | 'delete' (vide src/Webhook.php upstream)
_EVENT_MAP_MCP_TO_GLPI: Dict[str, tuple[str, str]] = {
    "ticket.created":  ("Ticket", "new"),
    "ticket.updated":  ("Ticket", "update"),
    "ticket.deleted":  ("Ticket", "delete"),
    "ticket.assigned": ("Ticket", "update"),
    "asset.created":   ("Computer", "new"),
    "asset.updated":   ("Computer", "update"),
    "asset.deleted":   ("Computer", "delete"),
    "asset.reserved":  ("Reservation", "new"),
    "user.created":    ("User", "new"),
    "user.updated":    ("User", "update"),
    "user.deleted":    ("User", "delete"),
    "group.created":   ("Group", "new"),
    "group.updated":   ("Group", "update"),
    "group.deleted":   ("Group", "delete"),
}

# @MX:NOTE: ticket.updated e ticket.assigned mapeiam para o mesmo (Ticket,update).
# No reverse, preferimos o mais geral ("updated") em vez do specifico ("assigned").
_EVENT_MAP_GLPI_TO_MCP: Dict[tuple[str, str], str] = {
    ("Ticket", "new"):     "ticket.created",
    ("Ticket", "update"):  "ticket.updated",
    ("Ticket", "delete"):  "ticket.deleted",
    ("Computer", "new"):    "asset.created",
    ("Computer", "update"): "asset.updated",
    ("Computer", "delete"): "asset.deleted",
    ("Reservation", "new"): "asset.reserved",
    ("User", "new"):    "user.created",
    ("User", "update"): "user.updated",
    ("User", "delete"): "user.deleted",
    ("Group", "new"):    "group.created",
    ("Group", "update"): "group.updated",
    ("Group", "delete"): "group.deleted",
}


def _to_glpi_event(mcp_event: str) -> tuple[str, str]:
    """Converte 'ticket.created' -> ('Ticket', 'new'). Raises se nao mapeado."""
    mapped = _EVENT_MAP_MCP_TO_GLPI.get(mcp_event)
    if mapped is None:
        raise ValidationError(
            f"event_type='{mcp_event}' invalido. Aceitos: "
            f"{list(_EVENT_MAP_MCP_TO_GLPI.keys())}",
            "event_type",
        )
    return mapped


def _to_mcp_event(itemtype: Optional[str], event: Optional[str]) -> str:
    """Converte (itemtype, event) -> 'ticket.created'. Fallback para 'Itemtype.event'."""
    if not itemtype or not event:
        return ""
    mapped = _EVENT_MAP_GLPI_TO_MCP.get((itemtype, event))
    if mapped is not None:
        return mapped
    return f"{itemtype.lower()}.{event}"


def _normalize_webhook_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Converte registro cru do GLPI 11 (Webhook itemtype) para shape estavel do MCP."""
    if not isinstance(raw, dict):
        return raw
    return {
        "id": raw.get("id"),
        "name": raw.get("name", ""),
        "url": raw.get("url", ""),
        "itemtype": raw.get("itemtype", ""),
        "event": raw.get("event", ""),
        "event_type": _to_mcp_event(raw.get("itemtype"), raw.get("event")),
        "http_method": raw.get("http_method", "POST"),
        "secret": "***" if raw.get("secret") else "",
        "is_active": bool(raw.get("is_active", 0)),
        "custom_headers": raw.get("custom_headers") or {},
        "payload": raw.get("payload", ""),
        "use_default_payload": bool(raw.get("use_default_payload", 1)),
        "use_cra_challenge": bool(raw.get("use_cra_challenge", 0)),
        "save_response_body": bool(raw.get("save_response_body", 0)),
        "entities_id": raw.get("entities_id"),
        "is_recursive": bool(raw.get("is_recursive", 0)),
        "webhookcategories_id": raw.get("webhookcategories_id"),
        "comment": raw.get("comment", ""),
        "created_at": raw.get("date_creation"),
        "updated_at": raw.get("date_mod"),
    }


def _validate_event_type(mcp_event: str) -> None:
    """Valida que o event_type esta no enum aceito (delegado para _to_glpi_event)."""
    _to_glpi_event(mcp_event)


def _validate_url(url: str) -> None:
    if not url or not url.startswith(("http://", "https://")):
        raise ValidationError("URL deve comecar com http:// ou https://", "url")


class WebhookTools:
    """Webhooks GLPI 11 via /apirest.php/Webhook."""

    _ENDPOINT = "/apirest.php/Webhook"

    def __init__(self) -> None:
        logger.info("WebhookTools initialized (GLPI 11 native backend)")

    # -----------------------------------------------------------------
    # LIST
    # -----------------------------------------------------------------
    async def list_webhooks(
        self,
        event_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        logger.info(f"WebhookTools.list_webhooks limit={limit} offset={offset}")
        try:
            params = {"range": f"{offset}-{offset + limit - 1}"}
            data = await glpi_client.get(self._ENDPOINT, params=params, use_cache=False)
        except GLPIError as exc:
            if exc.code == 404:
                # Endpoint indisponivel nesta instancia GLPI
                return {
                    "webhooks": [],
                    "pagination": {"total": 0, "offset": offset, "limit": limit, "has_more": False},
                    "warning": "Endpoint /apirest.php/Webhook indisponivel nesta instancia GLPI 11.",
                }
            raise
        except Exception as exc:
            logger.error(f"list_webhooks GLPI error: {exc}", exc_info=True)
            raise GLPIError(500, f"Falha ao listar webhooks: {exc}") from None

        items = data if isinstance(data, list) else []
        webhooks = [_normalize_webhook_record(w) for w in items]

        # Filtros client-side
        if event_type:
            webhooks = [w for w in webhooks if w.get("event_type") == event_type]
        if is_active is not None:
            webhooks = [w for w in webhooks if w.get("is_active") == is_active]

        total = len(webhooks)
        result = {
            "webhooks": webhooks,
            "pagination": {
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < total,
            },
        }
        return response_truncator.truncate_json_response(result)

    # -----------------------------------------------------------------
    # GET
    # -----------------------------------------------------------------
    async def get_webhook(self, webhook_id: str) -> Dict[str, Any]:
        logger.info(f"WebhookTools.get_webhook {webhook_id}")
        if not webhook_id or not str(webhook_id).strip():
            raise ValidationError("webhook_id obrigatorio", "webhook_id")

        wid = str(webhook_id).strip()
        try:
            raw = await glpi_client.get(f"{self._ENDPOINT}/{wid}", use_cache=False)
        except GLPIError as exc:
            if exc.code == 404:
                raise NotFoundError("Webhook", wid) from None
            raise
        except Exception as exc:
            logger.error(f"get_webhook error: {exc}", exc_info=True)
            raise GLPIError(500, f"Falha ao obter webhook: {exc}") from None

        if not isinstance(raw, dict):
            raise NotFoundError("Webhook", wid)
        return _normalize_webhook_record(raw)

    # -----------------------------------------------------------------
    # CREATE
    # -----------------------------------------------------------------
    async def create_webhook(
        self,
        name: str,
        url: str,
        event_type: str,
        secret: Optional[str] = None,
        is_active: bool = True,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        logger.info(f"WebhookTools.create_webhook name='{name}' event={event_type}")

        name = input_sanitizer.sanitize_string(name)
        url = input_sanitizer.sanitize_string(url)
        event_type = input_sanitizer.sanitize_string(event_type)
        if not name:
            raise ValidationError("name obrigatorio", "name")
        _validate_url(url)

        glpi_itemtype, glpi_event = _to_glpi_event(event_type)

        # @MX:NOTE: glpi_client.post() ja envelopa em {"input": ...}.
        # Passamos os fields direto — caso contrario vira {"input": {"input": ...}}.
        fields: Dict[str, Any] = {
            "name": name,
            "url": url,
            "itemtype": glpi_itemtype,
            "event": glpi_event,
            "http_method": "POST",
            "is_active": 1 if is_active else 0,
            "use_default_payload": 1,
        }
        if secret:
            fields["secret"] = secret
        if headers:
            fields["custom_headers"] = headers

        try:
            response = await glpi_client.post(self._ENDPOINT, fields)
        except Exception as exc:
            logger.error(f"create_webhook error: {exc}", exc_info=True)
            raise GLPIError(500, f"Falha ao criar webhook: {exc}") from None
        logger.info(f"DEBUG GLPI Webhook POST response: {response}")

        new_id = None
        if isinstance(response, dict):
            new_id = response.get("id")
        elif isinstance(response, list) and response:
            first = response[0]
            if isinstance(first, dict):
                new_id = first.get("id")

        if new_id is None:
            raise GLPIError(500, f"Webhook criado mas resposta sem id: {response}")

        return await self.get_webhook(str(new_id))

    # -----------------------------------------------------------------
    # UPDATE
    # -----------------------------------------------------------------
    async def update_webhook(
        self,
        webhook_id: str,
        name: Optional[str] = None,
        url: Optional[str] = None,
        event_type: Optional[str] = None,
        secret: Optional[str] = None,
        is_active: Optional[bool] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        logger.info(f"WebhookTools.update_webhook {webhook_id}")
        if not webhook_id:
            raise ValidationError("webhook_id obrigatorio", "webhook_id")

        wid = str(webhook_id).strip()
        # Confirma existencia primeiro (retorna NotFoundError limpo)
        await self.get_webhook(wid)

        updates: Dict[str, Any] = {"id": wid}
        if name is not None:
            updates["name"] = input_sanitizer.sanitize_string(name)
        if url is not None:
            url = input_sanitizer.sanitize_string(url)
            _validate_url(url)
            updates["url"] = url
        if event_type is not None:
            glpi_itemtype, glpi_event = _to_glpi_event(event_type)
            updates["itemtype"] = glpi_itemtype
            updates["event"] = glpi_event
        if secret is not None:
            updates["secret"] = secret
        if is_active is not None:
            updates["is_active"] = 1 if is_active else 0
        if headers is not None:
            updates["custom_headers"] = headers

        try:
            # @MX:NOTE: glpi_client.put() ja envelopa em {"input": ...}, passa fields direto
            await glpi_client.put(f"{self._ENDPOINT}/{wid}", updates)
        except Exception as exc:
            logger.error(f"update_webhook error: {exc}", exc_info=True)
            raise GLPIError(500, f"Falha ao atualizar webhook: {exc}") from None

        return await self.get_webhook(wid)

    # -----------------------------------------------------------------
    # DELETE
    # -----------------------------------------------------------------
    async def delete_webhook(
        self,
        webhook_id: str,
        confirmationToken: Optional[str] = None,  # noqa: N803 — kept for backward compat
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info(f"WebhookTools.delete_webhook {webhook_id}")
        if not webhook_id:
            raise ValidationError("webhook_id obrigatorio", "webhook_id")

        wid = str(webhook_id).strip()
        require_safety_confirmation(
            "delete_webhook",
            confirmation_token=confirmationToken,
            reason=reason,
            target_id=int(wid) if wid.isdigit() else 0,
            target_type="Webhook",
        )

        # Confirma existencia
        await self.get_webhook(wid)

        try:
            await glpi_client.delete(f"{self._ENDPOINT}/{wid}")
        except Exception as exc:
            logger.error(f"delete_webhook error: {exc}", exc_info=True)
            raise GLPIError(500, f"Falha ao excluir webhook: {exc}") from None

        return {"success": True, "webhook_id": wid, "message": f"Webhook {wid} excluido"}

    # -----------------------------------------------------------------
    # TEST (HTTP local, nao tem endpoint GLPI nativo)
    # -----------------------------------------------------------------
    async def test_webhook(self, webhook_id: str) -> Dict[str, Any]:
        logger.info(f"WebhookTools.test_webhook {webhook_id}")
        webhook = await self.get_webhook(webhook_id)
        target_url = webhook.get("url", "")
        if not target_url:
            raise ValidationError("Webhook nao tem URL configurada", "url")

        payload = {
            "event": "test",
            "webhook_id": webhook.get("id"),
            "webhook_name": webhook.get("name"),
            "timestamp": datetime.now().isoformat(),
            "source": "mcp-glpi.test_webhook",
            "data": {"message": "Test payload from GLPI MCP"},
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                http_resp = await client.post(
                    target_url, json=payload, headers=webhook.get("custom_headers") or {}
                )
            return {
                "webhook_id": webhook.get("id"),
                "url": target_url,
                "test_result": "success" if http_resp.is_success else "failed",
                "response_code": http_resp.status_code,
                "response_body": http_resp.text[:500],
                "timestamp": datetime.now().isoformat(),
            }
        except httpx.HTTPError as exc:
            return {
                "webhook_id": webhook.get("id"),
                "url": target_url,
                "test_result": "failed",
                "response_code": None,
                "error": str(exc),
                "timestamp": datetime.now().isoformat(),
            }

    # -----------------------------------------------------------------
    # DELIVERIES (GLPI 11 Notification log via /apirest.php/QueuedNotification)
    # -----------------------------------------------------------------
    async def get_webhook_deliveries(
        self,
        webhook_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        logger.info(f"WebhookTools.get_webhook_deliveries {webhook_id}")
        # Confirma existencia
        await self.get_webhook(webhook_id)

        # GLPI 11 nao expoe historico de entrega de webhook diretamente via REST.
        # @MX:TODO: Quando GLPI expor /apirest.php/Webhook/{id}/Notification, popular esta lista.
        return {
            "webhook_id": webhook_id,
            "deliveries": [],
            "pagination": {"total": 0, "offset": offset, "limit": limit, "has_more": False},
            "warning": (
                "GLPI 11 nao expoe historico de entrega via REST API. "
                "Consulte logs do servidor GLPI (glpi_logs/php-errors.log) para auditoria."
            ),
        }

    # -----------------------------------------------------------------
    # TRIGGER (GLPI 11 nao tem endpoint manual; sinalizamos isso ao LLM)
    # -----------------------------------------------------------------
    async def trigger_webhook(
        self,
        event_type: str,
        data: Dict[str, Any],
        webhook_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        logger.warning("WebhookTools.trigger_webhook called — no native GLPI endpoint")
        return {
            "event_type": event_type,
            "supported": False,
            "triggered_count": 0,
            "results": [],
            "message": (
                "GLPI 11 nao expoe endpoint para disparo manual de webhook via REST. "
                "Os webhooks sao disparados automaticamente pelos eventos nativos do GLPI. "
                "Use test_webhook para validar conectividade do endpoint destino."
            ),
        }

    # -----------------------------------------------------------------
    # STATS
    # -----------------------------------------------------------------
    async def get_webhook_stats(self) -> Dict[str, Any]:
        result = await self.list_webhooks(limit=500, offset=0)
        webhooks: List[Dict[str, Any]] = result.get("webhooks", []) if isinstance(result, dict) else []

        total = len(webhooks)
        active = sum(1 for w in webhooks if w.get("is_active"))
        by_event: Dict[str, int] = {}
        for w in webhooks:
            ev = w.get("event_type") or "unknown"
            by_event[ev] = by_event.get(ev, 0) + 1

        return {
            "total_webhooks": total,
            "active_webhooks": active,
            "inactive_webhooks": total - active,
            "total_deliveries": 0,
            "by_event_type": by_event,
            "last_updated": datetime.now().isoformat(),
            "note": "total_deliveries indisponivel via REST API GLPI 11.",
        }

    # -----------------------------------------------------------------
    # ENABLE / DISABLE
    # -----------------------------------------------------------------
    async def enable_webhook(self, webhook_id: str) -> Dict[str, Any]:
        return await self.update_webhook(webhook_id, is_active=True)

    async def disable_webhook(self, webhook_id: str) -> Dict[str, Any]:
        return await self.update_webhook(webhook_id, is_active=False)

    # -----------------------------------------------------------------
    # RETRY (GLPI 11 nao expoe; reportamos honestamente)
    # -----------------------------------------------------------------
    async def retry_failed_deliveries(self, webhook_id: str) -> Dict[str, Any]:
        await self.get_webhook(webhook_id)  # confirma existencia / NotFoundError limpo
        return {
            "webhook_id": webhook_id,
            "supported": False,
            "retried_count": 0,
            "success_count": 0,
            "message": "GLPI 11 nao expoe retry de webhook via REST API.",
            "timestamp": datetime.now().isoformat(),
        }


# Instancia global usada por consolidated_webhooks.py
webhook_tools = WebhookTools()
