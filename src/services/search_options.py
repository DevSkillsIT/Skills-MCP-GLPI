"""
SearchOptionsCache — resolves GLPI Search API field names to numeric field ids.

@MX:ANCHOR: Single source of truth for Search API field ids. Every service that
builds `criteria[N][field]` must resolve through this module instead of
hardcoding numbers.

@MX:REASON: Field ids are not stable. They shift across GLPI versions, differ
per profile and change when plugins add search options. This project targets
more than one GLPI instance with the same codebase, so a number that is correct
on one instance can silently point at another column on the next. Hardcoded ids
already produced a defect where field 82 was treated as an SLA column.

Strategy:
  1. Cache /apirest.php/listSearchOptions/{itemtype} per itemtype, TTL 1h.
  2. Resolve a reference in cascade, from most to least precise:
       a. already numeric            -> passthrough
       b. explicit uid               -> "Ticket.status"
       c. canonical own-table uid    -> "{itemtype}.{ref}"      (locale independent)
       d. translated display label   -> "Status" / "Statut"     (locale dependent)
       e. raw SQL column name        -> "status"                (locale independent)
  3. Own-table tie-break: the same column name reaches the catalogue through
     joined tables (`name` exists on glpi_tickets AND glpi_users). The option
     whose uid is exactly "{itemtype}.{field}" always wins, otherwise filtering
     a ticket by `name` would match the requester's name, not the ticket title.
  4. Graceful degradation: on lookup failure fall back to the legacy id table,
     which only contains ids already proven in production. References with no
     legacy entry raise instead of guessing a number.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from src.models.exceptions import ValidationError
from src.services.glpi_client import glpi_client
from src.utils.helpers import logger


class SearchOption:
    """A single entry of the GLPI search options catalogue."""

    __slots__ = ("id", "name", "table", "field", "datatype", "uid", "searchtypes")

    def __init__(self, option_id: int, raw: Dict[str, Any]) -> None:
        self.id = option_id
        self.name = str(raw.get("name") or option_id)
        self.table = raw.get("table") or None
        self.field = raw.get("field") or None
        self.datatype = raw.get("datatype") or None
        self.uid = raw.get("uid") or None
        searchtypes = raw.get("available_searchtypes")
        self.searchtypes = tuple(searchtypes) if isinstance(searchtypes, list) else ()

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<SearchOption {self.id} {self.uid or self.name}>"


class _Catalogue:
    """Indexed view of one itemtype's search options."""

    __slots__ = ("itemtype", "fetched_at", "by_id", "by_uid", "by_label", "by_column")

    def __init__(self, itemtype: str) -> None:
        self.itemtype = itemtype
        self.fetched_at = time.monotonic()
        self.by_id: Dict[int, SearchOption] = {}
        self.by_uid: Dict[str, SearchOption] = {}
        self.by_label: Dict[str, SearchOption] = {}
        self.by_column: Dict[str, SearchOption] = {}

    def add(self, option: SearchOption) -> None:
        self.by_id[option.id] = option

        if option.uid and option.uid not in self.by_uid:
            self.by_uid[option.uid] = option

        label = option.name.lower()
        if label and label not in self.by_label:
            self.by_label[label] = option

        # Own-table tie-break: an option reached through a joined table must not
        # shadow the itemtype's own column of the same name.
        if option.field:
            column = str(option.field).lower()
            is_canonical = option.uid == f"{self.itemtype}.{option.field}"
            if is_canonical or column not in self.by_column:
                self.by_column[column] = option


