"""
Markdown formatters for GLPI MCP domains.
Each function converts a Python dict/list to an optimized Markdown string.

SPEC-GLPI-ENHANCE-001/F01 — Section 4.1.2
Pattern: Adapted from Hudu src/formatters/markdown.ts
"""

from typing import Optional

from src.formatters.markdown_helpers import (
    esc,
    fmt_date,
    fmt_impact,
    fmt_priority,
    fmt_sla,
    fmt_status,
    fmt_type,
    fmt_urgency,
    glpi_id_link,
    glpi_url,
    page_info,
    remove_heavy_fields,
    strip_html,
    truncate_field,
)


def _actor(value, max_len: int = 24) -> str:
    """Render a GLPI actor/dropdown display value (solicitante, tecnico,
    categoria, grupo). Empty/zero -> em-dash. Junta multiplos atores (a Search
    API devolve listas quando ha varios) numa unica linha separada por virgula.
    """
    if value is None or value in ("", "0", 0):
        return "—"
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if v not in (None, "", 0, "0")]
        text = ", ".join(parts)
    else:
        text = str(value).replace("\r", "").replace("\n", ", ")
    text = text.strip(", ").strip()
    if not text or text == "0":
        return "—"
    cleaned = truncate_field(text, max_len)
    return cleaned or "—"


def _sla_flag(value) -> str:
    """Coluna SLA da listagem: campo 82 da Search API e a flag 'atrasado'
    (1 = TTR estourado). Mostra ATRASADO ou travessao."""
    if str(value).strip() in ("1", "True", "true"):
        return "ATRASADO"
    return "—"


# === TICKETS ===


def format_tickets_list(data, args: dict) -> str:
    """Format ticket list as a RICH Markdown table.

    Expoe numa unica varredura os campos que importam para decisao:
    solicitante, tecnico atribuido, categoria, urgencia e prazo de SLA (com
    flag ATRASADO) — sem precisar abrir ticket a ticket.
    """
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhum ticket encontrado."
    total = data.get("totalcount") if isinstance(data, dict) else None
    header = page_info(len(items), args.get("limit", 10), args.get("offset", 0), total)
    rows = []
    for t in items:
        rows.append(
            f"| {glpi_id_link('Ticket', t.get('id'))} "
            f"| {truncate_field(t.get('name', ''), 150)} "
            f"| {fmt_status(t.get('status'))} "
            f"| {fmt_priority(t.get('priority'))} "
            f"| {fmt_urgency(t.get('urgency'))} "
            f"| {_actor(t.get('requester'), 150)} "
            f"| {_actor(t.get('tech_assign'), 150)} "
            f"| {_actor(t.get('category'), 150)} "
            f"| {truncate_field(t.get('desc_snippet', ''), 300)} "
            f"| {fmt_date(t.get('date'))} "
            f"| {_sla_flag(t.get('sla_late'))} |"
        )
    table = "\n".join(rows)
    return (
        f"{header}\n\n"
        f"| ID | Titulo | Status | Prio | Urg | Solicitante | Tecnico | Categoria | Descricao | Aberto | SLA |\n"
        f"|---|---|---|---|---|---|---|---|---|---|---|\n{table}"
    )


# GLPI global_validation codes -> rotulo legivel (status de aprovacao do ticket).
_VALIDATION = {
    1: "Nao requer",
    2: "Aguardando",
    3: "Recusada",
    4: "Aceita",
}


def _dropdown(data: dict, key: str, default: str = "N/A") -> str:
    """Render a field that came resolved via expand_dropdowns (ja e um NOME) ou,
    na falta, o valor cru. Trata vazios/zero como N/A."""
    v = data.get(key)
    if v in (None, "", "0", 0):
        return default
    return esc(v)


def _validation(code) -> str:
    if code in (None, "", "0", 0):
        return "Nao requer"
    try:
        return _VALIDATION.get(int(code), f"Codigo {code}")
    except (ValueError, TypeError):
        return str(code)


def _attachments(count, breakdown: Optional[dict] = None) -> str:
    if count is None:
        return "N/D (nao consultado)"
    if count == 0:
        return "Nenhum"
    base = f"{count} anexo(s)"
    if breakdown and breakdown.get("followups"):
        base += (
            f" (chamado: {breakdown.get('ticket', 0)}, "
            f"followups: {breakdown.get('followups', 0)})"
        )
    return base


