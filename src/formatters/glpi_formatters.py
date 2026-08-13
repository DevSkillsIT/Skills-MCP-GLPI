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
    # @MX:NOTE: a widened text search is labelled as such, found or not.
    # @MX:REASON: "nenhum ticket encontrado" for a phrase and for every
    # relaxation of that phrase are different facts, and only the second one
    # justifies concluding the ticket does not exist.
    notice = data.get("search_notice") if isinstance(data, dict) else None
    if not items:
        empty = "Nenhum ticket encontrado."
        return f"{empty}\n\n_{notice}_" if notice else empty
    total = data.get("totalcount") if isinstance(data, dict) else None
    header = page_info(len(items), args.get("limit", 10), args.get("offset", 0), total)
    if notice:
        header = f"{header}\n\n_{notice}_"
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
            f"| {_actor(t.get('group_assign'), 150)} "
            f"| {_actor(t.get('category'), 150)} "
            f"| {truncate_field(t.get('desc_snippet', ''), 300)} "
            f"| {fmt_date(t.get('date'))} "
            f"| {_sla_flag(t.get('sla_late'))} |"
        )
    table = "\n".join(rows)
    # @MX:NOTE: the Grupo column exists because assigned_group is filterable.
    # Filtering by something the table does not show leaves the user unable to
    # confirm the filter took effect.
    return (
        f"{header}\n\n"
        f"| ID | Titulo | Status | Prio | Urg | Solicitante | Tecnico | Grupo | Categoria | Descricao | Aberto | SLA |\n"
        f"|---|---|---|---|---|---|---|---|---|---|---|---|\n{table}"
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


#: Nomes de tipo em portugues, para a linha de equipamento do chamado.
_ITEMTYPE_LABEL = {
    "Computer": "Computador",
    "Monitor": "Monitor",
    "Printer": "Impressora",
    "NetworkEquipment": "Equip. de rede",
    "Phone": "Telefone",
    "Peripheral": "Periferico",
    "Software": "Software",
    "Rack": "Rack",
    "Enclosure": "Enclosure",
}


def _linked_items(items) -> str:
    """Render the assets a ticket is about.

    @MX:NOTE: o vinculo chamado-equipamento e o contexto do atendimento.
    @MX:REASON: sao 18.580 vinculos nesta instancia contra 9.292 chamados, e
    nenhum aparecia. Sem isso, quem le o chamado sabe o sintoma e nao sabe em
    que maquina reproduzi-lo — e o dado ja estava cadastrado no proprio
    chamado.
    """
    if not items:
        return "—"
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        itemtype = str(item.get("itemtype") or "")
        # @MX:WARN: tipos com namespace nao sao equipamento.
        # @MX:REASON: o GLPI vincula ao chamado o proprio FORMULARIO que o
        # abriu (`Glpi\Form\Form`), no mesmo Item_Ticket dos ativos. Exibido
        # sob "Equipamento", ele aparecia lado a lado com a impressora real —
        # um objeto de software do GLPI apresentado como o equipamento do
        # atendimento. Nenhum ativo fisico usa nome com namespace.
        if "\\" in itemtype:
            continue
        label = _ITEMTYPE_LABEL.get(itemtype, itemtype or "Item")
        name = item.get("name")
        parts.append(f"{label}: {esc(name)}" if name else label)
    return " · ".join(parts) if parts else "—"


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
        f"| Equipamento | {_linked_items(data.get('linked_items'))} |\n"
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


# === TICKETS — COBERTURA ITIL (timeline, tarefas, aprovacoes) ===

# Rotulos dos eventos da timeline unificada.
_TIMELINE_LABELS = {
    "followup": "Acompanhamento",
    "task": "Tarefa",
    "solution": "Solucao",
    "validation": "Aprovacao",
}

# Rotulos plurais usados no resumo e no aviso de origem indisponivel.
_TIMELINE_PLURAL = {
    "followup": "acompanhamentos",
    "task": "tarefas",
    "solution": "solucoes",
    "validation": "aprovacoes",
}

# CommonITILActor: papel do ator no chamado (coluna `type` das tabelas de
# vinculo Ticket_User / Group_Ticket). Mesma ordem de ticket_service.ACTOR_TYPE.
_ACTOR_ROLE = {1: "Solicitante", 2: "Atribuido", 3: "Observador"}

# Ticket_Ticket: tipo do vinculo entre dois chamados.
_LINK_LABEL = {1: "Vinculo simples", 2: "Duplicado", 3: "Filho de", 4: "Pai de"}

# Estados de uma TicketTask.
_TASK_STATE = {0: "Informacao", 1: "A fazer", 2: "Concluida"}


def _one_line(text, max_len: int = 300) -> str:
    """Render free text as a single Markdown table cell.

    Follow-ups and tasks arrive as TinyMCE HTML with newlines; a raw newline
    inside a cell breaks the table for everything below it.
    """
    collapsed = " ".join(strip_html(str(text or "")).split())
    if not collapsed:
        return "—"
    return truncate_field(collapsed, max_len) or "—"


def _duration(seconds) -> str:
    """Render an actiontime (seconds) as a human duration."""
    if seconds in (None, "", 0, "0"):
        return "—"
    try:
        total = int(seconds)
    except (ValueError, TypeError):
        return esc(seconds)
    if total <= 0:
        return "—"
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours}h {minutes}min"
    if hours:
        return f"{hours}h"
    return f"{minutes}min"


