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
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
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
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
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
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
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
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
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
    """Format webhooks list."""
    items = data if isinstance(data, list) else data.get("data", data.get("items", []))
    if not items:
        return "Nenhum webhook encontrado."
    rows = []
    for w in items:
        rows.append(
            f"| {esc(w.get('id'))} "
            f"| {esc(w.get('name', 'N/A'))} "
            f"| {truncate_field(w.get('url', ''), 60)} "
            f"| {'Ativo' if w.get('is_active') else 'Inativo'} "
            f"| {esc(w.get('event', 'N/A'))} |"
        )
    table = "\n".join(rows)
    return f"**{len(items)} webhooks**\n\n| ID | Nome | URL | Status | Evento |\n|---|---|---|---|---|\n{table}"


def format_webhook_detail(data: dict) -> str:
    """Format webhook details."""
    if not data:
        return "Webhook nao encontrado."
    return (
        f"# Webhook: {esc(data.get('name', 'N/A'))}\n\n"
        f"| Campo | Valor |\n|---|---|\n"
        f"| ID | {esc(data.get('id'))} |\n"
        f"| Nome | {esc(data.get('name'))} |\n"
        f"| URL | {esc(data.get('url', 'N/A'))} |\n"
        f"| Evento | {esc(data.get('event', 'N/A'))} |\n"
        f"| Ativo | {'Sim' if data.get('is_active') else 'Nao'} |\n"
        f"| Secret | {'Configurado' if data.get('secret') else 'Nao configurado'} |"
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
    """Format success message for mutation operations."""
    if not data:
        return f"Operacao '{operation}' realizada com sucesso."
    msg = data.get("message", "") if isinstance(data, dict) else ""
    item_id = data.get("id", "") if isinstance(data, dict) else ""
    parts = [f"Operacao '{operation}' realizada com sucesso."]
    if item_id:
        parts.append(f"ID: {esc(item_id)}")
    if msg:
        parts.append(f"Mensagem: {esc(msg)}")
    return " ".join(parts)