def _followups_section(followups) -> str:
    """Render a conversa de acompanhamentos (follow-ups) abaixo do detalhe.

    Permite ao LLM responder 'o tecnico ja respondeu?' direto da tool de
    detalhe, sem precisar chamar get_followups separadamente.
    """
    if not followups or not isinstance(followups, list):
        return ""
    parts = [f"\n\n## Acompanhamentos ({len(followups)})\n"]
    for f in followups:
        if not isinstance(f, dict):
            continue
        date = fmt_date(f.get("date"))
        author = esc(f.get("author") or "?")
        vis = " _(privado)_" if f.get("is_private") else ""
        content = truncate_field(f.get("content", ""), 1500) or "—"
        parts.append(f"\n**{date} — {author}{vis}:**\n\n{content}\n")
    return "".join(parts)


def format_ticket_detail(data: dict) -> str:
    """Format ticket details with the MAXIMUM available context.

    Inclui atores resolvidos (solicitante/tecnico/grupo), categoria, urgencia,
    impacto, origem, localizacao, SLA com flag de atraso, datas de solucao/
    fechamento, validacao e contagem de anexos — enriquecidos por
    TicketService.get_ticket_detail.
    """
    if not data:
        return "Ticket nao encontrado."
    # @MX:NOTE: delete de ticket no GLPI e soft-delete (is_deleted=1 -> lixeira).
    deleted = str(data.get("is_deleted", 0)) in ("1", "True")
    trash_banner = "\n> ⚠️ Este ticket está NA LIXEIRA do GLPI (excluído / is_deleted=1).\n" if deleted else ""
    trash_row = "| Na lixeira | Sim (is_deleted=1) |\n" if deleted else ""

    # Solicitante: prefere o ator real (Ticket_User type=1); cai p/ quem registrou.
    requester = data.get("requester_names") or data.get("users_id_recipient")
    origem = data.get("request_source_name") or data.get("requesttypes_id")
    _url = glpi_url("Ticket", data.get("id"))
    link = f"[Abrir no GLPI]({_url})" if _url else "N/A"

    base = (
        f"# Ticket #{esc(data.get('id', 'N/A'))}: {esc(data.get('name', 'Sem titulo'))}\n"
        f"{trash_banner}\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Titulo | {esc(data.get('name'))} |\n"
        f"| Link | {link} |\n"
        f"{trash_row}"
        f"| Status | {fmt_status(data.get('status'))} |\n"
        f"| Tipo | {fmt_type(data.get('type'))} |\n"
        f"| Prioridade | {fmt_priority(data.get('priority'))} |\n"
        f"| Urgencia | {fmt_urgency(data.get('urgency'))} |\n"
        f"| Impacto | {fmt_impact(data.get('impact'))} |\n"
        f"| Categoria | {_dropdown(data, 'itilcategories_id')} |\n"
        f"| Solicitante | {_actor(requester, 80)} |\n"
        f"| Tecnico atribuido | {_actor(data.get('assign_tech_names'), 80)} |\n"
        f"| Grupo atribuido | {_actor(data.get('assign_group_names'), 80)} |\n"
        f"| Registrado por | {_dropdown(data, 'users_id_recipient')} |\n"
        f"| Origem | {_actor(origem, 40)} |\n"
        f"| Entidade | {_dropdown(data, 'entities_id')} |\n"
        f"| Localizacao | {_dropdown(data, 'locations_id')} |\n"
        f"| Anexos | {_attachments(data.get('attachment_count'), data.get('attachment_breakdown'))} |\n"
        f"| Validacao | {_validation(data.get('global_validation'))} |\n"
        f"| Abertura | {fmt_date(data.get('date'))} |\n"
        f"| Ultima atualizacao | {fmt_date(data.get('date_mod'))} |\n"
        f"| Prazo SLA (resolver) | {fmt_sla(data.get('time_to_resolve'), data.get('status'))} |\n"
        f"| Solucionado em | {fmt_date(data.get('solvedate'))} |\n"
        f"| Fechado em | {fmt_date(data.get('closedate'))} |\n"
        f"| Descricao | {truncate_field(data.get('content', ''), 4000)} |"
    )
    return base + _followups_section(data.get("followups"))