def _task_state(code) -> str:
    if code in (None, ""):
        return "—"
    try:
        return _TASK_STATE.get(int(code), f"Estado {code}")
    except (ValueError, TypeError):
        return esc(code)


def _timeline_failure_banner(failed) -> str:
    """Announce the sources that could not be read.

    @MX:NOTE: rendered as a warning ABOVE the entries, never as silence.
    @MX:REASON: a timeline missing its approvals looks exactly like a ticket
    that was never sent for approval. Whoever reads this has to be able to tell
    "nao houve" from "nao consegui ler".
    """
    if not failed or not isinstance(failed, list):
        return ""
    parts = []
    for item in failed:
        if not isinstance(item, dict):
            continue
        source = _TIMELINE_PLURAL.get(item.get("source"), item.get("source", "?"))
        parts.append(f"{source} ({truncate_field(str(item.get('error', '')), 120)})")
    if not parts:
        return ""
    return (
        "\n> AVISO: a timeline esta INCOMPLETA. Nao foi possivel ler: "
        + "; ".join(parts)
        + ".\n"
    )


def _timeline_detail(entry: dict) -> str:
    """Compose the detail cell of a timeline row, per event type."""
    kind = entry.get("kind")
    content = _one_line(entry.get("content"), 400)
    if kind == "task":
        prefix = ""
        duration = _duration(entry.get("actiontime"))
        if duration != "—":
            prefix += f"[duracao prevista: {duration}] "
        assignee = entry.get("assignee")
        if assignee:
            prefix += f"[tecnico: {esc(assignee)}] "
        return f"{prefix}{content}".strip()
    if kind == "validation":
        status = _validation(entry.get("validation_status"))
        answer = _one_line(entry.get("answer"), 200)
        detail = f"[{status}] {content}"
        if answer != "—":
            detail += f" — resposta: {answer}"
        approver = entry.get("approver")
        if approver:
            detail = f"[aprovador: {esc(approver)}] {detail}"
        return detail
    return content


def format_ticket_timeline(data, args: dict) -> str:
    """Format the unified ITIL timeline of a ticket as Markdown."""
    if not isinstance(data, dict):
        return "Timeline nao disponivel."

    entries = data.get("entries") or []
    counts = data.get("counts") or {}
    banner = _timeline_failure_banner(data.get("failed_sources"))
    title = f"# Timeline do chamado #{esc(data.get('ticket_id', 'N/A'))}\n"

    breakdown = ", ".join(
        f"{_TIMELINE_PLURAL.get(kind, kind)}: {value}" for kind, value in counts.items()
    )
    total = data.get("total_entries", len(entries))
    summary = f"\n**{total} evento(s)**" + (f" ({breakdown})" if breakdown else "")
    if data.get("truncated"):
        summary += f" — exibindo os {len(entries)} mais recentes"

    if not entries:
        # @MX:NOTE: an empty timeline WITH failures is not an empty history.
        # @MX:REASON: "Nenhum evento registrado" is a statement of fact about
        # the ticket. Printing it after a read failure is how a reader concludes
        # the ticket was never worked on when the truth is that we could not
        # look.
        tail = (
            "Nenhum evento pode ser exibido. Parte das origens falhou (veja o "
            "aviso acima), entao a ausencia de historico NAO esta confirmada."
            if banner
            else "Nenhum evento registrado neste chamado."
        )
        return f"{title}{banner}{summary}\n\n{tail}"

    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label = _TIMELINE_LABELS.get(entry.get("kind"), entry.get("kind", "?"))
        if entry.get("is_private"):
            label += " (privado)"
        rows.append(
            f"| {fmt_date(entry.get('date'))} "
            f"| {esc(label)} "
            f"| {_actor(entry.get('author'), 60)} "
            f"| {_timeline_detail(entry)} |"
        )
    table = "\n".join(rows)
    return (
        f"{title}{banner}{summary}\n\n"
        f"| Data | Tipo | Autor | Detalhe |\n|---|---|---|---|\n{table}"
    )


def format_ticket_tasks(data, args: dict) -> str:
    """Format the task list (TicketTask) of a ticket."""
    if isinstance(data, dict):
        items = data.get("tasks") or data.get("data") or data.get("items") or []
        ticket_id = data.get("ticket_id")
    elif isinstance(data, list):
        items, ticket_id = data, None
    else:
        items, ticket_id = [], None

    if not items:
        return "Nenhuma tarefa registrada neste chamado."

    rows = []
    for t in items:
        if not isinstance(t, dict):
            continue
        rows.append(
            f"| {esc(t.get('id'))} "
            f"| {fmt_date(t.get('date'))} "
            f"| {_actor(t.get('author'), 40)} "
            f"| {_actor(t.get('assignee'), 40)} "
            f"| {_duration(t.get('actiontime'))} "
            f"| {_task_state(t.get('state'))} "
            f"| {'Privada' if t.get('is_private') else 'Publica'} "
            f"| {_one_line(t.get('content'), 300)} |"
        )
    table = "\n".join(rows)
    header = f"**{len(items)} tarefa(s)**"
    if ticket_id is not None:
        header += f" — chamado #{esc(ticket_id)}"
    return (
        f"{header}\n\n"
        f"| ID | Data | Autor | Tecnico | Duracao | Estado | Visibilidade | Conteudo |\n"
        f"|---|---|---|---|---|---|---|---|\n{table}"
    )