class SearchOptionsCache:
    """Per-itemtype cache of the GLPI search options catalogue."""

    _TTL_SECONDS = 3600  # 1h

    # Field ids currently hardcoded across the services, kept only as a safety
    # net for when listSearchOptions is unreachable. Every entry here is already
    # running in production. New references are deliberately absent: resolving
    # them dynamically or failing loudly beats guessing a number.
    _LEGACY_IDS: Dict[str, Dict[str, int]] = {
        "Ticket": {
            "name": 1,
            "id": 2,
            "entity": 80,
        },
        "Computer": {
            "name": 1,
            "id": 2,
            "location": 3,
            "manufacturer": 23,
            "status": 31,
            "model": 40,
            "is_template": 47,
            "user": 70,
            "entity": 80,
        },
        "User": {
            "name": 1,
            "id": 2,
            "email": 5,
            "contact": 7,
            "firstname": 9,
            "realname": 34,
            "user": 70,
            "entity": 80,
        },
        "KnowbaseItem": {
            "name": 1,
            "answer": 7,
        },
    }

    def __init__(self) -> None:
        self._cache: Dict[str, _Catalogue] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # cache plumbing
    # ------------------------------------------------------------------

    def _lock_for(self, itemtype: str) -> asyncio.Lock:
        lock = self._locks.get(itemtype)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[itemtype] = lock
        return lock

    def _is_fresh(self, itemtype: str) -> bool:
        catalogue = self._cache.get(itemtype)
        if catalogue is None:
            return False
        return (time.monotonic() - catalogue.fetched_at) < self._TTL_SECONDS

    def invalidate(self, itemtype: Optional[str] = None) -> None:
        """Drop one itemtype from the cache, or everything when omitted."""
        if itemtype is None:
            self._cache.clear()
        else:
            self._cache.pop(itemtype, None)

    async def get_catalogue(self, itemtype: str) -> Optional[_Catalogue]:
        """Return the cached catalogue, fetching it when stale or absent."""
        if self._is_fresh(itemtype):
            return self._cache[itemtype]

        async with self._lock_for(itemtype):
            # Another coroutine may have populated it while we waited.
            if self._is_fresh(itemtype):
                return self._cache[itemtype]

            try:
                raw = await glpi_client.get(
                    f"/apirest.php/listSearchOptions/{itemtype}",
                    use_cache=False,
                )
            except Exception as exc:  # noqa: BLE001 — a cache miss must not break the caller
                logger.warning(
                    f"SearchOptionsCache: listSearchOptions/{itemtype} failed: {exc}",
                    extra={"itemtype": itemtype},
                )
                return None

            catalogue = self._parse(itemtype, raw)
            if catalogue is None:
                return None

            self._cache[itemtype] = catalogue
            logger.debug(
                f"SearchOptionsCache: {len(catalogue.by_id)} options cached for {itemtype}"
            )
            return catalogue

    def _parse(self, itemtype: str, raw: Any) -> Optional[_Catalogue]:
        """Build the indexed catalogue from the raw GLPI payload."""
        if not isinstance(raw, dict):
            logger.warning(
                f"SearchOptionsCache: unexpected payload for {itemtype}: {type(raw).__name__}"
            )
            return None

        catalogue = _Catalogue(itemtype)
        for key, value in raw.items():
            # Non-numeric keys are section metadata ("common", group labels).
            if not str(key).isdigit() or not isinstance(value, dict):
                continue
            catalogue.add(SearchOption(int(key), value))

        if not catalogue.by_id:
            logger.warning(f"SearchOptionsCache: empty catalogue for {itemtype}")
            return None

        return catalogue

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------

    async def resolve(self, itemtype: str, ref: Any) -> Optional[int]:
        """Resolve a field reference to its numeric id, or None when unknown.

        Args:
            itemtype: GLPI itemtype ("Ticket", "Computer", "User", ...).
            ref: numeric id, uid ("Ticket.status"), display label or SQL column.
        """
        if isinstance(ref, bool):  # bool is an int subclass — never a field id
            return None
        if isinstance(ref, int):
            return ref

        if ref is None:
            return None

        text = str(ref).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)

        catalogue = await self.get_catalogue(itemtype)
        if catalogue is not None:
            lowered = text.lower()
            option = (
                catalogue.by_uid.get(text)
                or catalogue.by_uid.get(f"{itemtype}.{text}")
                or catalogue.by_label.get(lowered)
                or catalogue.by_column.get(lowered)
            )
            if option is not None:
                return option.id

        legacy = self._LEGACY_IDS.get(itemtype, {}).get(text.lower())
        if legacy is not None:
            logger.warning(
                f"SearchOptionsCache: '{text}' on {itemtype} resolved from the legacy "
                f"table (id {legacy}); dynamic lookup was unavailable"
            )
            return legacy

        return None

    async def resolve_or_raise(self, itemtype: str, ref: Any) -> int:
        """Same as resolve(), but raises with a user-facing message on failure."""
        resolved = await self.resolve(itemtype, ref)
        if resolved is None:
            raise ValidationError(
                f"Campo '{ref}' nao existe na busca de {itemtype} nesta instancia do GLPI. "
                f"Verifique o nome do campo ou informe o ID numerico.",
                "field",
            )
        return resolved

    async def reconcile(
        self,
        itemtype: str,
        field_map: Dict[str, int],
        uid_hints: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Reconcile a static field map against the live catalogue, in place.

        Static maps are convenient — callers read them synchronously and the
        hot path stays free of lookups — but they drift: a GLPI upgrade, a
        plugin or a different profile can renumber a search option, and the
        code keeps filtering on a field that now means something else.

        Two levels of confidence, deliberately separated:

        * Keys with a uid hint name a column on the itemtype's own table, so
          the catalogue can resolve them unambiguously. Those are corrected
          in place when they disagree.
        * Keys without a hint reach the catalogue through a join (requester,
          assigned group, SLA flag). There is no locale-independent way to
          re-derive them, so they are only *checked* for existence. Replacing
          a working id with a guess would be worse than the drift itself.

        Returns a report of what changed and what looks suspicious, so callers
        can log it once instead of silently mutating behaviour.
        """
        catalogue = await self.get_catalogue(itemtype)
        if catalogue is None:
            return {"corrected": {}, "missing": [], "checked": False}

        hints = uid_hints or {}
        corrected: Dict[str, Any] = {}
        missing = []

        for key, current_id in list(field_map.items()):
            hint = hints.get(key)
            if hint:
                option = catalogue.by_uid.get(hint)
                if option is not None:
                    if option.id != current_id:
                        field_map[key] = option.id
                        corrected[key] = (current_id, option.id)
                    continue
            if current_id not in catalogue.by_id:
                missing.append(key)

        if corrected:
            logger.warning(
                f"SearchOptionsCache: {itemtype} field ids drifted and were "
                f"corrected from the live catalogue: {corrected}"
            )
        if missing:
            logger.warning(
                f"SearchOptionsCache: {itemtype} fields not present in this "
                f"instance's catalogue (kept as-is): {missing}"
            )

        return {"corrected": corrected, "missing": missing, "checked": True}

    async def datatype_of(self, itemtype: str, field_id: int) -> Optional[str]:
        """Return the GLPI datatype declared for a field, when the catalogue loads.

        @MX:NOTE: usado para recusar operadores de ordem fora de colunas de data.
        @MX:REASON: `morethan`/`lessthan` so se comportam como comparacao de
        verdade em coluna de data nesta versao do GLPI. Sem o datatype nao ha
        como distinguir, e a alternativa e confiar num aviso de texto que o
        chamador pode ignorar.
        """
        catalogue = await self.get_catalogue(itemtype)
        if not catalogue:
            return None
        option = catalogue.by_id.get(int(field_id))
        return option.datatype if option else None

    async def available_fields(self, itemtype: str, limit: int = 60) -> Dict[str, int]:
        """Map label -> field id, for discovery and error messages.

        @MX:WARN: labels are NOT unique in a GLPI catalogue.
        @MX:REASON: a live instance returns several options named "Status" —
        the ticket's own status plus approval and solution statuses reached
        through joins. Building the map naively let the last one win, so
        discovery advertised an id that resolution would never pick: someone
        reading this list and passing that id back would filter a different
        column and get a plausible, wrong answer.

        Resolution order matches `resolve`: the itemtype's own column wins the
        bare label, and the remaining homonyms are disambiguated by suffixing
        the table they come from, so every entry here is usable as-is.
        """
        catalogue = await self.get_catalogue(itemtype)
        if catalogue is None:
            return {}

        fields: Dict[str, int] = {}
        for option in list(catalogue.by_id.values())[:limit]:
            label = option.name
            # Own column means the CANONICAL uid, not merely a uid starting
            # with the itemtype: every option on Ticket starts with "Ticket.",
            # including the ones reached through joins.
            is_own = bool(option.field) and option.uid == f"{itemtype}.{option.field}"

            if label not in fields:
                fields[label] = option.id
                continue

            # Collision: the itemtype's own column takes the bare label and the
            # previous holder is pushed to a qualified one.
            if is_own:
                displaced_id = fields[label]
                displaced = catalogue.by_id.get(displaced_id)
                fields[self._qualified_label(label, displaced)] = displaced_id
                fields[label] = option.id
            else:
                fields[self._qualified_label(label, option)] = option.id

        return fields

    @staticmethod
    def _qualified_label(label: str, option: Optional[SearchOption]) -> str:
        """Disambiguate a repeated label using where the column comes from."""
        if option is None:
            return label
        origin = option.table or option.uid or ""
        origin = origin.replace("glpi_", "").strip(".")
        if origin and origin.lower() != label.lower():
            return f"{label} ({origin})"
        return f"{label} #{option.id}"


# Module-level singleton, mirroring dropdown_cache.
search_options_cache = SearchOptionsCache()
