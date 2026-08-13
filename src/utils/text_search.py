"""
Free-text search over GLPI columns.

@MX:ANCHOR: the only place that turns a human phrase into search criteria.
@MX:REASON: GLPI's ``contains`` is a SQL ``LIKE %value%`` — a literal substring
test. Passing a whole phrase to it means "Telefonica Vivo" never matches the
supplier stored as "Telefonica Brasil - VIVO", and "impressora nao imprime"
never matches a ticket titled "Impressora sem toner", even though every word is
present. Measured on the reference instance: each word alone returned a row,
the natural phrase returned zero. A caller phrasing a question the way people
speak got "nenhum resultado" as if it were a fact about the data.

The fix is to search for the *words*, not the string. Three strategies, tried
in order of precision, and the one that answered is reported back so the caller
can tell an exact hit from a widened one.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Connectors carry no discriminating power but would still have to match under
# AND. "problema com impressora" must not fail because no title contains "com".
# Dropped only when a meaningful term survives, so a query that is *entirely*
# stopwords still searches for something instead of matching everything.
_STOPWORDS = frozenset(
    {
        "a", "ao", "aos", "as", "às", "com", "como", "da", "das", "de", "dela",
        "dele", "do", "dos", "e", "em", "entre", "essa", "esse", "esta", "este",
        "eu", "foi", "há", "isso", "isto", "já", "la", "lo", "mas", "me", "mais",
        "meu", "minha", "muito", "na", "nas", "no", "nos", "num", "numa", "o",
        "os", "ou", "para", "pela", "pelo", "per", "por", "pra", "qual", "quando",
        "que", "se", "sem", "ser", "seu", "sua", "são", "só", "tem", "um", "uma",
        "and", "for", "from", "of", "or", "the", "to", "with",
    }
)

# A one-character token matches almost every row, so it costs a criteria group
# and buys nothing. Kept as a floor rather than a filter on meaning: "TI", "AD"
# and "PC" are two characters and genuinely discriminate.
_MIN_TERM_LENGTH = 2

# A pathological query ("copy-pasted the whole email") would otherwise build one
# criteria group per word and produce a URL the API rejects. The leading terms
# carry the intent; the tail is almost always narrative.
_MAX_TERMS = 6

_QUOTED = re.compile(r'"([^"]+)"')


def split_terms(query: str) -> Tuple[List[str], List[str]]:
    """Split a query into search terms.

    Returns ``(terms, quoted)``. A double-quoted run stays whole, which is how a
    caller asks for a literal phrase — "Telefonica Brasil" as one term rather
    than two. Everything else splits on whitespace.
    """
    if not query:
        return [], []

    text = str(query).strip()
    quoted = [m.strip() for m in _QUOTED.findall(text) if m.strip()]
    remainder = _QUOTED.sub(" ", text)

    bare = [t for t in re.split(r"\s+", remainder) if t]
    # Punctuation glued to a word ("impressora," / "- VIVO") would be searched
    # literally and match nothing.
    bare = [t.strip(".,;:!?()[]{}<>/\\'\"") for t in bare]
    bare = [t for t in bare if t]

    terms = quoted + bare
    return terms[:_MAX_TERMS], quoted


def significant_terms(terms: Sequence[str]) -> List[str]:
    """Drop connectors and single characters, unless nothing would remain."""
    kept = [
        t
        for t in terms
        if len(t) >= _MIN_TERM_LENGTH and t.lower() not in _STOPWORDS
    ]
    return kept or list(terms)


def build_text_criteria(
    fields: Sequence[int],
    terms: Sequence[str],
    mode: str = "all",
) -> List[Dict[str, Any]]:
    """Build top-level criteria groups matching ``terms`` across ``fields``.

    ``all``  — every term must appear in at least one field. One group per term,
               joined by AND; inside a group the fields are ORed.
    ``any``  — at least one term in at least one field. A single OR group.

    Groups are returned at the *top* level rather than wrapped in one outer
    group: the caller appends its own filters after them, and GLPI evaluates a
    flat list left to right, so keeping every text group a sibling of the
    filters is what makes "these words AND that status" mean what it says.
    Nesting depth stays at two, which is the depth already proven against the
    live API.
    """
    usable = [f for f in fields if f is not None]
    if not usable or not terms:
        return []

    if mode == "any":
        flat: List[Dict[str, Any]] = []
        for term in terms:
            for field in usable:
                crit: Dict[str, Any] = {
                    "field": field,
                    "searchtype": "contains",
                    "value": term,
                }
                if flat:
                    crit["link"] = "OR"
                flat.append(crit)
        return [{"criteria": flat}]

    groups: List[Dict[str, Any]] = []
    for term in terms:
        inner: List[Dict[str, Any]] = []
        for field in usable:
            crit = {"field": field, "searchtype": "contains", "value": term}
            if inner:
                crit["link"] = "OR"
            inner.append(crit)
        group: Dict[str, Any] = {"criteria": inner}
        if groups:
            group["link"] = "AND"
        groups.append(group)
    return groups


def score_by_coverage(row: Any, terms: Sequence[str]) -> int:
    """Count how many distinct terms appear anywhere in a result row.

    Used only to order a widened (``any``) search. GLPI returns the first N rows
    by sort column, not the most relevant ones, so without this the widened
    stage would answer a three-word question with whatever happened to be
    newest.
    """
    if not isinstance(row, dict):
        return 0
    haystack = " ".join(str(v) for v in row.values() if v is not None).lower()
    return sum(1 for t in terms if t.lower() in haystack)


def describe_stage(
    stage: str, terms: Sequence[str], found: bool = True
) -> Optional[str]:
    """Explain a widened search, or return None when the phrase matched as given.

    A widened result is still an answer, but it is not the answer that was
    asked for, and a caller that cannot tell the difference will report a loose
    match as an exact one.

    ``found=False`` inverts the wording: the same final stage means "and even
    this did not match" rather than "this is what matched". Reusing the success
    sentence for an empty result would state that items containing the terms
    were returned, next to a table containing none.
    """
    joined = ", ".join(terms)
    if not found:
        if len(terms) <= 1:
            return None
        return (
            f"Busca esgotada: nada encontrado para a frase exata, "
            f"para todos os termos, nem para qualquer um deles ({joined})."
        )
    if stage == "phrase":
        return None
    if stage == "all":
        return (
            f"Busca ampliada: nenhum resultado para a frase exata; "
            f"exibindo itens que contem todos os termos ({joined})."
        )
    if stage == "any":
        return (
            f"Busca ampliada: nenhum resultado com todos os termos; "
            f"exibindo itens que contem ao menos um ({joined}), "
            f"ordenados por quantos termos casam."
        )
    return None


async def run_text_search(
    query: str,
    fields: Sequence[int],
    execute: Any,
    limit: int,
    over_fetch: int = 3,
    max_fetch: int = 60,
) -> Tuple[List[Any], Optional[int], str, List[str]]:
    """Run the escalation ladder, stopping at the first stage that answers.

    ``execute(text_groups, fetch_limit)`` performs one search and returns
    ``(rows, total)``; the caller owns how the text groups combine with its own
    filters, since only it knows them.

    @MX:ANCHOR: every free-text tool escalates through this one function.
    @MX:REASON: five services each running their own ladder is how the
    stage-reporting drifts — one of them stops saying the result was widened,
    and a loose match starts being presented as an exact one.

    The widened stage over-fetches before ranking: GLPI returns the first N rows
    by sort column, not the best N, so trimming an unranked page would answer a
    three-word question with whatever happened to be newest.
    """
    stages, terms = plan_stages(query)
    rows: List[Any] = []
    total: Optional[int] = None
    stage = "phrase"

    for stage_name, stage_terms in stages:
        stage = stage_name
        mode = "any" if stage_name == "any" else "all"
        groups = build_text_criteria(fields, stage_terms, mode=mode)
        fetch = min(limit * over_fetch, max_fetch) if stage_name == "any" else limit
        rows, total = await execute(groups, fetch)
        rows = list(rows or [])
        if rows:
            if stage_name == "any":
                ranked = sorted(
                    rows,
                    key=lambda r: score_by_coverage(r, stage_terms),
                    reverse=True,
                )
                rows = ranked[:limit]
                # The over-fetched window makes `total` describe more rows than
                # were kept; reporting it verbatim would promise a next page
                # that ranking already consumed.
                if total is not None and total > len(rows):
                    total = None
            return rows, total, stage_name, list(stage_terms)

    return rows, total, stage, terms


def plan_stages(query: str) -> Tuple[List[Tuple[str, List[str]]], List[str]]:
    """Return the ordered (stage, terms) attempts for a query.

    A single-word query collapses to one attempt: phrase, all and any would
    issue identical requests, and paying three round-trips to learn that is
    waste on the most common call of all.
    """
    raw = str(query or "").strip()
    if not raw:
        return [], []

    terms, quoted = split_terms(raw)
    if len(terms) <= 1:
        return [("phrase", [raw])], terms or [raw]

    # An entirely quoted query is an explicit request for the literal string;
    # widening it would answer a different question than the one asked.
    if quoted and len(quoted) == len(terms):
        return [("phrase", [raw])], terms

    meaningful = significant_terms(terms)
    return (
        [("phrase", [raw]), ("all", meaningful), ("any", meaningful)],
        meaningful,
    )