def format_ticket_validations(data, args: dict) -> str:
    """Format the approval list (TicketValidation) of a ticket."""
    if isinstance(data, dict):
        items = data.get("validations") or data.get("data") or data.get("items") or []
        ticket_id = data.get("ticket_id")
    elif isinstance(data, list):
        items, ticket_id = data, None
    else:
        items, ticket_id = [], None

    if not items:
        return "Nenhuma aprovacao registrada neste chamado."

    rows = []
    for v in items:
        if not isinstance(v, dict):
            continue
        rows.append(
            f"| {esc(v.get('id'))} "
            f"| {fmt_date(v.get('date'))} "
            f"| {_actor(v.get('author'), 40)} "
            f"| {_actor(v.get('approver'), 40)} "
            f"| {_validation(v.get('validation_status'))} "
            f"| {fmt_date(v.get('validation_date'))} "
            f"| {_one_line(v.get('content'), 200)} "
            f"| {_one_line(v.get('answer'), 200)} |"
        )
    table = "\n".join(rows)
    header = f"**{len(items)} aprovacao(oes)**"
    if ticket_id is not None:
        header += f" — chamado #{esc(ticket_id)}"
    return (
        f"{header}\n\n"
        f"| ID | Solicitada em | Solicitante | Aprovador | Status | Respondida em | Pedido | Resposta |\n"
        f"|---|---|---|---|---|---|---|---|\n{table}"
    )


# Campos de resultado das escritas ITIL -> rotulo exibido.
_ITIL_RESULT_LABELS = (
    ("ticket_id", "Chamado"),
    ("id", "Registro criado (id)"),
    ("validation_id", "Aprovacao (id)"),
    ("group_id", "Grupo (id)"),
    ("group_name", "Grupo"),
    ("type", "Papel do ator"),
    ("approver_id", "Aprovador (id)"),
    ("status", "Status"),
    ("linked_ticket_id", "Chamado vinculado"),
    ("link_type", "Tipo de vinculo"),
    ("file_name", "Arquivo"),
    ("mime_type", "Tipo MIME"),
    ("size_bytes", "Tamanho (bytes)"),
    ("linked_to_ticket", "Vinculado ao chamado"),
    ("is_private", "Privado"),
    ("warning", "Aviso"),
)


def _itil_result_value(key: str, value) -> str:
    """Render a result field, translating GLPI codes into their labels."""
    if key == "link_type":
        try:
            return _LINK_LABEL.get(int(value), f"Codigo {value}")
        except (ValueError, TypeError):
            return esc(value)
    if key == "type":
        try:
            return _ACTOR_ROLE.get(int(value), f"Codigo {value}")
        except (ValueError, TypeError):
            return esc(value)
    if key == "status":
        return _validation(value)
    if isinstance(value, bool):
        return "Sim" if value else "Nao"
    return esc(value)


def format_itil_operation(data, operation: str) -> str:
    """Format the result of an ITIL write.

    @MX:NOTE: the success/failure decision is delegated to
    format_operation_success; only the detail table is added here.
    @MX:REASON: that function is the single place that knows how to recognise
    an error envelope, an unsupported operation and an explicit success=False.
    Re-deciding it here is how a "sucesso" gets printed over a failed call.
    """
    summary = format_operation_success(data, operation)
    if not isinstance(data, dict) or "realizada com sucesso" not in summary:
        return summary

    rows = []
    for key, label in _ITIL_RESULT_LABELS:
        if key not in data or data[key] in (None, ""):
            continue
        rows.append(f"| {label} | {_itil_result_value(key, data[key])} |")
    if not rows:
        return summary
    table = "\n".join(rows)
    return f"{summary}\n\n| Campo | Valor |\n|---|---|\n{table}"


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


#: Campos do Log cujo valor e um CODIGO do GLPI, e nao um numero.
_TICKET_LOG_ENUMS = {
    "3": fmt_priority,
    "10": fmt_urgency,
    "11": fmt_impact,
    "12": fmt_status,
    "14": fmt_type,
}

#: Campos do Log medidos em SEGUNDOS.
_TICKET_LOG_DURATIONS = ("150", "151", "153", "154")


def _resolve_log_field(h: dict) -> str:
    """Resolve o campo alterado para um rotulo legivel.

    Prefere o texto 'field' (quando o GLPI o expoe), senao mapeia o
    id_search_option, e por fim usa o itemtype vinculado do evento.

    @MX:NOTE: uma entrada do Log sem id_search_option nao e uma entrada vazia.
    @MX:REASON: imprimir "—" na coluna Campo faz o historico parecer corrompido.
    O GLPI usa essas entradas para eventos de vinculo (categoria, item
    associado, ator), e nesses casos itemtype_link diz de que se trata.
    """
    field_text = str(h.get("field", "") or "").strip()
    if field_text:
        return field_text
    code = str(h.get("id_search_option", "") or "").strip()
    if code:
        return _TICKET_LOG_FIELDS.get(code, f"Campo {code}")
    # itemtype_link vem "0" quando nao ha vinculo, e com namespace completo
    # quando ha (Glpi\Form\AnswersSet). "Vinculo (0)" nao informa nada.
    link = str(h.get("itemtype_link", "") or "").strip()
    if link and not link.isdigit():
        return f"Vinculo ({link.rsplit(chr(92), 1)[-1]})"
    return "Evento do chamado"