def format_ticket_followups(data, args: dict) -> str:
    """Format ticket followups list."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhum acompanhamento encontrado para este ticket."
    rows = []
    for f in items:
        rows.append(
            f"| {esc(f.get('id'))} "
            f"| {fmt_date(f.get('date'))} "
            f"| {truncate_field(f.get('content', ''), 200)} "
            f"| {'Privado' if f.get('is_private') else 'Publico'} "
            f"| {esc(f.get('users_id', 'N/A'))} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} acompanhamentos**\n\n| ID | Data | Conteudo | Visibilidade | Autor |\n|---|---|---|---|---|\n{table}"


# GLPI Ticket Log: mapa dos id_search_option mais comuns -> rotulo legivel.
# Sem isto a coluna "Campo" mostra numeros crus (ex: 12, 64) ininteligiveis ao LLM.
_TICKET_LOG_FIELDS = {
    "0": "Item vinculado",
    "1": "Titulo",
    "3": "Prioridade",
    "4": "Solicitante",
    "5": "Tecnico atribuido",
    "7": "Categoria",
    "8": "Grupo tecnico",
    "10": "Urgencia",
    "11": "Impacto",
    "12": "Status",
    "13": "Itens associados",
    "15": "Data de abertura",
    "17": "Data de solucao",
    "19": "Ultima atualizacao",
    "21": "Descricao",
    "64": "Ultima edicao por",
    "150": "Tempo p/ inicio de atendimento",
}


def _resolve_log_field(h: dict) -> str:
    """Resolve o campo alterado para um rotulo legivel.

    Prefere o texto 'field' (quando o GLPI o expoe), senao mapeia o
    id_search_option, e por fim cai para 'Campo {codigo}'.
    """
    field_text = str(h.get("field", "") or "").strip()
    if field_text:
        return field_text
    code = str(h.get("id_search_option", "") or "").strip()
    if not code:
        return "—"
    return _TICKET_LOG_FIELDS.get(code, f"Campo {code}")


def format_ticket_history(data, args: dict) -> str:
    """Format ticket change history."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhum historico encontrado para este ticket."
    rows = []
    for h in items[:50]:
        # GLPI Log expoe o autor como 'user_name' (string), nao 'users_id'.
        author = str(h.get("user_name", "") or "").strip() or "N/A"
        rows.append(
            f"| {fmt_date(h.get('date_mod'))} "
            f"| {truncate_field(_resolve_log_field(h), 40)} "
            f"| {truncate_field(str(h.get('old_value', '')), 100)} "
            f"| {truncate_field(str(h.get('new_value', '')), 100)} "
            f"| {esc(author)} |"
        )
    table = "\n".join(rows)
    note = f"\n\n*Mostrando 50 de {len(items)} entradas*" if len(items) > 50 else ""
    return f"**{len(items)} alteracoes**\n\n| Data | Campo | Antes | Depois | Usuario |\n|---|---|---|---|---|\n{table}{note}"


def format_ticket_stats(data) -> str:
    """Format ticket statistics."""
    if not data:
        return "Estatisticas nao disponiveis."
    parts = ["# Estatisticas de Tickets\n"]
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                parts.append(f"\n## {esc(key)}\n")
                parts.append("| Metrica | Valor |\n|---|---|")
                for k, v in value.items():
                    parts.append(f"| {esc(k)} | {esc(v)} |")
            else:
                parts.append(f"- **{esc(key)}:** {esc(value)}")
    return "\n".join(parts)


def format_similar_tickets(data, args: dict) -> str:
    """Format similar tickets list with scores."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhum ticket similar encontrado."
    rows = []
    for t in items:
        score = t.get("score", t.get("similarity", "N/A"))
        rows.append(
            f"| {glpi_id_link('Ticket', t.get('id'))} "
            f"| {truncate_field(t.get('name', ''), 80)} "
            f"| {fmt_status(t.get('status'))} "
            f"| {esc(score)} "
            f"| {fmt_date(t.get('date'))} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} tickets similares**\n\n| ID | Titulo | Status | Score | Data |\n|---|---|---|---|---|\n{table}"


# === ASSETS ===


def format_assets_list(data, args: dict) -> str:
    """Format asset list as Markdown table."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhum ativo encontrado."
    total = data.get("totalcount") if isinstance(data, dict) else None
    header = page_info(len(items), args.get("limit", 10), args.get("offset", 0), total)
    rows = []
    for a in items:
        rows.append(
            f"| {glpi_id_link(a.get('asset_type', 'Computer'), a.get('id'))} "
            f"| {truncate_field(a.get('name', ''), 40)} "
            f"| {esc(a.get('serial', 'N/A'))} "
            f"| {_actor(a.get('states_id'), 18)} "
            f"| {_actor(a.get('locations_id'), 22)} "
            f"| {_actor(a.get('manufacturers_id'), 18)} "
            f"| {_actor(a.get('models_id'), 20)} "
            f"| {_actor(a.get('users_id'), 20)} |"
        )
    table = "\n".join(rows)
    return (
        f"{header}\n\n"
        f"| ID | Nome | Serial | Status | Localizacao | Fabricante | Modelo | Usuario |\n"
        f"|---|---|---|---|---|---|---|---|\n{table}"
    )


