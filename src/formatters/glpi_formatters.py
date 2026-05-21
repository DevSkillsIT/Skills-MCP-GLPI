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
    fmt_priority,
    fmt_status,
    fmt_type,
    page_info,
    remove_heavy_fields,
    strip_html,
    truncate_field,
)


# === TICKETS ===


def format_tickets_list(data, args: dict) -> str:
    """Format ticket list as Markdown table."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhum ticket encontrado."
    total = data.get("totalcount") if isinstance(data, dict) else None
    header = page_info(len(items), args.get("limit", 10), args.get("offset", 0), total)
    rows = []
    for t in items:
        rows.append(
            f"| {esc(t.get('id', 'N/A'))} "
            f"| {truncate_field(t.get('name', ''), 80)} "
            f"| {fmt_status(t.get('status'))} "
            f"| {fmt_priority(t.get('priority'))} "
            f"| {fmt_type(t.get('type'))} "
            f"| {fmt_date(t.get('date'))} |"
        )
    table = "\n".join(rows)
    return f"{header}\n\n| ID | Titulo | Status | Prioridade | Tipo | Abertura |\n|---|---|---|---|---|---|\n{table}"


def format_ticket_detail(data: dict) -> str:
    """Format ticket details as field-value Markdown table."""
    if not data:
        return "Ticket nao encontrado."
    return (
        f"# Ticket #{esc(data.get('id', 'N/A'))}: {esc(data.get('name', 'Sem titulo'))}\n\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Titulo | {esc(data.get('name'))} |\n"
        f"| Status | {fmt_status(data.get('status'))} |\n"
        f"| Prioridade | {fmt_priority(data.get('priority'))} |\n"
        f"| Tipo | {fmt_type(data.get('type'))} |\n"
        f"| Entidade | {esc(data.get('entities_id', 'N/A'))} |\n"
        f"| Solicitante | {esc(data.get('users_id_recipient', 'N/A'))} |\n"
        f"| Abertura | {fmt_date(data.get('date'))} |\n"
        f"| Ultima atualizacao | {fmt_date(data.get('date_mod'))} |\n"
        f"| SLA | {fmt_date(data.get('time_to_resolve'))} |\n"
        f"| Descricao | {truncate_field(data.get('content', ''), 2000)} |"
    )


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


def format_ticket_history(data, args: dict) -> str:
    """Format ticket change history."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhum historico encontrado para este ticket."
    rows = []
    for h in items[:50]:
        rows.append(
            f"| {fmt_date(h.get('date_mod'))} "
            f"| {truncate_field(str(h.get('id_search_option', '')), 50)} "
            f"| {truncate_field(str(h.get('old_value', '')), 100)} "
            f"| {truncate_field(str(h.get('new_value', '')), 100)} "
            f"| {esc(h.get('users_id', 'N/A'))} |"
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
            f"| {esc(t.get('id'))} "
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
            f"| {esc(a.get('id', 'N/A'))} "
            f"| {truncate_field(a.get('name', ''), 60)} "
            f"| {esc(a.get('serial', 'N/A'))} "
            f"| {esc(a.get('otherserial', 'N/A'))} "
            f"| {esc(a.get('states_id', 'N/A'))} "
            f"| {esc(a.get('locations_id', 'N/A'))} |"
        )
    table = "\n".join(rows)
    return f"{header}\n\n| ID | Nome | Serial | Patrimonio | Status | Localizacao |\n|---|---|---|---|---|---|\n{table}"


def format_asset_detail(data: dict) -> str:
    """Format asset details as field-value Markdown table."""
    if not data:
        return "Ativo nao encontrado."
    return (
        f"# Ativo: {esc(data.get('name', 'Sem nome'))}\n\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Nome | {esc(data.get('name'))} |\n"
        f"| Serial | {esc(data.get('serial', 'N/A'))} |\n"
        f"| Patrimonio | {esc(data.get('otherserial', 'N/A'))} |\n"
        f"| Status | {esc(data.get('states_id', 'N/A'))} |\n"
        f"| Localizacao | {esc(data.get('locations_id', 'N/A'))} |\n"
        f"| Entidade | {esc(data.get('entities_id', 'N/A'))} |\n"
        f"| Fabricante | {esc(data.get('manufacturers_id', 'N/A'))} |\n"
        f"| Modelo | {esc(data.get('models_id', 'N/A'))} |\n"
        f"| Usuario | {esc(data.get('users_id', 'N/A'))} |\n"
        f"| Grupo | {esc(data.get('groups_id', 'N/A'))} |\n"
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
    """Format reservations list."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
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
        rows.append(
            f"| {esc(u.get('id'))} "
            f"| {esc(u.get('name', 'N/A'))} "
            f"| {esc(u.get('realname', ''))} {esc(u.get('firstname', ''))} "
            f"| {esc(u.get('is_active', 'N/A'))} "
            f"| {fmt_date(u.get('last_login'))} |"
        )
    table = "\n".join(rows)
    return f"{header}\n\n| ID | Login | Nome Completo | Ativo | Ultimo Login |\n|---|---|---|---|---|\n{table}"


def format_user_detail(data: dict) -> str:
    """Format user details."""
    if not data:
        return "Usuario nao encontrado."
    return (
        f"# Usuario: {esc(data.get('name', 'N/A'))}\n\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Login | {esc(data.get('name'))} |\n"
        f"| Nome | {esc(data.get('realname', ''))} {esc(data.get('firstname', ''))} |\n"
        f"| Email | {esc(data.get('email', 'N/A'))} |\n"
        f"| Telefone | {esc(data.get('phone', 'N/A'))} |\n"
        f"| Ativo | {'Sim' if data.get('is_active') else 'Nao'} |\n"
        f"| Entidade | {esc(data.get('entities_id', 'N/A'))} |\n"
        f"| Ultimo login | {fmt_date(data.get('last_login'))} |"
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
            f"| {esc(g.get('id'))} "
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
            f"| {esc(e.get('id'))} "
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
            f"| {esc(loc.get('id'))} "
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
            f"| {esc(w.get('id'))} "
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
    return (
        f"# Webhook: {esc(data.get('name', 'N/A'))}\n\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Nome | {esc(data.get('name'))} |\n"
        f"| URL | {esc(data.get('url', 'N/A'))} |\n"
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
            f"| {esc(a.get('id'))} "
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