def _resolve_log_value(h: dict, key: str) -> str:
    """Decodifica o valor de uma entrada do Log conforme o campo alterado.

    @MX:NOTE: `Status | 1 | 2` nao informa nada a quem le.
    @MX:REASON: o historico e o unico lugar do MCP que ainda devolvia codigo
    cru de status/prioridade/urgencia/impacto, e tempo de atendimento em
    segundos. Quem le a tabela precisa ver "Novo -> Atribuido" e "3h 13min",
    nao 1 -> 2 e 11580 — a mesma decodificacao que o detalhe do chamado ja faz.
    """
    raw = str(h.get(key, "") or "").strip()
    if not raw:
        return ""
    code = str(h.get("id_search_option", "") or "").strip()
    if raw.isdigit():
        decoder = _TICKET_LOG_ENUMS.get(code)
        if decoder is not None:
            return decoder(int(raw))
        if code in _TICKET_LOG_DURATIONS:
            # Zero segundos e um valor, nao um dado ausente: o "antes" de um
            # tempo de atendimento e legitimamente 0.
            return _duration(int(raw)) if int(raw) else "0"
    return raw


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
            f"| {truncate_field(_resolve_log_value(h, 'old_value'), 100)} "
            f"| {truncate_field(_resolve_log_value(h, 'new_value'), 100)} "
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


#: Marcas no MODELO do disco que denunciam estado solido. O campo "Disco
#: rigido: Tipo" do GLPI colapsa para um valor so quando a maquina tem dois
#: discos, entao dizia "HDD" numa maquina com HDD + SSD. O modelo nao mente.
_SSD_MARKERS = ("ssd", "nvme", "solid state", "m.2", "mz-", "sa400", "evo", "qvo")


def _disk_kind(names: list) -> str:
    """SSD, HDD or both, inferred from the drive models."""
    joined = " ".join(str(n).lower() for n in names)
    if not joined.strip():
        return ""
    solid = any(marker in joined for marker in _SSD_MARKERS)
    # Sem marcador de SSD, um disco inventariado e um HDD por eliminacao — mas
    # so afirmamos "HDD" quando ha exatamente um disco e ele nao tem marcador.
    if solid and len(names) > 1:
        return "SSD+HDD" if not all(
            any(m in str(n).lower() for m in _SSD_MARKERS) for n in names
        ) else "SSD"
    if solid:
        return "SSD"
    return "HDD"


def _asset_hardware_cells(a: dict) -> str:
    """The Tipo / CPU / RAM / Disco / Uso cells of a computer row."""
    from src.services.asset_service import _as_values, _fmt_mb_label, _first_value, _sum_values

    tipo = _actor(a.get("types_id"), 14)

    cpu = _first_value(a.get("cpu")) or a.get("cpu_info") or ""
    cpu = truncate_field(str(cpu).replace("(R)", "").replace("(TM)", "").strip(), 34) or "—"

    ram_mb = _sum_values(a.get("memory_mb"))
    ram = _fmt_mb_label(ram_mb) if ram_mb else (a.get("memory_info") or "N/A")
    mem_type = _first_value(a.get("memory_type"))
    if ram != "N/A" and mem_type:
        # "DDR4 - 2666 - DIMM" -> "DDR4-2666": o formato do pente nao muda a
        # decisao de ninguem, a velocidade muda.
        parts = [p.strip() for p in str(mem_type).split("-")]
        ram = f"{ram} {'-'.join(parts[:2])}" if len(parts) >= 2 else f"{ram} {parts[0]}"

    names = [n for n in _as_values(a.get("disk_names")) if str(n).strip()]
    disk_mb = _sum_values(a.get("disk_capacity_mb"))
    kind = _disk_kind(names)
    disco = _fmt_mb_label(disk_mb) if disk_mb else "—"
    if disco != "—" and kind:
        disco = f"{disco} {kind}"
    if len(names) > 1:
        disco = f"{disco} ({len(names)} discos)"

    # Uso do MAIOR volume — o volume de sistema é o que interessa; particoes de
    # recuperacao de 1 GB nao dizem nada sobre a maquina estar cheia.
    totals = [_sum_values(v) for v in _as_values(a.get("volume_total_mb"))]
    frees = [_sum_values(v) for v in _as_values(a.get("volume_free_mb"))]
    uso = "—"
    if totals:
        biggest = max(range(len(totals)), key=lambda i: totals[i])
        total_mb = totals[biggest]
        free_mb = frees[biggest] if biggest < len(frees) else 0
        if total_mb > 0:
            used_pct = round((total_mb - free_mb) * 100 / total_mb)
            uso = f"{used_pct}% de {_fmt_mb_label(total_mb)}"

    return f" {tipo} | {cpu} | {ram} | {disco} | {uso} |"