def _asset_field(data: dict, id_key: str, name_key: str) -> str:
    """Prefere o nome resolvido (*_name); senao mostra o id; 0/vazio -> N/A.

    @MX:NOTE: o get de ativo exibia codigos crus (Status: 0, Localizacao: 0).
    asset_service.get_asset enriquece com *_name via dropdown_cache; aqui
    consumimos esse nome quando disponivel.
    """
    name = data.get(name_key)
    if name:
        return esc(name)
    raw = data.get(id_key)
    if raw in (None, "", 0, "0"):
        return "N/A"
    return esc(raw)


def format_asset_detail(data: dict) -> str:
    """Format asset details as field-value Markdown table."""
    if not data:
        return "Ativo nao encontrado."
    deleted = str(data.get("is_deleted", 0)) in ("1", "True")
    trash_banner = "\n> ⚠️ Este ativo está NA LIXEIRA do GLPI (excluído / is_deleted=1).\n" if deleted else ""
    trash_row = "| Na lixeira | Sim (is_deleted=1) |\n" if deleted else ""
    return (
        f"# Ativo: {esc(data.get('name', 'Sem nome'))}\n"
        f"{trash_banner}\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Nome | {esc(data.get('name'))} |\n"
        f"| Link | {('[Abrir no GLPI](' + glpi_url(data.get('asset_type', 'Computer'), data.get('id')) + ')') if glpi_url(data.get('asset_type', 'Computer'), data.get('id')) else 'N/A'} |\n"
        f"{trash_row}"
        f"| Serial | {esc(data.get('serial', 'N/A'))} |\n"
        f"| Patrimonio | {esc(data.get('otherserial', 'N/A'))} |\n"
        f"| Status | {_asset_field(data, 'states_id', 'states_name')} |\n"
        f"| Localizacao | {_asset_field(data, 'locations_id', 'locations_name')} |\n"
        f"| Entidade | {_asset_field(data, 'entities_id', 'entities_name')} |\n"
        f"| Fabricante | {_asset_field(data, 'manufacturers_id', 'manufacturers_name')} |\n"
        f"| Modelo | {_asset_field(data, 'models_id', 'models_name')} |\n"
        f"| Usuario | {_asset_field(data, 'users_id', 'users_name')} |\n"
        f"| Grupo | {_asset_field(data, 'groups_id', 'groups_name')} |\n"
        f"| Comentario | {truncate_field(data.get('comment', ''), 2000)} |"
    )


def format_asset_stats(data) -> str:
    """Format asset statistics."""
    if not data:
        return "Estatisticas de ativos nao disponiveis."
    parts = ["# Estatisticas de Ativos\n"]
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                parts.append(f"\n## {esc(key)}\n")
                parts.append("| Metrica | Valor |\n|---|---|")
                for k, v in value.items():
                    parts.append(f"| {esc(k)} | {esc(v)} |")
            else:
                parts.append(f"- **{esc(key)}:** {esc(value)}")
    return "\n".join(parts)


