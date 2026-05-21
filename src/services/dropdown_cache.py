"""
DropdownCache — resolve IDs do GLPI para nomes humanos, com TTL.

@MX:ANCHOR: Cache unico de dropdowns. Usado por formatters para enriquecer
respostas onde GLPI retorna apenas IDs (location, manufacturer, OS, software,
filesystem, user, group, entity, state).

@MX:REASON: Bugs #3/#4/#5 — IDs crus em stats e details obrigavam o LLM a
fazer N calls extras ou interpretar dados incompletos.

Estrategia:
  1. Cache TTL 1h por (itemtype, item_id).
  2. Bulk listing por itemtype para popular o cache de uma vez.
  3. Fallback gracioso: se nao conseguir resolver, retorna `str(id)`.
  4. Operacao async, nao bloqueia o handler em cache miss.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Iterable, Optional

from src.services.glpi_client import glpi_client
from src.utils.helpers import logger


class DropdownCache:
    """Cache global de dropdowns GLPI com TTL e bulk-loading."""

    _TTL_SECONDS = 3600  # 1h
    _BULK_LIMIT = 500

    # itemtypes que sao seguros para bulk-list (todos sao read-only e relativamente pequenos)
    _BULK_TYPES = frozenset(
        {
            "Entity",
            "Location",
            "Manufacturer",
            "OperatingSystem",
            "OperatingSystemVersion",
            "Filesystem",
            "State",
            "Group",
            "ItemDeviceProcessor",
            "ITILCategory",
        }
    )

    def __init__(self) -> None:
        # _cache[itemtype][item_id] = name
        self._cache: Dict[str, Dict[int, str]] = {}
        # _filled_at[itemtype] = monotonic timestamp do bulk-load mais recente
        self._filled_at: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _lock_for(self, itemtype: str) -> asyncio.Lock:
        lock = self._locks.get(itemtype)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[itemtype] = lock
        return lock

    def _is_fresh(self, itemtype: str) -> bool:
        filled = self._filled_at.get(itemtype)
        if filled is None:
            return False
        return (time.monotonic() - filled) < self._TTL_SECONDS

    async def _bulk_load(self, itemtype: str) -> None:
        """Lista todos os registros do itemtype e popula o cache."""
        async with self._lock_for(itemtype):
            if self._is_fresh(itemtype):
                return  # other coroutine ja populou

            try:
                items = await glpi_client.get(
                    f"/apirest.php/{itemtype}",
                    params={"range": f"0-{self._BULK_LIMIT - 1}"},
                    use_cache=False,
                )
            except Exception as exc:  # noqa: BLE001 — falha de cache nao deve quebrar handler
                logger.warning(
                    f"DropdownCache: bulk-load {itemtype} falhou: {exc}",
                    extra={"itemtype": itemtype},
                )
                # Marca como filled mesmo em falha para evitar retry agressivo
                self._filled_at[itemtype] = time.monotonic() - (self._TTL_SECONDS - 60)
                return

            type_cache: Dict[int, str] = self._cache.setdefault(itemtype, {})

            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_id = item.get("id")
                    if item_id is None:
                        continue
                    name = (
                        item.get("name")
                        or item.get("completename")
                        or item.get("comment")
                        or item.get("title")
                    )
                    if name:
                        type_cache[int(item_id)] = str(name)

            self._filled_at[itemtype] = time.monotonic()
            logger.debug(
                f"DropdownCache: carregados {len(type_cache)} registros de {itemtype}"
            )

    async def _ensure_loaded(self, itemtype: str) -> None:
        if itemtype not in self._BULK_TYPES:
            return  # Tipos nao-bulk so resolvem on-demand via _resolve_single
        if not self._is_fresh(itemtype):
            await self._bulk_load(itemtype)

    async def _resolve_single(self, itemtype: str, item_id: int) -> Optional[str]:
        """Resolve um unico ID sem listar tudo (uso pontual: User, Software)."""
        type_cache = self._cache.setdefault(itemtype, {})
        if item_id in type_cache:
            return type_cache[item_id]

        try:
            item = await glpi_client.get(
                f"/apirest.php/{itemtype}/{item_id}", use_cache=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"DropdownCache: lookup {itemtype}/{item_id} falhou: {exc}"
            )
            return None

        if not isinstance(item, dict):
            return None

        name = (
            item.get("name")
            or item.get("completename")
            or item.get("realname")
            or item.get("firstname")
        )
        if name:
            type_cache[item_id] = str(name)
            return str(name)
        return None

    async def get_name(
        self, itemtype: str, item_id: Any, fallback: Optional[str] = None
    ) -> str:
        """Resolve um ID para nome humano. Retorna fallback ou str(id) se nao achar."""
        if item_id is None or item_id == "":
            return fallback if fallback is not None else ""
        try:
            item_id_int = int(item_id)
        except (TypeError, ValueError):
            return str(item_id)

        await self._ensure_loaded(itemtype)
        type_cache = self._cache.get(itemtype, {})

        if item_id_int in type_cache:
            return type_cache[item_id_int]

        if itemtype not in self._BULK_TYPES:
            # On-demand lookup para tipos nao-bulk (User, Software, SoftwareVersion)
            name = await self._resolve_single(itemtype, item_id_int)
            if name:
                return name

        return fallback if fallback is not None else str(item_id_int)

    async def get_many_names(
        self, itemtype: str, item_ids: Iterable[Any]
    ) -> Dict[int, str]:
        """Resolve varios IDs de uma vez. Retorna mapping {id: name}.

        Para tipos bulk, dispara um unico bulk-load se necessario.
        Para tipos nao-bulk, faz lookups paralelos (limitado por semaphore).
        """
        await self._ensure_loaded(itemtype)
        type_cache = self._cache.get(itemtype, {})

        normalized: Dict[int, None] = {}
        for raw in item_ids:
            if raw is None:
                continue
            try:
                normalized[int(raw)] = None
            except (TypeError, ValueError):
                continue

        if not normalized:
            return {}

        result: Dict[int, str] = {}
        missing: list[int] = []

        for item_id in normalized:
            if item_id in type_cache:
                result[item_id] = type_cache[item_id]
            else:
                missing.append(item_id)

        if missing and itemtype not in self._BULK_TYPES:
            semaphore = asyncio.Semaphore(5)

            async def _one(iid: int) -> tuple[int, Optional[str]]:
                async with semaphore:
                    return iid, await self._resolve_single(itemtype, iid)

            for coro in asyncio.as_completed([_one(iid) for iid in missing]):
                iid, name = await coro
                if name:
                    result[iid] = name

        return result

    def invalidate(self, itemtype: Optional[str] = None) -> None:
        """Limpa cache (debug/manual)."""
        if itemtype is None:
            self._cache.clear()
            self._filled_at.clear()
        else:
            self._cache.pop(itemtype, None)
            self._filled_at.pop(itemtype, None)


# Instancia global
dropdown_cache = DropdownCache()