def format_assets_list(data, args: dict) -> str:
    """Format asset list as Markdown table."""
    # @MX:ANCHOR: a chave 'assets' faz parte do contrato desta listagem.
    # @MX:REASON: list_assets devolve uma LISTA quando o resultado cabe na
    # pagina e um dict {'assets': [...], 'pagination': {...}} quando nao cabe.
    # O formatter so conhecia 'data'/'items', entao toda listagem com mais
    # registros que o limite — justamente as grandes — era renderizada como
    # "Nenhum ativo encontrado". O inventario existia e a resposta dizia que
    # nao.
    if isinstance(data, list):
        items = data
    else:
        items = (
            data.get("data")
            or data.get("items")
            or data.get("assets")
            or []
        )
    if not items:
        return "Nenhum ativo encontrado."

    # @MX:WARN: marcadores de corte NAO sao ativos.
    # @MX:REASON: o truncador anexa um item {"truncation_info": ...} ao fim da
    # lista e a busca anexa {"search_hint": ...}. Renderizados como linha, eles
    # viravam um ativo fantasma ("N/A | — | —") e ainda somavam +1 na contagem:
    # 119 computadores apareciam como "6 resultados | Mostrando todos". O aviso
    # que eles carregam ia para o lixo justamente quando era necessario.
    notices = []
    real_items = []
    for item in items:
        # @MX:ANCHOR: toda chave de pseudo-item precisa constar aqui.
        # @MX:REASON: 'smart_search_warning' era inserido na POSICAO 0 da lista
        # de ativos e nao constava — virava a primeira linha da tabela,
        # "N/A |  | N/A | — | — |", e somava +1 no total. O aviso que ele
        # carregava sumia. Um pseudo-item nao reconhecido nao degrada: ele
        # inventa um ativo.
        if isinstance(item, dict) and (
            "truncation_info" in item
            or "search_hint" in item
            or "search_notice" in item
            or "smart_search_warning" in item
        ):
            notices.append(
                item.get("truncation_info")
                or item.get("search_hint")
                or item.get("search_notice")
                or item.get("smart_search_warning")
            )
            if item.get("original_count"):
                notices[-1] = f"{notices[-1]} (total: {item['original_count']})"
            continue
        real_items.append(item)
    items = real_items
    if not items:
        return "Nenhum ativo encontrado."

    total = None
    if isinstance(data, dict):
        # O total vem em 'totalcount' (Search API crua) ou em pagination.total
        # (shape paginado de list_assets); sem ele o cabecalho anuncia a pagina
        # como se fosse o inventario inteiro.
        total = data.get("totalcount") or (data.get("pagination") or {}).get("total")
    if notices:
        # @MX:WARN: com corte, o cabecalho NAO pode falar em lista completa.
        # @MX:REASON: o truncador corta antes do formatter, que entao ve uma
        # lista curta e conclui que acabou — 5 de 119 computadores saiam
        # anunciados como "Mostrando todos". O corte precisa aparecer no
        # cabecalho, nao so numa nota que o modelo pode ignorar.
        header = (
            f"**{len(items)} resultados** | LISTA TRUNCADA — ha mais registros\n\n"
            f"> {' | '.join(str(n) for n in notices)}"
        )
    else:
        header = page_info(len(items), args.get("limit", 10), args.get("offset", 0), total)
    # @MX:ANCHOR: computador lista hardware; os demais tipos nao.
    # @MX:REASON: "liste os computadores do fulano" e sempre seguido de "quanto
    # de RAM, que disco, e notebook?", e responder isso exigia outra tool por
    # ativo. Esses dados chegam de graca na mesma consulta (colunas do proprio
    # Computer), entao ficam na tabela. Monitor e impressora nao tem nenhuma
    # dessas colunas — colunas vazias so gastariam contexto.
    is_computer = any(
        str(a.get("asset_type") or "") == "Computer" for a in items
    )
    hw_head = " Tipo | CPU | RAM | Disco | Uso |" if is_computer else ""
    hw_sep = "---|---|---|---|---|" if is_computer else ""

    rows = []
    for a in items:
        hw_cells = _asset_hardware_cells(a) if is_computer else ""
        rows.append(
            f"| {glpi_id_link(a.get('asset_type', 'Computer'), a.get('id'))} "
            f"| {truncate_field(a.get('name', ''), 40)} "
            f"| {esc(a.get('serial', 'N/A'))} "
            # @MX:WARN: aceitar as duas chaves de situacao do ativo.
            # @MX:REASON: a listagem grava 'states_id' e a busca textual grava
            # 'status' — ler so uma delas deixava a coluna Situacao vazia em
            # todo o caminho de busca, embora o dado tivesse vindo do GLPI.
            # Mesma classe de defeito de "pedir uma coluna e ler outra".
            f"| {_actor(a.get('states_id') if a.get('states_id') is not None else a.get('status'), 18)} "
            f"| {_actor(a.get('locations_id'), 22)} "
            f"| {_actor(a.get('manufacturers_id'), 18)} "
            f"| {_actor(a.get('models_id'), 20)} "
            f"| {_actor(a.get('users_id'), 20)} |{hw_cells}"
        )
    table = "\n".join(rows)
    return (
        f"{header}\n\n"
        f"| ID | Nome | Serial | Status | Localizacao | Fabricante | Modelo | Usuario |{hw_head}\n"
        f"|---|---|---|---|---|---|---|---|{hw_sep}\n{table}"
    )


def _fmt_mb(megabytes) -> str:
    """Render a GLPI size (always MB) in the unit a person would say it in."""
    try:
        value = int(megabytes or 0)
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    if value >= 1_048_576:
        return f"{value / 1_048_576:.1f} TB".replace(".0 ", " ")
    if value >= 1024:
        return f"{value / 1024:.1f} GB".replace(".0 ", " ")
    return f"{value} MB"


def _blank_to_dash(value) -> str:
    """An em dash where GLPI stored nothing, so an empty cell is never mistaken
    for a value the inventory actually recorded."""
    return "—" if _is_blank(value) else str(value)