def format_reservations_list(data, args: dict) -> str:
    """Format reservations OR reservable items (scope-aware)."""
    scope = (args or {}).get("scope", "reservations")
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # @MX:NOTE: scope=reservable retorna a chave 'reservable_items' (antes
        # ignorada -> sempre vazio); scope=reservations usa data/items.
        items = (
            data.get("reservable_items")
            or data.get("data")
            or data.get("items")
            or []
        )
    else:
        items = []

    if scope == "reservable":
        if not items:
            return "Nenhum item reservavel encontrado."
        rows = [
            f"| {esc(r.get('id'))} "
            f"| {esc(r.get('itemtype', 'N/A'))} "
            f"| {glpi_id_link(r.get('itemtype', 'Computer'), r.get('items_id'))} "
            f"| {esc(r.get('name') or r.get('item_name', 'N/A'))} "
            f"| {esc(r.get('is_active', 'N/A'))} |"
            for r in items
        ]
        table = "\n".join(rows)
        return (
            f"**{len(items)} itens reservaveis**\n\n"
            f"| ID | Tipo | Item ID | Nome | Ativo |\n|---|---|---|---|---|\n{table}"
        )

    if not items:
        return "Nenhuma reserva encontrada."
    rows = []
    for r in items:
        rows.append(
            f"| {esc(r.get('id'))} "
            f"| {esc(r.get('items_id', 'N/A'))} "
            f"| {fmt_date(r.get('begin'))} "
            f"| {fmt_date(r.get('end'))} "
            f"| {esc(r.get('users_id', 'N/A'))} "
            f"| {truncate_field(r.get('comment', ''), 100)} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} reservas**\n\n| ID | Item | Inicio | Fim | Usuario | Comentario |\n|---|---|---|---|---|---|\n{table}"


# === ADMIN ===


def format_users_list(data, args: dict) -> str:
    """Format users list as Markdown table."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("users") or data.get("data") or data.get("items") or []
    else:
        items = []
    if not items:
        return "Nenhum usuario encontrado."
    total = data.get("totalcount") if isinstance(data, dict) else None
    header = page_info(len(items), args.get("limit", 10), args.get("offset", 0), total)
    rows = []
    for u in items:
        full_name = f"{u.get('realname', '') or ''} {u.get('firstname', '') or ''}".strip()
        phone = u.get("phone") or u.get("mobile")
        ativo = "Sim" if str(u.get("is_active", "")) in ("1", "True", "true") else "Nao"
        rows.append(
            f"| {glpi_id_link('User', u.get('id'))} "
            f"| {esc(u.get('name', 'N/A'))} "
            f"| {esc(full_name) or '—'} "
            f"| {_actor(phone, 20)} "
            f"| {_actor(u.get('entities_id'), 24)} "
            f"| {ativo} "
            f"| {fmt_date(u.get('last_login'))} |"
        )
    table = "\n".join(rows)
    return (
        f"{header}\n\n"
        f"| ID | Login | Nome Completo | Telefone | Entidade | Ativo | Ultimo Login |\n"
        f"|---|---|---|---|---|---|---|\n{table}"
    )


def format_user_detail(data: dict) -> str:
    """Format user details with the MAXIMUM available context."""
    if not data:
        return "Usuario nao encontrado."
    full_name = f"{data.get('realname', '') or ''} {data.get('firstname', '') or ''}".strip()
    deleted = str(data.get("is_deleted", 0)) in ("1", "True")
    trash_row = "| Na lixeira | Sim (is_deleted=1) |\n" if deleted else ""
    # Conta grupos/perfis quando vierem como subitens enriquecidos.
    groups = data.get("groups") or []
    n_groups = len(groups) if isinstance(groups, list) else 0
    entity = data.get("entities_name") or data.get("entities_id")
    supervisor = data.get("supervisor_name") or data.get("users_id_supervisor")
    location = data.get("locations_name") or data.get("locations_id")
    return (
        f"# Usuario: {esc(data.get('name', 'N/A'))}"
        + (f" ({esc(full_name)})" if full_name else "")
        + "\n\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Login | {esc(data.get('name'))} |\n"
        f"| Link | {('[Abrir no GLPI](' + glpi_url('User', data.get('id')) + ')') if glpi_url('User', data.get('id')) else 'N/A'} |\n"
        f"{trash_row}"
        f"| Nome completo | {esc(full_name) or 'N/A'} |\n"
        f"| Email | {_dropdown(data, 'email')} |\n"
        f"| Telefone | {_dropdown(data, 'phone')} |\n"
        f"| Telefone 2 | {_dropdown(data, 'phone2')} |\n"
        f"| Celular | {_dropdown(data, 'mobile')} |\n"
        f"| Matricula | {_dropdown(data, 'registration_number')} |\n"
        f"| Ativo | {'Sim' if str(data.get('is_active')) in ('1', 'True', 'true') else 'Nao'} |\n"
        f"| Entidade | {_actor(entity, 60)} |\n"
        f"| Localizacao | {_actor(location, 60)} |\n"
        f"| Supervisor | {_actor(supervisor, 60)} |\n"
        f"| Grupos | {n_groups if n_groups else '—'} |\n"
        f"| Criado em | {fmt_date(data.get('date_creation'))} |\n"
        f"| Ultimo login | {fmt_date(data.get('last_login'))} |\n"
        f"| Comentario | {truncate_field(data.get('comment', ''), 500)} |"
    )


def format_groups_list(data, args: dict) -> str:
    """Format groups list."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("groups") or data.get("data") or data.get("items") or []
    else:
        items = []
    if not items:
        return "Nenhum grupo encontrado."
    rows = []
    for g in items:
        rows.append(
            f"| {glpi_id_link('Group', g.get('id'))} "
            f"| {esc(g.get('name', 'N/A'))} "
            f"| {truncate_field(g.get('comment', ''), 100)} "
            f"| {esc(g.get('entities_id', 'N/A'))} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} grupos**\n\n| ID | Nome | Comentario | Entidade |\n|---|---|---|---|\n{table}"


def format_entities_list(data, args: dict) -> str:
    """Format entities list."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("entities") or data.get("data") or data.get("items") or []
    else:
        items = []
    if not items:
        return "Nenhuma entidade encontrada."
    rows = []
    for e in items:
        rows.append(
            f"| {glpi_id_link('Entity', e.get('id'))} "
            f"| {esc(e.get('name', 'N/A'))} "
            f"| {truncate_field(e.get('comment', ''), 100)} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} entidades**\n\n| ID | Nome | Comentario |\n|---|---|---|\n{table}"


def format_locations_list(data, args: dict) -> str:
    """Format locations list."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("locations") or data.get("data") or data.get("items") or []
    else:
        items = []
    if not items:
        return "Nenhuma localizacao encontrada."
    rows = []
    for loc in items:
        rows.append(
            f"| {glpi_id_link('Location', loc.get('id'))} "
            f"| {esc(loc.get('name', 'N/A'))} "
            f"| {esc(loc.get('address', 'N/A'))} "
            f"| {esc(loc.get('entities_id', 'N/A'))} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} localizacoes**\n\n| ID | Nome | Endereco | Entidade |\n|---|---|---|---|\n{table}"


def format_admin_detail(data: dict, resource: str) -> str:
    """Format generic admin resource details."""
    if not data:
        return f"{resource.capitalize()} nao encontrado(a)."
    parts = [f"# {esc(resource.capitalize())}: {esc(data.get('name', 'N/A'))}\n"]
    parts.append("| Campo | Valor |\n|---|---|")
    for key, value in data.items():
        if key in ("links", "_links", "completename") or key.startswith("_"):
            continue
        display_value = truncate_field(str(value), 300) if isinstance(value, str) else esc(value)
        parts.append(f"| {esc(key)} | {display_value} |")
    return "\n".join(parts)


# === WEBHOOKS ===


def format_webhooks_list(data, args: dict) -> str:
    """Format webhooks list (GLPI 11 native: itemtype/event/event_type)."""
    if isinstance(data, dict) and isinstance(data.get("webhooks"), list):
        items = data["webhooks"]
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data") or data.get("items") or []
    else:
        items = []
    if not items:
        return "Nenhum webhook encontrado."
    rows = []
    for w in items:
        event_label = w.get("event_type") or (
            f"{w.get('itemtype', '?')}.{w.get('event', '?')}"
            if w.get("itemtype")
            else "N/A"
        )
        rows.append(
            f"| {glpi_id_link('Webhook', w.get('id'))} "
            f"| {esc(w.get('name', 'N/A'))} "
            f"| {truncate_field(w.get('url', ''), 60)} "
            f"| {'Ativo' if w.get('is_active') else 'Inativo'} "
            f"| {esc(event_label)} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} webhooks**\n\n| ID | Nome | URL | Status | Evento |\n|---|---|---|---|---|\n{table}"


def format_webhook_detail(data: dict) -> str:
    """Format webhook details (GLPI 11 native fields)."""
    if not data:
        return "Webhook nao encontrado."
    event_label = data.get("event_type") or (
        f"{data.get('itemtype', '?')}.{data.get('event', '?')}"
        if data.get("itemtype")
        else "N/A"
    )
    _wurl = glpi_url("Webhook", data.get("id"))
    return (
        f"# Webhook: {esc(data.get('name', 'N/A'))}\n\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Link | {('[Abrir no GLPI](' + _wurl + ')') if _wurl else 'N/A'} |\n"
        f"| Nome | {esc(data.get('name'))} |\n"
        f"| URL (callback) | {esc(data.get('url', 'N/A'))} |\n"
        f"| Evento (MCP) | {esc(event_label)} |\n"
        f"| Itemtype | {esc(data.get('itemtype', 'N/A'))} |\n"
        f"| Event (GLPI) | {esc(data.get('event', 'N/A'))} |\n"
        f"| HTTP Method | {esc(data.get('http_method', 'POST'))} |\n"
        f"| Ativo | {'Sim' if data.get('is_active') else 'Nao'} |\n"
        f"| Secret | {'Configurado' if data.get('secret') else 'Nao configurado'} |\n"
        f"| Custom Headers | {esc(str(data.get('custom_headers') or {}))} |\n"
        f"| Use default payload | {'Sim' if data.get('use_default_payload') else 'Nao'} |\n"
        f"| Entidade | {esc(data.get('entities_id', 'N/A'))} |\n"
        f"| Recursivo | {'Sim' if data.get('is_recursive') else 'Nao'} |\n"
        f"| Criado | {esc(data.get('created_at', 'N/A'))} |\n"
        f"| Atualizado | {esc(data.get('updated_at', 'N/A'))} |\n"
        f"| Comentario | {truncate_field(data.get('comment', ''), 500)} |"
    )


def format_webhook_stats(data) -> str:
    """Format webhook statistics."""
    if not data:
        return "Estatisticas de webhooks nao disponiveis."
    parts = ["# Estatisticas de Webhooks\n"]
    if isinstance(data, dict):
        for key, value in data.items():
            parts.append(f"- **{esc(key)}:** {esc(value)}")
    return "\n".join(parts)


def format_webhook_deliveries(data, args: dict) -> str:
    """Format webhook deliveries list."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhuma entrega de webhook encontrada."
    rows = []
    for d in items:
        rows.append(
            f"| {esc(d.get('id'))} "
            f"| {fmt_date(d.get('date'))} "
            f"| {esc(d.get('status_code', 'N/A'))} "
            f"| {esc(d.get('event', 'N/A'))} "
            f"| {truncate_field(d.get('response', ''), 100)} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} entregas**\n\n| ID | Data | Status | Evento | Resposta |\n|---|---|---|---|---|\n{table}"


# === AI ANALYSIS ===


def format_ai_analysis_result(data) -> str:
    """Format AI analysis result."""
    if not data:
        return "Resultado de analise nao disponivel."
    parts = ["# Analise IA\n"]
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and len(value) > 300:
                parts.append(f"\n## {esc(key)}\n{truncate_field(value, 2000)}")
            else:
                parts.append(f"- **{esc(key)}:** {esc(value)}")
    return "\n".join(parts)


# === BRIDGE ===


def format_knowledge_articles(data, args: dict) -> str:
    """Format knowledge base articles as Markdown table."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("articles") or data.get("data") or data.get("items") or []
    else:
        items = []
    if not items:
        q = (args or {}).get("query", "")
        return f"Nenhum artigo encontrado na base de conhecimento{(' para: ' + q) if q else ''}."
    total = data.get("total", len(items)) if isinstance(data, dict) else len(items)
    rows = []
    for a in items:
        rows.append(
            f"| {glpi_id_link('KnowbaseItem', a.get('id'))} "
            f"| {truncate_field(a.get('name', ''), 80)} "
            f"| {esc(a.get('category', 'N/A'))} "
            f"| {esc(a.get('views', 0))} |"
        )
    table = "\n".join(rows)
    return (
        f"**{len(items)} artigo(s) encontrado(s)** (total: {total})\n\n"
        f"| ID | Titulo | Categoria | Visualizacoes |\n|---|---|---|---|\n{table}"
    )


def format_computer_details_enriched(data, args: dict) -> str:
    """Format enriched computer details (asset + sub-items).

    Accepts both the new shape {asset, operating_systems, disks, processors,
    memories, networks, software} and the legacy flat asset dict.
    """
    if not isinstance(data, dict):
        return format_asset_detail(data)

    asset = data.get("asset")
    if not isinstance(asset, dict):
        # Legacy/flat shape: treat the whole dict as the asset
        return format_asset_detail(data)

    parts = [format_asset_detail(asset)]

    def _section(title: str, items: list, columns: list[tuple[str, str]]) -> str:
        if not items:
            return ""
        header = "| " + " | ".join(c[0] for c in columns) + " |"
        sep = "|" + "|".join(["---"] * len(columns)) + "|"
        rows = []
        for it in items:
            row = "| " + " | ".join(esc(it.get(c[1], "")) for c in columns) + " |"
            rows.append(row)
        return f"\n\n## {title} ({len(items)})\n\n{header}\n{sep}\n" + "\n".join(rows)

    parts.append(
        _section(
            "Sistema Operacional",
            data.get("operating_systems") or [],
            [("ID", "id"), ("OS", "operatingsystems_id"), ("Versao", "operatingsystemversions_id")],
        )
    )
    parts.append(
        _section(
            "Discos",
            data.get("disks") or [],
            [("ID", "id"), ("Nome", "name"), ("Tamanho (MB)", "totalsize"), ("Filesystem", "filesystems_id")],
        )
    )
    parts.append(
        _section(
            "Processadores",
            data.get("processors") or [],
            [("ID", "id"), ("CPU ID", "deviceprocessors_id"), ("Freq (MHz)", "frequency"), ("Cores", "nbcores")],
        )
    )
    parts.append(
        _section(
            "Memorias",
            data.get("memories") or [],
            [("ID", "id"), ("Mem ID", "devicememories_id"), ("Tamanho (MB)", "size")],
        )
    )
    parts.append(
        _section(
            "Redes",
            data.get("networks") or [],
            [("ID", "id"), ("Nome", "name"), ("MAC", "mac")],
        )
    )
    parts.append(
        _section(
            "Software Instalado",
            (data.get("software") or [])[:25],
            [("ID", "id"), ("Software ID", "softwares_id"), ("Versao ID", "softwareversions_id")],
        )
    )

    return "".join(p for p in parts if p)


def format_resources_list(resources: list) -> str:
    """Format MCP resources list as Markdown table."""
    if not resources:
        return "Nenhum resource disponivel."
    rows = []
    for r in resources:
        rows.append(
            f"| {esc(r.get('uri', ''))} "
            f"| {esc(r.get('name', ''))} "
            f"| {esc(r.get('description', ''))} |"
        )
    table = "\n".join(rows)
    return f"**{len(resources)} resources disponiveis**\n\n| URI | Nome | Descricao |\n|---|---|---|\n{table}"


def format_prompts_list(prompts: list) -> str:
    """Format prompts list as Markdown table."""
    if not prompts:
        return "Nenhum prompt disponivel."
    rows = []
    for p in prompts:
        args_str = ", ".join(a.get("name", "") for a in p.get("arguments", []))
        rows.append(
            f"| {esc(p.get('name', ''))} "
            f"| {esc(p.get('description', ''))} "
            f"| {esc(p.get('category', ''))} "
            f"| {esc(args_str)} |"
        )
    table = "\n".join(rows)
    return f"**{len(prompts)} prompts disponiveis**\n\n| Nome | Descricao | Categoria | Argumentos |\n|---|---|---|---|\n{table}"


def format_operation_success(data, operation: str) -> str:
    """Format result message for mutation operations.

    Distinguishes between:
    - MCP error envelope (isError=True): render as FAILURE with the error text.
    - Real success payload: render as SUCCESS with id/message.
    Never returns "sucesso" when the underlying call actually failed.
    """
    if not data:
        return f"Operacao '{operation}' realizada com sucesso."

    if isinstance(data, dict):
        # Detect MCP error envelope produced by create_mcp_error / similar
        if data.get("isError") is True or data.get("error"):
            err_text = ""
            content = data.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict):
                    err_text = first.get("text", "") or ""
            if not err_text:
                err_text = str(data.get("error") or data.get("message") or "Erro desconhecido")
            return f"Operacao '{operation}' FALHOU: {err_text}"

        # Operacao reconhecida porem NAO SUPORTADA pelo backend (ex.: GLPI 11
        # nao expoe retry/trigger de webhook). Nem sucesso, nem falha: aviso.
        if data.get("supported") is False or data.get("status") == "not_supported":
            reason = data.get("message") or data.get("warning") or "Operacao nao suportada pelo GLPI"
            return f"Operacao '{operation}' NAO SUPORTADA: {reason}"

        # Explicit success=False
        if data.get("success") is False:
            reason = data.get("message") or data.get("error") or "Operacao nao confirmada pelo servidor"
            return f"Operacao '{operation}' FALHOU: {reason}"

        msg = data.get("message", "")
        item_id = data.get("id", "")
        parts = [f"Operacao '{operation}' realizada com sucesso."]
        if item_id:
            parts.append(f"ID: {esc(item_id)}")
        if msg:
            parts.append(f"Mensagem: {esc(msg)}")
        return " ".join(parts)

    return f"Operacao '{operation}' realizada com sucesso."