def _is_blank(value) -> bool:
    """True when a GLPI value carries nothing, in any of its empty spellings.

    @MX:NOTE: "[]" chega como STRING, nao como lista.
    @MX:REASON: um ativo sem grupo devolvia a string literal "[]" e a celula
    "Grupo" exibia "[]" -- um par de colchetes onde deveria haver um nome le-se
    como dado corrompido, nao como ausencia.
    """
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    if isinstance(value, str) and value.strip() in ("", "[]", "{}", "0", "null", "None"):
        return True
    return value in (None, 0)


def _asset_suffix_field(data: dict, suffix: str) -> str:
    """Resolve a column GLPI names per asset type.

    @MX:NOTE: o modelo de um Computer e `computermodels_id`, o de um Monitor e
    `monitormodels_id` -- nao existe `models_id`.
    @MX:REASON: o detalhe pedia `models_id` e mostrava "Modelo: N/A" enquanto a
    LISTA do mesmo ativo mostrava "OptiPlex 5060", porque a busca le o campo 40
    e o GET le a coluna. Duas telas do mesmo registro discordando e pior que
    faltar o dado nas duas: sugere que o cadastro esta incompleto.
    """
    for key, value in data.items():
        if key.endswith(f"{suffix}_name") and not _is_blank(value):
            return esc(value)
    # Sem nome resolvido nao se exibe o id cru: "Modelo: 3" afirma um modelo.
    return "N/A"


def _asset_field(data: dict, id_key: str, name_key: str) -> str:
    """Prefere o nome resolvido (*_name); senao mostra o id; 0/vazio -> N/A.

    @MX:NOTE: o get de ativo exibia codigos crus (Status: 0, Localizacao: 0).
    asset_service.get_asset enriquece com *_name via dropdown_cache; aqui
    consumimos esse nome quando disponivel.
    """
    name = data.get(name_key)
    if not _is_blank(name):
        return esc(name)
    raw = data.get(id_key)
    if _is_blank(raw):
        return "N/A"
    return esc(raw)


def format_asset_detail(data: dict) -> str:
    """Format asset details as field-value Markdown table."""
    if not data:
        return "Ativo nao encontrado."
    deleted = str(data.get("is_deleted", 0)) in ("1", "True")
    trash_banner = "\n> ⚠️ Este ativo está NA LIXEIRA do GLPI (excluído / is_deleted=1).\n" if deleted else ""
    trash_row = "| Na lixeira | Sim (is_deleted=1) |\n" if deleted else ""

    # @MX:WARN: linhas so aparecem quando ha valor.
    # @MX:REASON: o sistema operacional do GLPI nao e coluna do ativo, e sim um
    # sub-item (Item_OperatingSystem) que so a acao `get_details` busca. Uma
    # linha fixa "Sistema operacional: N/A" afirma que a maquina nao tem SO,
    # quando o que houve foi nao termos perguntado — e a mesma maquina responde
    # o SO por outro caminho. Ausencia de dado nao e o mesmo que ausencia de
    # campo.
    optional_rows = ""
    for label, key in (
        ("Endereco IP", "ip_addresses"),
        ("Sistema operacional", "operatingsystems_name"),
        ("Versao do SO", "operatingsystemversions_name"),
        ("Dominio", "domains_name"),
        ("Contato", "contact"),
        ("Telefone do contato", "contact_num"),
    ):
        value = data.get(key)
        if not _is_blank(value):
            optional_rows += f"| {label} | {esc(value)} |\n"

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
        f"| Modelo | {_asset_suffix_field(data, 'models')} |\n"
        f"| Usuario | {_asset_field(data, 'users_id', 'users_name')} |\n"
        f"| Grupo | {_asset_field(data, 'groups_id', 'groups_name')} |\n"
        # @MX:WARN: estes campos JA vinham na resposta e eram descartados.
        # @MX:REASON: o forcedisplay de get_asset pede sistema operacional,
        # contato, dominio, ultimo inventario e ultimo boot; o formatter parava
        # no comentario e jogava fora o resto. "Essa maquina ainda esta viva?
        # quando ela apareceu pela ultima vez?" e a pergunta de monitoramento
        # mais comum de um MSP, e a resposta ja estava em maos, sem custo de
        # round-trip adicional.
        f"{optional_rows}"
        f"| Ultimo inventario | {fmt_date(data.get('last_inventory_update')) if data.get('last_inventory_update') else 'N/A'} |\n"
        f"| Ultimo boot | {fmt_date(data.get('last_boot')) if data.get('last_boot') else 'N/A'} |\n"
        f"| Criado | {fmt_date(data.get('date_creation')) if data.get('date_creation') else 'N/A'} |\n"
        f"| Atualizado | {fmt_date(data.get('date_mod')) if data.get('date_mod') else 'N/A'} |\n"
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
    notice = data.get("search_notice") if isinstance(data, dict) else None
    if not items:
        empty = "Nenhum usuario encontrado."
        return f"{empty}\n\n_{notice}_" if notice else empty
    total = data.get("totalcount") if isinstance(data, dict) else None
    header = page_info(len(items), args.get("limit", 10), args.get("offset", 0), total)
    if notice:
        header = f"{header}\n\n_{notice}_"
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
    # @MX:NOTE: grupos, perfis e entidades saem por NOME, nao por contagem.
    # @MX:REASON: `| Grupos | 8 |` era o total de vinculos, e todo leitor —
    # humano ou modelo — le isso como "grupo 8". Perfil e entidade nem
    # apareciam, apesar de ja terem sido buscados no GLPI.
    def _named(key: str) -> str:
        names = data.get(f"{key}_names")
        if isinstance(names, list) and names:
            shown = [esc(n) for n in names[:8]]
            suffix = f" (+{len(names) - 8})" if len(names) > 8 else ""
            return ", ".join(shown) + suffix
        return "—"

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
        f"| Grupos | {_named('groups')} |\n"
        f"| Perfis (direitos no GLPI) | {_named('profiles')} |\n"
        f"| Entidades com acesso | {_named('entities')} |\n"
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
    notice = data.get("search_notice") if isinstance(data, dict) else None
    if not items:
        q = (args or {}).get("query", "")
        empty = f"Nenhum artigo encontrado na base de conhecimento{(' para: ' + q) if q else ''}."
        return f"{empty}\n\n_{notice}_" if notice else empty
    total = data.get("total", len(items)) if isinstance(data, dict) else len(items)
    rows = []
    # @MX:NOTE: the answer excerpt is a column, not a detail-only field.
    # @MX:REASON: title plus category cannot separate two articles from the same
    # category, and the caller would have to open each one to find out -- the
    # excerpt is what the search was asked to surface.
    for a in items:
        rows.append(
            f"| {glpi_id_link('KnowbaseItem', a.get('id'))} "
            f"| {truncate_field(a.get('name', ''), 80)} "
            f"| {esc(a.get('category', 'N/A'))} "
            f"| {truncate_field(a.get('answer', ''), 220)} "
            f"| {esc(a.get('views', 0))} |"
        )
    table = "\n".join(rows)
    header = f"**{len(items)} artigo(s) encontrado(s)** (total: {total})"
    if notice:
        header = f"{header}\n\n_{notice}_"
    return (
        f"{header}\n\n"
        f"| ID | Titulo | Categoria | Trecho da resposta | Visualizacoes |\n"
        f"|---|---|---|---|---|\n{table}"
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

    # @MX:ANCHOR: esta tela responde a um chamado, nao cataloga um registro.
    # @MX:REASON: a versao anterior imprimia "CPU ID 109", "Mem ID 98" e uma
    # coluna de software vazia — os ids internos das tabelas de dispositivo do
    # GLPI. Um analista atendendo alguem precisa saber o modelo do processador,
    # se a memoria e DDR3 ou DDR4 e em que formato, quanto sobra no disco e se o
    # antivirus esta atualizado. Nada disso exigia chamada nova: faltava
    # `expand_dropdowns` na coleta e uma leitura util na renderizacao.

    os_items = data.get("operating_systems") or []
    if os_items:
        rows = []
        for it in os_items:
            version = _blank_to_dash(it.get("operatingsystemversions_id"))
            arch = _blank_to_dash(it.get("operatingsystemarchitectures_id"))
            kernel = _blank_to_dash(it.get("operatingsystemkernelversions_id"))
            rows.append(
                f"| {esc(it.get('operatingsystems_id'))} | {esc(version)} "
                f"| {esc(arch)} | {esc(kernel)} |"
            )
        parts.append(
            "\n\n## Sistema operacional\n\n"
            "| SO | Versao | Arquitetura | Build/Kernel |\n|---|---|---|---|\n"
            + "\n".join(rows)
        )

    hardware = []
    for it in data.get("processors") or []:
        cores = it.get("nbcores")
        threads = it.get("nbthreads")
        freq = it.get("frequency")
        spec = esc(it.get("deviceprocessors_id") or "Desconhecido")
        detail = []
        if cores:
            detail.append(f"{cores} nucleo(s)")
        if threads:
            detail.append(f"{threads} thread(s)/nucleo")
        if freq:
            detail.append(f"{freq} MHz")
        hardware.append(("Processador", spec + (f" — {', '.join(detail)}" if detail else "")))

    memories = data.get("memories") or []
    if memories:
        total_mb = sum(int(m.get("size") or 0) for m in memories)
        # O nome do dispositivo ja traz "DDR4 - 2666 - DIMM": tipo, frequencia e
        # formato numa string so, que e exatamente o que se pergunta antes de
        # comprar um pente.
        modules = []
        for m in memories:
            size = int(m.get("size") or 0)
            kind = _blank_to_dash(m.get("devicememories_id"))
            slot = m.get("busID")
            label = f"{_fmt_mb(size)} {kind}" if kind != "—" else _fmt_mb(size)
            if slot:
                label += f" (slot {esc(slot)})"
            modules.append(label)
        hardware.append(
            (
                "Memoria",
                f"{_fmt_mb(total_mb)} em {len(memories)} modulo(s): "
                + "; ".join(modules),
            )
        )

    for it in data.get("drives") or []:
        capacity = int(it.get("capacity") or 0)
        model = esc(it.get("deviceharddrives_id") or "Desconhecido")
        bits = [_fmt_mb(capacity)] if capacity else []
        # @MX:NOTE: tipo (SSD/HDD) e RPM sao campos do GLPI que o agente de
        # inventario pode nao preencher; quando vazios, NAO se deduz do nome do
        # modelo. "SSD" inferido de uma string e um palpite com cara de dado.
        for key, prefix in (("interfacetypes_id", ""), ("rpm", "RPM ")):
            value = it.get(key)
            if value not in (None, "", 0, "0", "None"):
                bits.append(f"{prefix}{esc(value)}")
        hardware.append(("Disco fisico", model + (f" — {', '.join(bits)}" if bits else "")))

    for it in data.get("graphics") or []:
        memory = int(it.get("memory") or 0)
        spec = esc(it.get("devicegraphiccards_id") or "Desconhecido")
        hardware.append(("Video", spec + (f" — {_fmt_mb(memory)}" if memory else "")))

    for it in data.get("batteries") or []:
        spec = esc(it.get("devicebatteries_id") or "Desconhecido")
        capacity = it.get("real_capacity") or it.get("capacity")
        hardware.append(("Bateria", spec + (f" — {esc(capacity)} mWh" if capacity else "")))

    for it in data.get("firmwares") or []:
        version = it.get("devicefirmwares_id")
        hardware.append(("BIOS/Firmware", esc(version or "Desconhecido")))

    if hardware:
        rows = "\n".join(f"| {label} | {value} |" for label, value in hardware)
        parts.append(
            "\n\n## Hardware\n\n| Componente | Especificacao |\n|---|---|\n" + rows
        )

    # Volumes logicos: o espaco livre e a resposta do chamado "esta lento" /
    # "nao consigo salvar". Volumes de 0 byte sao particoes de recuperacao sem
    # leitura e nao dizem nada ao analista.
    volumes = [
        d for d in (data.get("disks") or [])
        if int(d.get("totalsize") or 0) > 0
    ]
    if volumes:
        rows = []
        for d in sorted(volumes, key=lambda x: int(x.get("totalsize") or 0), reverse=True):
            total = int(d.get("totalsize") or 0)
            free = int(d.get("freesize") or 0)
            pct_used = round((total - free) * 100 / total) if total else 0
            flag = " ⚠️" if pct_used >= 90 else ""
            name = d.get("mountpoint") or d.get("name") or "—"
            rows.append(
                f"| {esc(name)} | {esc(_blank_to_dash(d.get('filesystems_id')))} "
                f"| {_fmt_mb(total)} | {_fmt_mb(free)} | {pct_used}%{flag} |"
            )
        parts.append(
            "\n\n## Armazenamento\n\n"
            "| Volume | Sistema | Total | Livre | Uso |\n|---|---|---|---|---|\n"
            + "\n".join(rows)
        )

    networks = data.get("networks") or []
    if networks:
        rows = []
        for n in networks:
            speed = n.get("ifspeed")
            speed_txt = f"{int(speed) // 1000000} Mbps" if speed else "—"
            rows.append(
                f"| {esc(n.get('name') or '—')} | {esc(n.get('mac') or '—')} "
                f"| {esc(_blank_to_dash(n.get('instantiation_type')))} | {speed_txt} |"
            )
        parts.append(
            "\n\n## Rede\n\n| Interface | MAC | Tipo | Velocidade |\n|---|---|---|---|\n"
            + "\n".join(rows)
        )

    # Antivirus: "esta protegido e atualizado" e pergunta de triagem, e a
    # resposta e um booleano que o GLPI ja guarda.
    antivirus = data.get("antivirus") or []
    if antivirus:
        rows = []
        for a in antivirus:
            active = "Sim" if str(a.get("is_active")) in ("1", "True") else "Nao"
            uptodate = "Sim" if str(a.get("is_uptodate")) in ("1", "True") else "Nao"
            flag = "" if uptodate == "Sim" else " ⚠️"
            rows.append(
                f"| {esc(a.get('name') or '—')} | {esc(_blank_to_dash(a.get('antivirus_version')))} "
                f"| {esc(_blank_to_dash(a.get('signature_version')))} | {active} | {uptodate}{flag} |"
            )
        parts.append(
            "\n\n## Seguranca\n\n"
            "| Antivirus | Versao | Assinatura | Ativo | Atualizado |\n|---|---|---|---|---|\n"
            + "\n".join(rows)
        )

    # Garantia / compra: decide se o conserto e por contrato ou por conta da
    # empresa, e essa e a primeira pergunta quando o hardware falha.
    infocom = data.get("infocom") or []
    if infocom:
        rows = []
        for i in infocom:
            rows.append(
                f"| {esc(_blank_to_dash(i.get('buy_date')))} "
                f"| {esc(_blank_to_dash(i.get('warranty_date')))} "
                f"| {esc(i.get('warranty_duration') or '—')} "
                f"| {esc(_blank_to_dash(i.get('suppliers_id')))} |"
            )
        parts.append(
            "\n\n## Aquisicao e garantia\n\n"
            "| Compra | Inicio da garantia | Duracao (meses) | Fornecedor |\n"
            "|---|---|---|---|\n" + "\n".join(rows)
        )

    software = data.get("software") or []
    if software:
        rows = []
        for s in software[:25]:
            name = _blank_to_dash(s.get("softwares_id"))
            version = _blank_to_dash(s.get("softwareversions_id"))
            rows.append(
                f"| {esc(name)} | {esc(version)} "
                f"| {esc(_blank_to_dash(s.get('date_install')))} |"
            )
        more = f" — exibindo 25 de {len(software)}" if len(software) > 25 else ""
        parts.append(
            f"\n\n## Software instalado ({len(software)}){more}\n\n"
            "| Software | Versao | Instalado em |\n|---|---|---|\n" + "\n".join(rows)
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
