"""
MCP Handlers - Conforme SPEC.md seção 4.2
Integração das 48 tools MCP em handlers centralizados
Roteamento JSON-RPC 2.0 para execução das tools
"""

from typing import Dict, Any, List, Optional, Tuple
import hashlib
import json
import re
from datetime import datetime

# SPEC-GLPI-ENHANCE-001/F04: Consolidated tools
from src.tools.consolidated_tickets import search_tickets, manage_tickets, manage_ai_analysis
from src.tools.consolidated_itil import search_itil_records, manage_itil_records
from src.tools.consolidated_search import search_records
from src.tools.consolidated_assets import search_assets, manage_assets
from src.tools.consolidated_admin import search_admin, manage_admin
from src.tools.consolidated_webhooks import search_webhooks, manage_webhooks
from src.tools.bridge_tools import bridge_tools
from src.services.kb_search.handler import search_knowledge_unified as kb_search_unified
from src.models.exceptions import (
    GLPIError,
    NotFoundError,
    ValidationError,
    SimilarityError,
    MethodNotFoundError,
    InvalidRequestError,
    HTTP_TO_JSONRPC,
)
from src import __version__
from src.config.settings import settings
from src.utils.helpers import logger
from src.formatters.response_formatter import format_tool_response
from src.security.idempotency import get_idempotency_store
from src.security.write_policy import get_write_policy, resolve_operation


# Names that mean the same parameter across sibling tools.
#
# @MX:ANCHOR: every tool answers to every spelling in these groups.
# @MX:REASON: four sibling search tools each named the "what am I searching"
# parameter differently -- `record_type` (ITIL), `resource` (admin),
# `asset_type` (assets), `itemtype` (free criteria). A caller that learns one
# from a successful call sends it to the next tool and gets
# `search_admin() got an unexpected keyword argument 'record_type'` -- a
# TypeError surfaced as a tool failure, which reads as "the GLPI service is
# down" rather than "you spelled the parameter differently". Measured: that is
# exactly the failure this cost us.
#
# `name` is deliberately absent from the free-text group: on the manage_* tools
# it is the record's own name, a value being written, not a search term.
_ARGUMENT_ALIASES: Tuple[frozenset, ...] = (
    frozenset({"record_type", "resource", "asset_type", "itemtype", "item_type"}),
    frozenset({"query", "search", "search_text", "text", "q"}),
    frozenset({"limit", "max_results", "page_size"}),
    frozenset({"confirmation_token", "confirmationToken"}),
)


_UNEXPECTED_KWARG = re.compile(r"unexpected keyword argument '([^']+)'")


def tool_error_result(text: str) -> Dict[str, Any]:
    """Result of a tool that ran and failed: MCP ``isError`` with readable text."""
    return {"content": [{"type": "text", "text": text}], "isError": True}


def describe_failure(exc: GLPIError) -> str:
    """Error text an agent can act on: says WHICH item or parameter failed.

    ``NotFoundError`` only carries "Ticket not found" in its message; the id lives in
    ``details``. Without it the agent cannot tell which of several calls failed.
    """
    msg = exc.message
    details = exc.details or {}
    ident = details.get("identifier")
    if ident and str(ident) not in msg:
        resource = details.get("resource")
        msg = f"{msg}: {resource} {ident}" if resource else f"{msg}: {ident}"
    field = details.get("field")
    if field and field not in msg:
        msg = f"{msg} (parametro '{field}')"
    return msg


def _normalize_argument_aliases(
    tool_name: str,
    arguments: Dict[str, Any],
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Rename argument synonyms to the name this tool actually declares.

    The canonical name is read from the tool's own schema rather than a table,
    so a tool that renames a parameter keeps working without anyone maintaining
    a second list. A group is only applied when the tool declares exactly one of
    its names -- otherwise the caller's spelling is already unambiguous, or the
    rename would have to guess between two real parameters.
    """
    if not isinstance(arguments, dict) or not arguments:
        return arguments

    properties = (schema or {}).get("properties") or {}
    if not properties:
        return arguments

    normalized = dict(arguments)
    for group in _ARGUMENT_ALIASES:
        declared = [name for name in properties if name in group]
        if len(declared) != 1:
            continue
        canonical = declared[0]
        if canonical in normalized:
            continue
        for supplied in list(normalized):
            if supplied in group and supplied != canonical:
                normalized[canonical] = normalized.pop(supplied)
                logger.info(
                    f"{tool_name}: argumento '{supplied}' interpretado como "
                    f"'{canonical}'"
                )
                break

    return normalized


class MCPHandler:
    """
    Handler principal para protocolo MCP (Model Context Protocol).
    Implementa JSON-RPC 2.0 conforme SPEC.md
    """

    def __init__(self):
        """Inicializa handler MCP."""
        self.tools = self._register_tools()

        logger.info(f"MCPHandler initialized with {len(self.tools)} tools")

    def _register_tools(self) -> Dict[str, Any]:
        """
        SPEC-GLPI-ENHANCE-001/F04: registra as tools consolidadas com annotations.
        CONSOLIDATED_TOOLS abaixo e a unica fonte da lista (a contagem real vai no
        log "Registered N consolidated MCP tools"); a tool de analise IA so entra
        com ENABLE_AI_ANALYSIS=true.
        """
        tools = {}

        # SPEC-GLPI-ENHANCE-001/F03+F04 + DIRETRIZES-OBRIGATORIAS-MCP-TOOLS-NOMENCLATURA
        # Names: 30-48 chars, {MCP_ID}_{verb}_{resource}, English
        # Descriptions: pt-BR, 250-400 chars, [SUBSTANTIVO-CHAVE]+[QUANDO]+[RETORNO], GLPI 2x, 2-4 synonyms
        CONSOLIDATED_TOOLS = [
            # === TICKETS (3 tools) ===
            {
                "name": "glpi_search_helpdesk_tickets",  # 28 chars
                "description": (
                    "Chamados, tickets, incidentes, requisicoes e solicitacoes de helpdesk no GLPI — listagem e busca textual "
                    "com filtros por status, prioridade, urgencia, tecnico atribuido, grupo atribuido, solicitante, categoria "
                    "e periodo. Use para 'chamados de hoje', 'tickets abertos', 'chamados do grupo Infraestrutura', 'chamados "
                    "atribuidos ao Joao', 'urgentes da categoria Rede'. Aceita ordenacao via sort_by/order. IMPORTANTE: o token "
                    "MCP ja fixa o cliente/tenant no GLPI, NAO preencha entity_id nem entity_name (so use para sub-entidade). "
                    "Sem parametros, retorna os 10 chamados mais recentes. Retorna tabela Markdown paginada. Somente leitura."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Status do chamado no GLPI. Valores: new (novo), assigned (atribuido), planned (planejado), pending (pendente), solved (solucionado), closed (fechado). Para 'chamados abertos' use new OU omita para pegar todos os estados.", "enum": ["new", "assigned", "planned", "pending", "solved", "closed"]},
                        "priority": {"type": "integer", "description": "Prioridade do chamado. Valores: 1 (muito baixa), 2 (baixa), 3 (media), 4 (alta), 5 (muito alta), 6 (maior)", "minimum": 1, "maximum": 6},
                        "query": {"type": "string", "description": "Texto para busca em titulo e conteudo (minimo 2 caracteres). Omita para listagem sem busca textual."},
                        "date_after": {"type": "string", "description": "Data de criacao a partir de. Aceita YYYY-MM-DD, DD/MM/YYYY, ISO com hora, ou palavras 'hoje'/'today'/'ontem'/'yesterday'/'amanha'/'tomorrow'. Para 'chamados de hoje' use 'hoje' (ou a data atual) em date_after E date_before."},
                        "date_before": {"type": "string", "description": "Data de criacao ate. Aceita YYYY-MM-DD, DD/MM/YYYY, ISO com hora, ou palavras 'hoje'/'today'/'ontem'/'yesterday'/'amanha'/'tomorrow'. Para 'chamados de hoje' use 'hoje' em date_after E date_before."},
                        "urgency": {"type": "integer", "description": "Urgencia do chamado no GLPI — eixo DISTINTO de prioridade (no GLPI a prioridade e derivada de urgencia + impacto). Valores: 1 (muito baixa) a 5 (muito alta). Use para 'chamados urgentes'.", "minimum": 1, "maximum": 5},
                        "assigned_tech": {"type": "string", "description": "Tecnico atribuido ao chamado no GLPI. Aceita o NOME (busca parcial, ex: 'Joao') ou o ID numerico do usuario. Use para 'chamados do fulano', 'o que esta atribuido ao X'."},
                        "assigned_group": {"type": "string", "description": "Grupo tecnico atribuido ao chamado no GLPI. Aceita o NOME (busca parcial, ex: 'Infraestrutura') ou o ID numerico do grupo. Use para 'chamados do time X', 'fila do grupo Y'."},
                        "requester": {"type": "string", "description": "Solicitante que abriu o chamado no GLPI. Aceita o NOME (busca parcial) ou o ID numerico do usuario. Use para 'chamados abertos pelo fulano'."},
                        "category": {"type": "string", "description": "Categoria ITIL do chamado no GLPI. Aceita o NOME (busca parcial, ex: 'Rede') ou o ID numerico da categoria."},
                        "open_only": {"type": "boolean", "description": "Se true, retorna apenas chamados em aberto (exclui solucionados e fechados). Ignorado quando status e informado, pois status e mais especifico.", "default": False},
                        "sort_by": {"type": "string", "description": "Campo de ordenacao no GLPI. Padrao: date_mod (ultima atualizacao). Use date para ordenar por abertura ('chamados mais antigos primeiro' = sort_by=date + order=asc).", "enum": ["date", "date_mod", "priority", "urgency", "status", "name", "category", "solvedate", "closedate"]},
                        "order": {"type": "string", "description": "Direcao da ordenacao. asc (crescente, mais antigos/menores primeiro) ou desc (decrescente, padrao).", "enum": ["asc", "desc"], "default": "desc"},
                        "entity_id": {"type": "integer", "description": "OPCIONAL — Token ja fixa tenant. So preencha para filtrar UMA sub-entidade especifica dentro do cliente. ID numerico da entidade no GLPI."},
                        "entity_name": {"type": "string", "description": "OPCIONAL — Token ja fixa tenant. So preencha para filtrar UMA sub-entidade pelo nome (ex: nome de uma filial). Nao use o nome do cliente principal."},
                        "limit": {"type": "integer", "description": "Quantidade maxima de resultados (padrao: 10, maximo: 50)", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "description": "Deslocamento para paginacao (padrao: 0)", "minimum": 0, "default": 0},
                    },
                },
                "handler": search_tickets,
                "category": "tickets",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_ticket_operations",  # 33 chars
                "description": (
                    "Chamados, tickets, incidentes e requisicoes no GLPI — operacoes sobre UM chamado: abertura, consulta, "
                    "atualizacao, atribuicao a tecnico ou a grupo, resolucao, fechamento, comentarios, tarefas, aprovacoes, "
                    "anexos, vinculo entre chamados e linha do tempo completa. Use action no GLPI: get, get_by_number, create, "
                    "update, delete, assign, assign_group, close, resolve, add_followup, add_task, add_document, link_tickets, "
                    "request_validation, answer_validation, get_timeline, get_tasks, get_validations, get_followups, "
                    "get_history, get_stats, find_similar. Para LISTAR use glpi_search_helpdesk_tickets. Retorna Markdown."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Operacao a executar no GLPI. Consulta: get (detalhe), get_by_number (por numero), get_followups (comentarios), get_history (auditoria), get_stats (estatisticas), get_timeline (linha do tempo completa: comentarios + tarefas + solucoes + aprovacoes), get_tasks (tarefas), get_validations (aprovacoes), find_similar (chamados parecidos). Escrita: create, update, delete, assign (tecnico), assign_group (grupo/equipe), close, resolve, add_followup (comentar), add_task (tarefa), add_document (anexar arquivo), link_tickets (vincular chamados), request_validation (pedir aprovacao), answer_validation (aprovar ou recusar).", "enum": ["get", "get_by_number", "create", "update", "delete", "assign", "assign_group", "close", "resolve", "add_followup", "get_followups", "get_history", "get_stats", "find_similar", "get_timeline", "add_task", "get_tasks", "request_validation", "answer_validation", "get_validations", "link_tickets", "add_document"]},
                        "ticket_id": {"type": "integer", "description": "ID do chamado no GLPI (obrigatorio para get, update, delete, assign, close, resolve, add_followup, get_followups, get_history)"},
                        "title": {"type": "string", "description": "Titulo do chamado (obrigatorio para create)"},
                        "description": {"type": "string", "description": "Descricao detalhada do problema (obrigatorio para create). Formatacao: o GLPI guarda este campo como HTML — use <br>, <p>, <strong>, <ul><li> para formatar. Markdown (**negrito**) NAO e interpretado e aparece literal. Aspas, & e acentos podem ser escritos normalmente."},
                        "content": {"type": "string", "description": "Conteudo do acompanhamento (obrigatorio para add_followup). Formatacao: o GLPI guarda este campo como HTML — use <br>, <p>, <strong>, <ul><li> para formatar. Markdown (**negrito**) NAO e interpretado e aparece literal. Aspas, & e acentos podem ser escritos normalmente."},
                        "status": {"type": "string", "description": "Novo status. Valores: new (novo), assigned (atribuido), planned (planejado), pending (pendente), solved (solucionado), closed (fechado)", "enum": ["new", "assigned", "planned", "pending", "solved", "closed"]},
                        "priority": {"type": "integer", "description": "Prioridade. Valores: 1 (muito baixa) a 5 (muito alta), 6 (maior)", "minimum": 1, "maximum": 6},
                        "entity_id": {"type": "integer", "description": "OPCIONAL — Token ja fixa tenant. So preencha em create/get_stats para sub-entidade especifica. ID numerico no GLPI."},
                        "entity_name": {"type": "string", "description": "OPCIONAL — Token ja fixa tenant. So preencha em create/get_stats para sub-entidade especifica (resolvido automaticamente)."},
                        "user_id": {"type": "integer", "description": "ID do tecnico para atribuicao (obrigatorio para assign)"},
                        "solution": {"type": "string", "description": "Texto da solucao tecnica (obrigatorio para resolve e close). Formatacao: o GLPI guarda este campo como HTML — use <br>, <p>, <strong>, <ul><li> para formatar. Markdown (**negrito**) NAO e interpretado e aparece literal. Aspas, & e acentos podem ser escritos normalmente."},
                        "urgency": {"type": "integer", "description": "Urgencia do chamado (create e update): 1 (muito baixa) a 5 (muito alta). Padrao no create: 3. Eixo distinto de priority.", "minimum": 1, "maximum": 5},
                        "type": {"type": "string", "description": "Tipo do chamado (apenas create). Valores: incident (incidente, padrao), request (requisicao).", "enum": ["incident", "request"]},
                        "category_id": {"type": "integer", "description": "ID da categoria ITIL do chamado (create e update)."},
                        "requester_id": {"type": "integer", "description": "ID do usuario solicitante (apenas create). Para o nome, use glpi_search_admin_resources."},
                        "assignee_id": {"type": "integer", "description": "ID do tecnico atribuido (create e update). Depois da abertura, action=assign tambem atribui."},
                        "location_id": {"type": "integer", "description": "ID da localizacao do chamado (apenas create)."},
                        "resolution": {"type": "string", "description": "Alias legado de solution, so em close. Prefira solution; se os dois vierem, resolution vence."},
                        "solution_type": {"type": "integer", "description": "ID do tipo de solucao no GLPI, so em close (padrao: 5).", "default": 5},
                        "ticket_number": {"type": "string", "description": "Numero do chamado como string (para get_by_number)"},
                        "threshold": {"type": "number", "description": "Limite de similaridade 0.0-1.0 para find_similar. Padrao: 0.3", "minimum": 0, "maximum": 1, "default": 0.3},
                        "max_results": {"type": "integer", "description": "Numero maximo de tickets similares retornados para find_similar. Padrao: 10", "minimum": 1, "maximum": 50, "default": 10},
                        "date_from": {"type": "string", "description": "Data inicial para get_stats. Aceita YYYY-MM-DD, DD/MM/YYYY ou palavras 'hoje'/'ontem'/'amanha'."},
                        "date_to": {"type": "string", "description": "Data final para get_stats. Aceita YYYY-MM-DD, DD/MM/YYYY ou palavras 'hoje'/'ontem'/'amanha'."},
                        "is_private": {"type": "boolean", "description": "Se true, o acompanhamento ou a tarefa fica visivel apenas para tecnicos, nao para o solicitante. Padrao: false", "default": False},
                        "actiontime": {"type": "integer", "description": "Duracao prevista da tarefa em SEGUNDOS (para add_task). Ex: 3600 = 1 hora, 1800 = 30 minutos.", "minimum": 0},
                        "task_category_id": {"type": "integer", "description": "ID da categoria da tarefa no GLPI (opcional em add_task)."},
                        "approver": {"type": "string", "description": "Aprovador da validacao (obrigatorio em request_validation). Aceita NOME/login do usuario ou o ID numerico. Nome ambiguo e recusado com a lista de candidatos."},
                        "validation_id": {"type": "integer", "description": "ID da aprovacao no GLPI (para answer_validation). Se omitido e houver apenas UMA aprovacao pendente no chamado, ela e resolvida automaticamente."},
                        "validation_status": {"type": "string", "description": "Resposta da aprovacao (obrigatorio em answer_validation). Valores: aprovado ou recusado. Ao recusar, o campo comment e obrigatorio.", "enum": ["aprovado", "recusado"]},
                        "comment": {"type": "string", "description": "Comentario da aprovacao. Obrigatorio ao recusar uma validacao."},
                        "group": {"type": "string", "description": "Grupo/equipe a atribuir ao chamado (obrigatorio em assign_group). Aceita NOME (ex: 'Infraestrutura') ou ID numerico. Nome ambiguo e recusado com a lista de candidatos."},
                        "group_type": {"type": "string", "description": "Papel do grupo no chamado do GLPI. Valores: assigned (atribuido, padrao), requester (solicitante), observer (observador).", "enum": ["assigned", "requester", "observer"], "default": "assigned"},
                        "linked_ticket_id": {"type": "integer", "description": "ID do outro chamado a vincular (obrigatorio em link_tickets)."},
                        "link_type": {"type": "string", "description": "Tipo do vinculo entre chamados no GLPI. Valores: link (relacionado, padrao), duplicate (duplicado), son (filho), parent (pai).", "enum": ["link", "duplicate", "son", "parent"], "default": "link"},
                        "file_base64": {"type": "string", "description": "Conteudo do arquivo codificado em base64 (obrigatorio em add_document). Exige file_name. Limite de 25 MB."},
                        "file_name": {"type": "string", "description": "Nome do arquivo com extensao (obrigatorio quando usar file_base64). A extensao define o tipo MIME enviado ao GLPI."},
                        "document_title": {"type": "string", "description": "Titulo do documento no GLPI. Padrao: o proprio nome do arquivo."},
                        "limit": {"type": "integer", "description": "Quantidade maxima de eventos retornados em get_timeline (padrao 100, mantem os mais recentes).", "minimum": 1, "maximum": 200, "default": 100},
                        "confirmation_token": {"type": "string", "description": "Token de confirmacao exigido para operacoes destrutivas quando o safety guard esta ativo."},
                        "reason": {"type": "string", "description": "Motivo da operacao destrutiva (minimo 10 caracteres) quando o safety guard esta ativo."},
                    },
                    "required": ["action"],
                },
                "handler": manage_tickets,
                "category": "tickets",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_ticket_ai_analysis",  # 34 chars
                "description": (
                    "Analise por IA de chamados, tickets e incidentes do GLPI — orquestra job assincrono que categoriza, "
                    "prioriza e sugere solucao baseada no historico. Fluxo em 3 passos: 1) action=trigger com ticket_id "
                    "dispara o job e retorna job_id; 2) action=get_result com job_id consulta o resultado quando pronto; "
                    "3) action=publish com job_id e response publica a resposta no chamado do GLPI. Sempre comece em trigger. "
                    "Retorna Markdown."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Etapa do fluxo de analise IA no GLPI. Valores: trigger (passo 1: dispara o job a partir do ticket_id), get_result (passo 2: consulta resultado usando job_id), publish (passo 3: publica resposta IA usando job_id e response)", "enum": ["trigger", "get_result", "publish"]},
                        "ticket_id": {"type": "integer", "description": "ID do chamado a analisar no GLPI (obrigatorio para trigger)"},
                        "job_id": {"type": "string", "description": "ID do job retornado pelo passo trigger (obrigatorio para get_result e publish)"},
                        "response": {"type": "object", "description": "Payload da resposta IA a publicar no chamado (obrigatorio para publish; normalmente vem do get_result)"},
                    },
                    "required": ["action"],
                },
                "handler": manage_ai_analysis,
                "category": "tickets",
                "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
            },
            # === ASSETS (2 tools) ===
            {
                "name": "glpi_search_asset_inventory",  # 31 chars
                "description": (
                    "Ativos, equipamentos, patrimonio e inventario de TI no GLPI — busca por computadores, monitores, impressoras, "
                    "software, dispositivos de rede, reservas e estatisticas. Use scope para filtrar tipo de busca no GLPI. "
                    "Aceita filtro por responsavel (assigned_user, por nome ou id) e ordenacao via sort_by/order. "
                    "IMPORTANTE: o token MCP ja fixa o cliente/tenant — NAO preencha entity_id nem entity_name (so use para "
                    "filtrar sub-entidade especifica). Sem parametros, retorna inventario completo do cliente. Retorna tabela "
                    "Markdown paginada. Consulta somente leitura."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "description": "Escopo da busca no GLPI. Valores: all (todos os ativos), computers (computadores), monitors (monitores), software (programas), devices (dispositivos de rede/telefone), reservations (reservas ativas), reservable (itens reservaveis), stats (estatisticas)", "enum": ["all", "computers", "monitors", "software", "devices", "reservations", "reservable", "stats"], "default": "all"},
                        "asset_type": {"type": "string", "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral", "enum": ["Computer", "Monitor", "Printer", "NetworkEquipment", "Phone", "Peripheral"]},
                        "query": {"type": "string", "description": "Texto para busca por nome, serial ou usuario vinculado"},
                        "assigned_user": {"type": "string", "description": "Responsavel pelo ativo no GLPI (usuario vinculado ao equipamento). Aceita o NOME (busca parcial, ex: 'Joao') ou o ID numerico do usuario. Use para 'quais equipamentos estao com o fulano', 'notebook do X'. Nao se aplica a scope=software."},
                        "username": {"type": "string", "description": "Login do usuario vinculado ao ativo (filtro; scope=computers e busca por texto). Prefira assigned_user."},
                        "device_type": {"type": "string", "description": "Tipo de ativo listado em scope=devices. Padrao: NetworkEquipment. Valores: NetworkEquipment, Peripheral, Phone, Printer, Monitor, Computer.", "enum": ["NetworkEquipment", "Peripheral", "Phone", "Printer", "Monitor", "Computer"]},
                        "is_active": {"type": "boolean", "description": "Filtra itens reservaveis ativos (apenas scope=reservable)."},
                        "itemtype": {"type": "string", "description": "Tipo do item reservavel (apenas scope=reservable). Valores: Computer, Monitor, Peripheral, Phone, Printer, NetworkEquipment.", "enum": ["Computer", "Monitor", "Peripheral", "Phone", "Printer", "NetworkEquipment"]},
                        "fields": {"type": "array", "description": "IDs numericos das colunas de busca do GLPI a devolver (apenas com query). Omitido = colunas padrao.", "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
                        "status": {"type": "string", "description": "Situacao do ativo no GLPI (states_id), como TEXTO com o ID numerico do estado (ex: '2'). Use para 'equipamentos em estoque', 'maquinas em uso', 'itens em manutencao'."},
                        "location_id": {"type": "integer", "description": "ID da localizacao no GLPI. Use para 'equipamentos da filial X', 'maquinas do andar Y'."},
                        "manufacturer_id": {"type": "integer", "description": "ID do fabricante no GLPI. Use para 'quantos equipamentos Dell temos', 'impressoras da marca X'."},
                        "user_id": {"type": "integer", "description": "ID numerico do usuario vinculado ao ativo. Prefira assigned_user, que tambem aceita o nome."},
                        "sort_by": {"type": "string", "description": "Campo de ordenacao no GLPI. Padrao do GLPI quando omitido. Use name para ordem alfabetica, date_mod para 'equipamentos alterados recentemente' (com order=desc), status para agrupar por situacao.", "enum": ["name", "id", "serial", "location", "manufacturer", "model", "status", "user", "date_mod"]},
                        "order": {"type": "string", "description": "Direcao da ordenacao. asc (crescente, A-Z ou mais antigos primeiro) ou desc (decrescente, Z-A ou mais recentes primeiro). Sem sort_by, aplica a direcao ao nome do ativo.", "enum": ["asc", "desc"]},
                        "entity_id": {"type": "integer", "description": "OPCIONAL — Token ja fixa tenant. So preencha para filtrar UMA sub-entidade especifica. ID numerico no GLPI."},
                        "entity_name": {"type": "string", "description": "OPCIONAL — Token ja fixa tenant. So preencha para filtrar UMA sub-entidade pelo nome."},
                        "limit": {"type": "integer", "description": "Quantidade maxima de resultados (padrao: 10, maximo: 50)", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "description": "Deslocamento para paginacao (padrao: 0)", "minimum": 0, "default": 0},
                    },
                },
                "handler": search_assets,
                "category": "assets",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_asset_operations",  # 32 chars
                "description": (
                    "Ativos, equipamentos e patrimonio no GLPI — operacoes sobre UM ativo especifico: cadastro, consulta "
                    "detalhada, atualizacao, exclusao e gerenciamento de reservas. Use action no GLPI: get, get_details, "
                    "create, update, delete, get_reservations, create_reservation, update_reservation. Para LISTAR ativos "
                    "use glpi_search_asset_inventory. Token ja fixa tenant — nao passe entity em operacoes basicas. Retorna Markdown."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Operacao sobre ativo no GLPI. Valores: get (detalhes basicos), get_details (detalhes com hardware), create (cadastrar), update (atualizar), delete (excluir), get_reservations (ver reservas), create_reservation (reservar), update_reservation (alterar reserva)", "enum": ["get", "get_details", "create", "update", "delete", "get_reservations", "create_reservation", "update_reservation"]},
                        "asset_type": {"type": "string", "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral", "enum": ["Computer", "Monitor", "Printer", "NetworkEquipment", "Phone", "Peripheral"]},
                        "asset_id": {"type": "integer", "description": "ID do ativo no GLPI (obrigatorio para get, get_details, update, delete, get_reservations, create_reservation)"},
                        "name": {"type": "string", "description": "Nome do ativo (obrigatorio para create)"},
                        "serial_number": {"type": "string", "description": "Numero de serie do equipamento"},
                        "user_id": {"type": "integer", "description": "ID do usuario: da reserva (obrigatorio para create_reservation; opcional em update_reservation) ou o responsavel do ativo (create e update)"},
                        "date_start": {"type": "string", "description": "Inicio da reserva 'YYYY-MM-DD HH:MM:SS' (obrigatorio para create_reservation; opcional em update_reservation)"},
                        "date_end": {"type": "string", "description": "Fim da reserva 'YYYY-MM-DD HH:MM:SS' (obrigatorio para create_reservation; opcional em update_reservation)"},
                        "reservation_id": {"type": "integer", "description": "ID da reserva existente (obrigatorio para update_reservation)"},
                        "comment": {"type": "string", "description": "Comentario opcional: do ativo (create e update) ou da reserva (create_reservation e update_reservation)"},
                        "other_serial": {"type": "string", "description": "Numero de serie alternativo/inventario (create e update)."},
                        "status": {"type": "integer", "description": "Estado do ativo no GLPI (states_id), como NUMERO INTEIRO (ex: 2) (create e update)."},
                        "entity_id": {"type": "integer", "description": "OPCIONAL — Token ja fixa tenant. ID da sub-entidade do ativo (create e update)."},
                        "location_id": {"type": "integer", "description": "ID da localizacao do ativo (create e update)."},
                        "manufacturer_id": {"type": "integer", "description": "ID do fabricante (create e update)."},
                        "model_id": {"type": "integer", "description": "ID do modelo (create e update)."},
                        "group_id": {"type": "integer", "description": "ID do grupo responsavel (create e update)."},
                        "date_from": {"type": "string", "description": "Inicio do periodo das reservas, formato ISO 8601 (AAAA-MM-DD) (get_reservations)."},
                        "date_to": {"type": "string", "description": "Fim do periodo das reservas, formato ISO 8601 (AAAA-MM-DD) (get_reservations)."},
                        "confirmation_token": {"type": "string", "description": "Token de confirmacao exigido para a exclusao quando o safety guard esta ativo."},
                        "reason": {"type": "string", "description": "Motivo da exclusao (minimo 10 caracteres) quando o safety guard esta ativo."},
                    },
                    "required": ["action"],
                },
                "handler": manage_assets,
                "category": "assets",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            # === ADMIN (2 tools) ===
            {
                "name": "glpi_search_admin_resources",  # 31 chars
                "description": (
                    "Usuarios, colaboradores, tecnicos, grupos, equipes, entidades e localizacoes no GLPI — busca unificada de "
                    "recursos administrativos com filtro por nome, login, email e entidade. Use resource para selecionar: users, "
                    "groups, entities, locations. Aceita ordenacao via sort_by/order. Use para 'quem e o tecnico X', 'listar "
                    "usuarios do cliente', 'quais grupos existem'. IMPORTANTE: o token MCP ja fixa o cliente/tenant no GLPI — NAO "
                    "preencha entity_id nem entity_name (so use para sub-entidade). Retorna tabela Markdown. Somente leitura."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "resource": {"type": "string", "description": "Tipo de recurso administrativo no GLPI. Valores: users (usuarios/tecnicos), groups (grupos/equipes), entities (entidades/clientes), locations (localizacoes/escritorios)", "enum": ["users", "groups", "entities", "locations"], "default": "users"},
                        "query": {"type": "string", "description": "Texto para busca por nome, sobrenome, email ou login (aplica-se a users)"},
                        "sort_by": {"type": "string", "description": "Campo de ordenacao no GLPI. Padrao do GLPI quando omitido. Use name para ordem alfabetica, date_creation com order=desc para 'usuarios cadastrados recentemente', last_login para 'quem entrou por ultimo' (so users). Campo que o recurso nao possui cai no nome.", "enum": ["name", "id", "email", "firstname", "realname", "comment", "entity", "location", "date_mod", "date_creation", "last_login"]},
                        "order": {"type": "string", "description": "Direcao da ordenacao. asc (crescente, A-Z ou mais antigos primeiro) ou desc (decrescente, Z-A ou mais recentes primeiro). Sem sort_by, aplica a direcao ao nome do recurso.", "enum": ["asc", "desc"]},
                        "entity_id": {"type": "integer", "description": "OPCIONAL — Token ja fixa tenant. So preencha para filtrar usuarios/recursos de UMA sub-entidade especifica."},
                        "entity_name": {"type": "string", "description": "OPCIONAL — Token ja fixa tenant. So preencha para filtrar pelo nome de UMA sub-entidade."},
                        "limit": {"type": "integer", "description": "Quantidade maxima de resultados (padrao: 10, maximo: 50)", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "description": "Deslocamento para paginacao (padrao: 0)", "minimum": 0, "default": 0},
                    },
                },
                "handler": search_admin,
                "category": "admin",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_admin_resources",  # 31 chars
                "description": (
                    "Usuarios, colaboradores, grupos, entidades e localizacoes no GLPI — operacoes sobre UM recurso "
                    "administrativo especifico: cadastro, consulta detalhada, atualizacao e exclusao. Use resource + action "
                    "no GLPI: get (detalhe), create (cadastrar), update (atualizar), delete (excluir). Para LISTAR use "
                    "glpi_search_admin_resources. Token ja fixa tenant — nao passe entity em operacoes basicas. Retorna Markdown."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "resource": {"type": "string", "description": "Tipo de recurso administrativo no GLPI. Valores: users (usuarios), groups (grupos), entities (entidades), locations (localizacoes)", "enum": ["users", "groups", "entities", "locations"]},
                        "action": {"type": "string", "description": "Operacao a executar no GLPI. Valores: get (consultar detalhes), create (cadastrar novo), update (atualizar existente), delete (excluir)", "enum": ["get", "create", "update", "delete"]},
                        "resource_id": {"type": "integer", "description": "ID do recurso no GLPI (obrigatorio para get, update, delete)"},
                        "name": {"type": "string", "description": "Nome/login (obrigatorio para create de users e groups)"},
                        "email": {"type": "string", "description": "Email do usuario (para create/update de users)"},
                        "password": {"type": "string", "description": "SENSIVEL. Senha do usuario local, minimo 6 caracteres (apenas create de users; necessaria para authtype=1). Vai ao GLPI e nunca e devolvida nem registrada em log."},
                        "password2": {"type": "string", "description": "SENSIVEL. Confirmacao da senha; igual a password. Se omitida, usa password."},
                        "firstname": {"type": "string", "description": "Primeiro nome do usuario (users: create e update)."},
                        "realname": {"type": "string", "description": "Sobrenome do usuario (users: create e update)."},
                        "phone": {"type": "string", "description": "Telefone principal do usuario (users: create e update)."},
                        "phone2": {"type": "string", "description": "Telefone secundario do usuario (users: create e update)."},
                        "mobile": {"type": "string", "description": "Celular do usuario (users: create e update)."},
                        "authtype": {"type": "integer", "description": "Tipo de autenticacao do usuario (apenas create de users). Valores: 1 (local, padrao), 2 (e-mail), 3 (LDAP).", "enum": [1, 2, 3], "default": 1},
                        "is_active": {"type": "boolean", "description": "Usuario ativo (users: create, padrao true; update: omitido = nao altera)."},
                        "profile_id": {"type": "integer", "description": "ID do perfil padrao do usuario (users: create e update)."},
                        "group_id": {"type": "integer", "description": "ID do grupo ao qual adicionar o usuario (users: apenas create)."},
                        "usertitle_id": {"type": "integer", "description": "ID do titulo/cargo do usuario (users: create e update)."},
                        "usercategory_id": {"type": "integer", "description": "ID da categoria do usuario (users: create e update)."},
                        "registration_number": {"type": "string", "description": "Numero administrativo/matricula do usuario (users: create e update)."},
                        "entity_id": {"type": "integer", "description": "OPCIONAL — Token ja fixa tenant. ID da sub-entidade (users, groups, locations)."},
                        "entity_name": {"type": "string", "description": "OPCIONAL — Nome da sub-entidade, resolvido automaticamente (apenas create)."},
                        "location_id": {"type": "integer", "description": "ID da localizacao do usuario (users: create e update)."},
                        "comment": {"type": "string", "description": "Comentario do registro (users, groups, locations: create e update)."},
                        "is_user_group": {"type": "boolean", "description": "Grupo de usuarios (groups: create, padrao true; update: omitido = nao altera)."},
                        "is_technical_group": {"type": "boolean", "description": "Grupo tecnico, que pode receber itens (groups: create, padrao false; update: omitido = nao altera)."},
                        "is_requester": {"type": "boolean", "description": "Grupo pode ser solicitante (groups: create, padrao true; update: omitido = nao altera)."},
                        "is_assign": {"type": "boolean", "description": "Grupo pode receber atribuicao (groups: create, padrao true; update: omitido = nao altera)."},
                        "is_notify": {"type": "boolean", "description": "Grupo recebe notificacoes (groups: create, padrao true; update: omitido = nao altera)."},
                        "parent_location_id": {"type": "integer", "description": "ID da localizacao pai (locations: create e update)."},
                        "building": {"type": "string", "description": "Predio (locations: create e update)."},
                        "room": {"type": "string", "description": "Sala (locations: create e update)."},
                        "town": {"type": "string", "description": "Cidade (locations: create e update)."},
                        "address": {"type": "string", "description": "Endereco (locations: create e update)."},
                        "confirmation_token": {"type": "string", "description": "Token de confirmacao exigido para a exclusao (delete) quando o safety guard esta ativo."},
                        "reason": {"type": "string", "description": "Motivo da exclusao (delete) (minimo 10 caracteres) quando o safety guard esta ativo."},
                    },
                    "required": ["resource", "action"],
                },
                "handler": manage_admin,
                "category": "admin",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            # === WEBHOOKS (2 tools) ===
            {
                "name": "glpi_search_webhook_integrations",  # 36 chars
                "description": (
                    "Webhooks, integracoes e callbacks HTTP no GLPI — listagem de endpoints configurados, estatisticas de "
                    "entrega e historico de notificacoes automaticas. Use scope para selecionar no GLPI: list (listar webhooks), "
                    "stats (metricas de entrega), deliveries (historico de tentativas). Retorna Markdown. Consulta somente leitura."
                ),  # 354 chars
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "description": "Escopo da consulta de webhooks no GLPI. Valores: list (listar todos), stats (estatisticas de entrega), deliveries (historico de tentativas por webhook)", "enum": ["list", "stats", "deliveries"], "default": "list"},
                        "webhook_id": {"type": "string", "description": "ID numerico do webhook no GLPI, o mesmo que aparece na coluna ID da listagem (obrigatorio quando scope=deliveries). Aceita 4 ou '4'."},
                        "limit": {"type": "integer", "description": "Quantidade maxima de resultados (padrao: 10, maximo: 50)", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "description": "Deslocamento para paginacao (padrao: 0)", "minimum": 0, "default": 0},
                    },
                },
                "handler": search_webhooks,
                "category": "webhooks",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_webhook_integrations",  # 36 chars
                "description": (
                    "Webhooks, integracoes e notificacoes automaticas no GLPI — cadastro, atualizacao, exclusao, teste de "
                    "conectividade, disparo manual e ativacao de endpoints que avisam sistemas externos quando algo muda. Use "
                    "action no GLPI: get, create, update, delete, test, trigger, enable, disable, retry. Acione para integrar o "
                    "GLPI a outra ferramenta, notificar um sistema a cada chamado novo ou diagnosticar entrega falhando. "
                    "Retorna Markdown."
                ),  # 330 chars
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Operacao sobre webhook no GLPI. Valores: get (detalhes), create (cadastrar), update (atualizar), delete (excluir), test (testar conectividade), trigger (disparo manual), enable (ativar), disable (desativar), retry (reenviar falhas)", "enum": ["get", "create", "update", "delete", "test", "trigger", "enable", "disable", "retry"]},
                        "webhook_id": {"type": "string", "description": "ID numerico do webhook no GLPI, o mesmo que aparece na coluna ID da listagem (obrigatorio para get, update, delete, test, enable, disable, retry). Aceita 4 ou '4'."},
                        "name": {"type": "string", "description": "Nome do webhook (obrigatorio para create)"},
                        "url": {"type": "string", "description": "URL de destino do callback HTTP (obrigatorio para create)"},
                        "event_type": {"type": "string", "description": "Tipo de evento que dispara o webhook (obrigatorio para create e trigger). Valores aceitos: ticket.created, ticket.updated, ticket.deleted, ticket.assigned, asset.created, asset.updated, asset.deleted, asset.reserved, user.created, user.updated, user.deleted, group.created, group.updated, group.deleted", "enum": ["ticket.created", "ticket.updated", "ticket.deleted", "ticket.assigned", "asset.created", "asset.updated", "asset.deleted", "asset.reserved", "user.created", "user.updated", "user.deleted", "group.created", "group.updated", "group.deleted"]},
                        "secret": {"type": "string", "description": "Segredo HMAC usado para assinar as entregas do webhook (create e update). SENSIVEL: e enviado ao GLPI e nunca devolvido — as respostas mostram apenas se esta configurado. Omita para nao alterar."},
                        "is_active": {"type": "boolean", "description": "Se o webhook fica ativo (create: padrao true; update: omita para nao alterar). Para ligar ou desligar um webhook ja existente tambem existem as actions enable e disable."},
                        "headers": {"type": "object", "description": "Cabecalhos HTTP personalizados enviados em cada entrega, em formato chave-valor de strings (create e update). No update substitui o conjunto atual.", "additionalProperties": {"type": "string"}},
                        "data": {"type": "object", "description": "Payload do evento a disparar (apenas action=trigger). Atencao: o GLPI 11 nao expoe disparo manual por REST, entao trigger responde que nao e suportado."},
                        "webhook_ids": {"type": "array", "description": "IDs de webhooks especificos a disparar (apenas action=trigger); omita para todos os webhooks do evento. Mesma ressalva do campo data.", "items": {"type": "string"}},
                        "confirmation_token": {"type": "string", "description": "Token de confirmacao exigido na exclusao (delete) quando o safety guard esta ativo."},
                        "reason": {"type": "string", "description": "Motivo da exclusao (delete), minimo 10 caracteres, quando o safety guard esta ativo."},
                    },
                    "required": ["action"],
                },
                "handler": manage_webhooks,
                "category": "webhooks",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            # === BRIDGE (4 tools) ===
            {
                "name": "glpi_list_available_resources",  # 32 chars
                "description": (
                    "Resources MCP, dados estaticos e referencias do GLPI — catalogo de URIs disponiveis para consulta direta "
                    "de entidades, status de tickets, categorias e prioridades no GLPI. Use quando precisar descobrir quais "
                    "dados de referencia estao acessiveis via protocolo MCP no GLPI. Retorna tabela Markdown."
                ),  # 327 chars
                "input_schema": {"type": "object"},
                "handler": bridge_tools.list_resources_tool,
                "category": "bridge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            },
            {
                "name": "glpi_read_resource_by_uri",  # 28 chars - acceptable per Rule 3 exception
                "description": (
                    "Resource MCP e dados de referencia do GLPI — leitura do conteudo de uma URI especifica com entidades, "
                    "status ou categorias. Use quando ja souber a URI do resource no GLPI (ex: glpi://entities, "
                    "glpi://ticket-status, glpi://ticket-categories, glpi://priorities). Retorna conteudo Markdown formatado."
                ),  # 334 chars
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "uri": {"type": "string", "description": "URI do resource no GLPI. Valores aceitos: glpi://entities, glpi://ticket-status, glpi://ticket-categories, glpi://priorities", "enum": ["glpi://entities", "glpi://ticket-status", "glpi://ticket-categories", "glpi://priorities"]},
                    },
                    "required": ["uri"],
                },
                "handler": bridge_tools.read_resource_tool,
                "category": "bridge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_list_available_prompts",  # 30 chars
                "description": (
                    "Prompts profissionais, relatorios e analises do GLPI — catalogo de 15 modelos prontos para gestores "
                    "e analistas de suporte tecnico com metricas de SLA, produtividade e tendencias. Use quando precisar "
                    "descobrir quais relatorios e analises estao disponiveis no GLPI. Retorna tabela Markdown."
                ),  # 325 chars
                "input_schema": {"type": "object"},
                "handler": bridge_tools.list_prompts_tool,
                "category": "bridge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            },
            {
                "name": "glpi_get_prompt_template",  # 27 chars - acceptable per Rule 3
                "description": (
                    "Relatorios gerenciais, dashboards e analises pre-fabricadas do GLPI — EXECUTA um relatorio nomeado e "
                    "retorna os DADOS reais ja processados em Markdown (SLA, tendencias de chamados, produtividade de tecnicos, "
                    "ROI de ativos). NAO retorna template em branco — retorna o relatorio pronto. Para descobrir nomes disponiveis "
                    "chame glpi_list_available_prompts antes. Token ja fixa tenant — relatorio sai do escopo do cliente."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Nome do relatorio/prompt a executar no GLPI (ex: 'glpi_sla_performance', 'glpi_ticket_trends'; o prefixo glpi_ e opcional). Use glpi_list_available_prompts para ver os 15 disponiveis."},
                        "arguments": {"type": "object", "description": "Argumentos do relatorio no formato chave-valor (ex: {'periodo': '30d'}). Cada relatorio aceita argumentos especificos — consulte glpi_list_available_prompts para detalhes."},
                    },
                    "required": ["name"],
                },
                "handler": bridge_tools.get_prompt_tool,
                "category": "bridge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            # === KNOWLEDGE (1 tool) ===
            {
                "name": "glpi_search_knowledge_articles",  # 33 chars
                "description": (
                    "Base de conhecimento, solucoes e artigos tecnicos do GLPI — busca textual em resolucoes de chamados, "
                    "procedimentos e documentacao interna de suporte. Use quando precisar localizar solucoes ja documentadas "
                    "ou procedimentos operacionais registrados no GLPI. Retorna resultados em Markdown paginado."
                ),  # 338 chars
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Texto para busca na base de conhecimento do GLPI (minimo 2 caracteres)"},
                        "limit": {"type": "integer", "description": "Quantidade maxima de resultados (padrao: 10, maximo: 50)", "minimum": 1, "maximum": 50, "default": 10},
                    },
                    "required": ["query"],
                },
                "handler": bridge_tools.search_knowledge,
                "category": "knowledge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_search_knowledge_unified",  # 29 chars
                "description": (
                    "Base de conhecimento unificada do GLPI — busca semantica (pgvector) e textual em chamados "
                    "resolvidos, artigos de ajuda e posts de comunidade, com ranking RRF que mistura as fontes e "
                    "rotula cada item. Use para duvidas, erros, mensagens de erro, sintomas ou how-to, achando "
                    "solucoes ja aplicadas no GLPI. Diferente de glpi_search_knowledge_articles (so artigos nativos "
                    "via REST). Retorna tabela Markdown."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Texto livre da duvida, erro ou sintoma para buscar na base de conhecimento do GLPI (minimo 2 caracteres)."},
                        "source": {"type": "string", "enum": ["all", "chamados", "help", "comunidade"], "default": "all", "description": "Fonte: all (todas com RRF), chamados (resolvidos do GLPI), help (artigos de ajuda), comunidade (forum)."},
                        "limit": {"type": "integer", "description": "Quantidade maxima de resultados (padrao 15, maximo 50).", "minimum": 1, "maximum": 50, "default": 15},
                        "tenant": {"type": "string", "description": "Opcional: restringe a busca a uma entidade/cliente (multi-tenant). Itens globais sempre aparecem."},
                    },
                    "required": ["query"],
                },
                "handler": kb_search_unified,
                "category": "knowledge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            # === ITIL ALEM DO INCIDENTE (2 tools) ===
            {
                "name": "glpi_search_itil_records",  # 24 chars
                "description": (
                    "Problemas, mudancas, projetos, contratos e fornecedores no GLPI — busca e listagem dos registros ITIL que "
                    "ficam ALEM do chamado comum, com filtro por situacao, prioridade, urgencia, categoria, entidade e periodo. "
                    "Use para 'problemas abertos', 'mudancas planejadas', 'RFC do mes', 'contratos vencendo', 'quais fornecedores "
                    "temos', 'causa raiz recorrente'. Para chamados/incidentes use glpi_search_helpdesk_tickets. Aceita "
                    "count_only para obter apenas o total do GLPI. Retorna tabela Markdown paginada. Somente leitura."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "record_type": {"type": "string", "description": "Tipo de registro ITIL no GLPI. Valores: problems (problemas/causa raiz), changes (mudancas/RFC), projects (projetos), contracts (contratos), suppliers (fornecedores).", "enum": ["problems", "changes", "projects", "contracts", "suppliers"]},
                        "query": {"type": "string", "description": "Texto para busca no titulo/nome do registro (minimo 2 caracteres)."},
                        "status": {"type": "string", "description": "Situacao do registro no GLPI. Para problemas e mudancas aceita o nome do status; para projetos e contratos, o estado; para fornecedores, ativo ou inativo."},
                        "priority": {"type": "integer", "description": "Prioridade de 1 (muito baixa) a 6 (maior). Nao se aplica a contratos e fornecedores.", "minimum": 1, "maximum": 6},
                        "urgency": {"type": "integer", "description": "Urgencia de 1 a 5. Aplica-se apenas a problemas e mudancas no GLPI.", "minimum": 1, "maximum": 5},
                        "category": {"type": "string", "description": "Categoria ITIL (problemas/mudancas) ou tipo (projeto, contrato, fornecedor). Aceita nome ou ID numerico."},
                        "entity_id": {"type": "integer", "description": "OPCIONAL — Token ja fixa tenant. So preencha para uma sub-entidade especifica."},
                        "entity_name": {"type": "string", "description": "OPCIONAL — Token ja fixa tenant. Nome de UMA sub-entidade, resolvido automaticamente."},
                        "date_from": {"type": "string", "description": "Inicio do periodo. Aceita AAAA-MM-DD, DD/MM/AAAA ou as palavras hoje e ontem."},
                        "date_to": {"type": "string", "description": "Fim do periodo. Aceita AAAA-MM-DD, DD/MM/AAAA ou as palavras hoje e ontem."},
                        "date_field": {"type": "string", "description": "Coluna de data usada no periodo. Padrao: data de abertura (problemas, mudancas, projetos), inicio de vigencia (contratos) e data de cadastro (fornecedores)."},
                        "sort_by": {"type": "string", "description": "Campo de ordenacao (nome do campo ou ID numerico no GLPI). Campo desconhecido cai no padrao do tipo."},
                        "order": {"type": "string", "description": "Direcao da ordenacao: asc (crescente) ou desc (decrescente, padrao).", "enum": ["asc", "desc"], "default": "desc"},
                        "limit": {"type": "integer", "description": "Quantidade maxima de resultados (padrao 10, maximo 50).", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "description": "Deslocamento para paginacao (padrao 0).", "minimum": 0, "default": 0},
                        "count_only": {"type": "boolean", "description": "Se true, retorna APENAS a quantidade total no GLPI, sem trazer os registros. Consulta barata para perguntas de volume.", "default": False},
                    },
                    "required": ["record_type"],
                },
                "handler": search_itil_records,
                "category": "itil",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_itil_records",  # 24 chars
                "description": (
                    "Problemas, mudancas, projetos, contratos e fornecedores no GLPI — operacoes sobre UM registro ITIL: consulta "
                    "detalhada, cadastro, alteracao, exclusao, comentarios e vinculo com chamados. Use record_type + action no "
                    "GLPI: get, create, update, delete, add_followup, get_followups, link_ticket. Acione para abrir um problema a "
                    "partir de chamados repetidos, registrar uma mudanca, cadastrar contrato ou fornecedor. Para LISTAR use "
                    "glpi_search_itil_records. Exclusao e destrutiva e pode exigir confirmacao. Retorna Markdown."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "record_type": {"type": "string", "description": "Tipo de registro ITIL no GLPI. Valores: problems, changes, projects, contracts, suppliers.", "enum": ["problems", "changes", "projects", "contracts", "suppliers"]},
                        "action": {"type": "string", "description": "Operacao no GLPI. Valores: get (detalhe), create (cadastrar), update (alterar), delete (excluir), add_followup (comentar), get_followups (listar comentarios), link_ticket (vincular chamado ao problema ou mudanca).", "enum": ["get", "create", "update", "delete", "add_followup", "get_followups", "link_ticket"]},
                        "record_id": {"type": "integer", "description": "ID do registro no GLPI (obrigatorio para get, update, delete, add_followup, get_followups e link_ticket)."},
                        "name": {"type": "string", "description": "Titulo do problema/mudanca/projeto ou nome do contrato/fornecedor (obrigatorio em create)."},
                        "content": {"type": "string", "description": "Descricao detalhada do registro. Formatacao: o GLPI guarda este campo como HTML — use <br>, <p>, <strong>, <ul><li> para formatar. Markdown (**negrito**) NAO e interpretado e aparece literal. Aspas, & e acentos podem ser escritos normalmente."},
                        "comment": {"type": "string", "description": "Observacoes do registro (usado em projetos, contratos e fornecedores)."},
                        "status": {"type": "string", "description": "Situacao do registro no GLPI."},
                        "priority": {"type": "integer", "description": "Prioridade de 1 a 6.", "minimum": 1, "maximum": 6},
                        "urgency": {"type": "integer", "description": "Urgencia de 1 a 5 (problemas e mudancas).", "minimum": 1, "maximum": 5},
                        "impact": {"type": "integer", "description": "Impacto de 1 a 5 (problemas e mudancas).", "minimum": 1, "maximum": 5},
                        "category_id": {"type": "integer", "description": "ID da categoria ITIL ou do tipo (projeto, contrato, fornecedor) no GLPI."},
                        "state_id": {"type": "integer", "description": "ID do estado do projeto ou do contrato no GLPI."},
                        "entity_id": {"type": "integer", "description": "OPCIONAL — Token ja fixa tenant. So preencha para sub-entidade especifica."},
                        "entity_name": {"type": "string", "description": "OPCIONAL — Nome de sub-entidade, resolvido automaticamente."},
                        "begin_date": {"type": "string", "description": "Inicio de vigencia do contrato ou inicio planejado do projeto (AAAA-MM-DD)."},
                        "end_date": {"type": "string", "description": "Fim planejado do projeto (AAAA-MM-DD). Em contratos, o GLPI calcula o fim a partir do inicio mais a duracao."},
                        "duration": {"type": "integer", "description": "Duracao do contrato em meses."},
                        "periodicity": {"type": "integer", "description": "Periodicidade do contrato em meses."},
                        "num": {"type": "string", "description": "Numero do contrato no GLPI."},
                        "manager_id": {"type": "integer", "description": "ID do responsavel pelo projeto."},
                        "percent_done": {"type": "integer", "description": "Percentual concluido do projeto (0 a 100).", "minimum": 0, "maximum": 100},
                        "code": {"type": "string", "description": "Codigo do projeto."},
                        "is_active": {"type": "boolean", "description": "Situacao ativa do fornecedor."},
                        "email": {"type": "string", "description": "E-mail do fornecedor."},
                        "phone": {"type": "string", "description": "Telefone do fornecedor."},
                        "website": {"type": "string", "description": "Site do fornecedor."},
                        "followup_content": {"type": "string", "description": "Texto do comentario (obrigatorio em add_followup)."},
                        "is_private": {"type": "boolean", "description": "Se true, o comentario fica visivel apenas para tecnicos.", "default": False},
                        "ticket_id": {"type": "integer", "description": "ID do chamado a vincular (obrigatorio em link_ticket, apenas para problemas e mudancas)."},
                        "purge": {"type": "boolean", "description": "Se true, exclui definitivamente; se false (padrao), envia para a lixeira do GLPI.", "default": False},
                        "confirmation_token": {"type": "string", "description": "Token de confirmacao exigido na exclusao quando o safety guard esta ativo."},
                        "reason": {"type": "string", "description": "Motivo da exclusao (minimo 10 caracteres) quando o safety guard esta ativo."},
                        "fields": {"type": "object", "description": "Campos adicionais do GLPI em formato chave-valor, para colunas nao cobertas pelos parametros acima."},
                    },
                    "required": ["record_type", "action"],
                },
                "handler": manage_itil_records,
                "category": "itil",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            # === BUSCA AVANCADA (1 tool) ===
            {
                "name": "glpi_search_records_by_criteria",  # 31 chars
                "description": (
                    "Registros de qualquer tipo no GLPI por criterios livres — monta filtros combinados com E/OU sobre "
                    "chamados, ativos, usuarios, contratos ou qualquer itemtype, sem depender dos filtros prontos das outras "
                    "tools. Use quando a pergunta nao couber nas buscas especificas do GLPI, para contar registros sem lista-los "
                    "(scope=count) ou para descobrir quais campos existem (scope=fields). Campos podem ser informados por NOME. "
                    "Ferramenta de apoio: prefira as tools especificas quando elas atenderem. Retorna Markdown."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "itemtype": {"type": "string", "description": "Tipo de registro no GLPI. Exemplos: Ticket (chamado), Computer (computador), User (usuario), Problem, Change, Contract, Supplier, Software, Monitor, Printer, KnowbaseItem."},
                        "scope": {"type": "string", "description": "O que fazer no GLPI. Valores: search (traz os registros, padrao), count (traz apenas o total, consulta barata), fields (lista os campos disponiveis para filtrar e ordenar).", "enum": ["search", "count", "fields"], "default": "search"},
                        "criteria": {"type": "array", "description": "Lista de condicoes. Cada item: field (nome do campo ou ID), searchtype (contains, equals, notequals, lessthan, morethan, under, empty), value e link (AND ou OR, aplicado a partir da segunda condicao). ATENCAO: 'morethan' e 'lessthan' so funcionam como comparacao em campos de DATA. Em campo numerico ou de enum eles colapsam para igualdade — varredura completa de 0 a 7 sobre a prioridade de chamados, que tem 6 valores reais distintos, deu morethan(N) = lessthan(N) = equals(N) em todos os pontos. Uma faixa numerica devolveria uma fatia exata parecendo um intervalo, sem erro. Estes dois operadores sao RECUSADOS fora de colunas de data; para conjuntos use varios criterios com link OR.", "items": {"type": "object"}},
                        "fields": {"type": "array", "description": "Colunas a retornar, por nome ou ID. Campo desconhecido e ignorado com aviso.", "items": {"type": "string"}},
                        "sort_by": {"type": "string", "description": "Campo de ordenacao, por nome ou ID numerico do GLPI."},
                        "order": {"type": "string", "description": "Direcao da ordenacao: asc ou desc.", "enum": ["asc", "desc"]},
                        "limit": {"type": "integer", "description": "Quantidade maxima de registros (padrao 10, maximo 50).", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "description": "Deslocamento para paginacao (padrao 0).", "minimum": 0, "default": 0},
                        "field_filter": {"type": "string", "description": "Usado com scope=fields: filtra os campos listados por um trecho do nome (ex: data, status)."},
                    },
                    "required": ["itemtype"],
                },
                "handler": search_records,
                "category": "search",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
        ]

        # @MX:WARN: glpi_manage_ticket_ai_analysis stays out of tools/list while
        # settings.enable_ai_analysis is False.
        # @MX:REASON: AIIntegrationService is an in-memory job store that never
        # calls GLPI, and configure_agents() has no caller, so _agents_configured
        # is permanently False. In that state action=trigger answers "disparada
        # com sucesso" for ANY ticket_id (even one that does not exist) and
        # action=publish answers "realizada com sucesso" without writing a single
        # byte to the ticket — a model reading that reports a published AI
        # analysis to the user that does not exist anywhere. The handler and the
        # service are kept intact so wiring a real agent is a one-flag change.
        gated = {"glpi_manage_ticket_ai_analysis"} if not settings.enable_ai_analysis else set()

        for tool_def in CONSOLIDATED_TOOLS:
            if tool_def["name"] in gated:
                continue
            tools[tool_def["name"]] = tool_def

        if gated:
            logger.info(
                f"AI analysis tool not registered (ENABLE_AI_ANALYSIS=false): {sorted(gated)}"
            )

        logger.info(
            f"Registered {len(tools)} consolidated MCP tools (SPEC-GLPI-ENHANCE-001/F04)"
        )
        return tools

    async def handle_list_tools(self) -> Dict[str, Any]:
        """
        Handler MCP: tools/list
        Lista todas as tools disponíveis conforme JSON-RPC 2.0.

        Returns:
            Lista de tools MCP disponíveis
        """
        try:
            logger.info("MCP Handler: tools/list")

            tools_list = []
            for tool_name, tool_info in self.tools.items():
                tool_entry = {
                    "name": tool_info["name"],
                    "description": tool_info["description"],
                    "inputSchema": tool_info["input_schema"],
                }
                # SPEC-GLPI-ENHANCE-001/F03: Emit annotations in tools/list
                if "annotations" in tool_info:
                    tool_entry["annotations"] = tool_info["annotations"]
                tools_list.append(tool_entry)

            result = {
                "tools": tools_list,
                "total_count": len(tools_list),
                "categories": {
                    "tickets": len(
                        [t for t in self.tools.values() if t["category"] == "tickets"]
                    ),
                    "assets": len(
                        [t for t in self.tools.values() if t["category"] == "assets"]
                    ),
                    "admin": len(
                        [t for t in self.tools.values() if t["category"] == "admin"]
                    ),
                    "webhooks": len(
                        [t for t in self.tools.values() if t["category"] == "webhooks"]
                    ),
                },
            }

            logger.info(f"tools/list completed: {len(tools_list)} tools returned")
            return result

        except Exception as e:
            logger.error(f"tools/list error: {e}", exc_info=True)
            raise GLPIError(500, f"Failed to list tools: {str(e)}") from None

    # Domínio de escrita de cada tool consolidada, para o portão de política.
    # Tools de leitura não aparecem: ausência aqui significa "sem portão".
    _WRITE_DOMAINS = {
        "glpi_manage_ticket_operations": "tickets",
        "glpi_manage_asset_operations": "assets",
        "glpi_manage_admin_resources": "admin",
        "glpi_manage_webhook_integrations": "webhooks",
        "glpi_manage_itil_records": "itil",
    }

    # Ações que criam registro novo e, portanto, duplicam se repetidas.
    # Atualizar ou excluir duas vezes converge no mesmo estado; criar, não.
    _CREATE_LIKE_ACTIONS = frozenset({
        "create", "add_followup", "add_task", "add_document",
        "link_tickets", "link_ticket", "request_validation", "create_reservation",
    })

    # Janela de proteção contra repetição. Curta de propósito: cobre o retry do
    # cliente ou do modelo sem impedir que alguém registre, mais tarde, um
    # comentário legitimamente idêntico.
    _IDEMPOTENCY_TTL_SECONDS = 120

    def _resolve_write_operation(self, tool_name: str, arguments: Dict[str, Any]):
        """Descobre qual operação de escrita esta chamada representa.

        @MX:ANCHOR: único ponto que liga as tools à política de escrita.
        @MX:REASON: os módulos de política e idempotência existiam com testes
        completos e não eram chamados por ninguém — protegiam no papel. Ligar
        aqui, no despacho, cobre toda tool de uma vez e evita que a próxima
        tool nasça desprotegida por esquecimento.
        """
        domain = self._WRITE_DOMAINS.get(tool_name)
        if not domain:
            return None
        action = str(arguments.get("action") or "").strip().lower()
        if not action:
            return None
        # O recurso vem com nomes diferentes conforme a tool: 'resource' no
        # administrativo, 'record_type' no ITIL. Exclusão tem portão por tipo,
        # então o nome precisa chegar até aqui.
        resource = arguments.get("resource") or arguments.get("record_type")

        # Tenta primeiro o portão específico do tipo; se não houver, cai no
        # portão do domínio. Sem esse degrau, informar o tipo faria criar e
        # alterar deixarem de resolver — e uma operação que não resolve passa
        # sem portão nenhum.
        if resource:
            specific = resolve_operation(domain, action, resource)
            if specific is not None:
                return specific
        return resolve_operation(domain, action)

    async def _execute_guarded(self, operation, tool_name: str, arguments: Dict[str, Any], handler):
        """Executa uma escrita, protegendo criações contra repetição."""
        action = str(arguments.get("action") or "").strip().lower()
        if action not in self._CREATE_LIKE_ACTIONS:
            return await handler(**arguments)

        store = get_idempotency_store()
        # A chave é o próprio conteúdo da chamada: repetir a mesma criação com
        # os mesmos argumentos é exatamente o caso que precisa ser detido.
        # @MX:NOTE: the key is a digest, never the raw arguments.
        # @MX:REASON: the store persists the key (SQLite by default). Using the
        # JSON itself wrote webhook secrets and user passwords of every create
        # call to disk in clear text.
        key = hashlib.sha256(
            json.dumps(arguments, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        return await store.run(
            operation.value,
            key,
            arguments,
            lambda: handler(**arguments),
            ttl_seconds=self._IDEMPOTENCY_TTL_SECONDS,
        )

    async def handle_call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handler MCP: tools/call
        Executa uma tool específica conforme JSON-RPC 2.0.

        Args:
            tool_name: Nome da tool para executar
            arguments: Argumentos da tool

        Returns:
            Resultado da execução da tool
        """
        try:
            logger.info(f"MCP Handler: tools/call {tool_name}")

            # Verificar se tool existe
            if tool_name not in self.tools:
                raise MethodNotFoundError(tool_name)

            tool_info = self.tools[tool_name]
            handler = tool_info["handler"]

            # Sinonimos do mesmo parametro, resolvidos ANTES da validacao.
            arguments = _normalize_argument_aliases(
                tool_name, arguments, tool_info["input_schema"]
            )

            # Validar argumentos contra schema (básico)
            self._validate_arguments(tool_name, arguments, tool_info["input_schema"])

            # Portao de escrita + protecao contra repeticao, aplicados no ponto
            # de despacho para valerem para TODAS as tools de uma vez.
            operation = self._resolve_write_operation(tool_name, arguments)
            if operation is not None:
                get_write_policy().check(operation)

            # Executar tool
            start_time = datetime.now()
            if operation is not None:
                result = await self._execute_guarded(operation, tool_name, arguments, handler)
            else:
                result = await handler(**arguments)
            execution_time = (datetime.now() - start_time).total_seconds()

            # SPEC-GLPI-ENHANCE-001/F01: Interceptor Markdown centralizado
            # Pattern identico ao Hudu server.ts:388 com fallback chain de 3 niveis:
            # 1. Markdown formatado | 2. result.message | 3. JSON fallback
            markdown = await format_tool_response(tool_name, result, arguments)
            fallback_message = result.get("message", "") if isinstance(result, dict) else ""
            final_text = markdown or fallback_message or json.dumps(result, ensure_ascii=False, default=str)

            # MCP Protocol: tools/call DEVE retornar content array
            wrapped_result = {
                "content": [
                    {
                        "type": "text",
                        "text": final_text,
                    }
                ]
            }

            logger.info(f"tools/call completed: {tool_name} in {execution_time:.3f}s")
            return wrapped_result

        except (GLPIError, NotFoundError, ValidationError, SimilarityError) as e:
            # @MX:NOTE: re-raise limpo, mensagem ja esta clara no exception original
            logger.error(f"tools/call validation error for {tool_name}: {e.message}")
            raise
        except TypeError as e:
            # An argument the handler does not declare surfaces here as a Python TypeError.
            # Tell the agent which argument is wrong and what it may send instead.
            unexpected = _UNEXPECTED_KWARG.search(str(e))
            if unexpected is None:
                logger.error(f"tools/call unexpected error for {tool_name}: {e}", exc_info=True)
                raise GLPIError(500, f"Tool '{tool_name}' falhou: {str(e)}") from None
            schema = self.tools.get(tool_name, {}).get("input_schema") or {}
            accepted = ", ".join(sorted(schema.get("properties") or {})) or "(nenhum)"
            logger.error(f"tools/call unknown argument for {tool_name}: {unexpected.group(1)}")
            raise ValidationError(
                f"A tool '{tool_name}' nao aceita o argumento '{unexpected.group(1)}'. "
                f"Argumentos aceitos: {accepted}.",
                unexpected.group(1),
            ) from None
        except Exception as e:
            # @MX:NOTE: stack completo no log, mensagem unica para o LLM (Bug #9 — flatten)
            logger.error(
                f"tools/call unexpected error for {tool_name}: {e}", exc_info=True
            )
            raise GLPIError(500, f"Tool '{tool_name}' falhou: {str(e)}") from None

    def _validate_arguments(
        self, tool_name: str, arguments: Dict[str, Any], schema: Dict[str, Any]
    ):
        """
        Valida argumentos contra schema JSON: type/required/enum/minimum/maximum/minLength.

        @MX:ANCHOR: Single source of truth para validacao de input antes do dispatch.
        @MX:REASON: Bug #7 — limit=999 (schema max 50) passava por aqui sem rejeicao.
        """
        if schema.get("type") == "object" and not isinstance(arguments, dict):
            raise ValidationError("Arguments must be a JSON object", "arguments")

        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []

        # Required fields
        for field in required:
            if field not in arguments or arguments[field] is None:
                raise ValidationError(
                    f"Parametro '{field}' e obrigatorio. Schema da tool '{tool_name}' "
                    f"exige: {required}",
                    field,
                )

        # @MX:ANCHOR: coerce the scalar the model got the wrong way round before
        # judging it, never after.
        # @MX:REASON: glpi_search_webhook_integrations prints `| ID | 4 |` and
        # glpi_manage_webhook_integrations declared webhook_id as a string, so
        # the obvious follow-up call — webhook_id=4 — was rejected with a type
        # error and the model concluded the webhook did not exist. The same trap
        # fires in reverse whenever a model quotes an id (ticket_id="9449"). An
        # unambiguous scalar in the wrong JSON type is a notation slip, not a
        # different value; only genuinely ambiguous input still errors.
        for name, value in list(arguments.items()):
            spec = properties.get(name)
            if not isinstance(spec, dict) or value is None:
                continue
            expected = spec.get("type")
            if expected == "string" and isinstance(value, int) and not isinstance(value, bool):
                arguments[name] = str(value)
            elif expected == "integer" and isinstance(value, str):
                stripped = value.strip()
                if stripped.lstrip("-").isdigit():
                    arguments[name] = int(stripped)
            elif expected == "boolean" and isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("true", "false"):
                    arguments[name] = lowered == "true"

        # Per-property constraints
        for name, value in arguments.items():
            if value is None:
                continue
            spec = properties.get(name)
            if not isinstance(spec, dict):
                continue

            expected_type = spec.get("type")
            if expected_type == "integer" and not isinstance(value, bool) and not isinstance(value, int):
                raise ValidationError(
                    f"Parametro '{name}' deve ser inteiro, recebido {type(value).__name__}",
                    name,
                )
            if expected_type == "number" and not isinstance(value, (int, float)) or isinstance(value, bool):
                if expected_type == "number":
                    raise ValidationError(
                        f"Parametro '{name}' deve ser numero, recebido {type(value).__name__}",
                        name,
                    )
            if expected_type == "string" and not isinstance(value, str):
                raise ValidationError(
                    f"Parametro '{name}' deve ser string, recebido {type(value).__name__}",
                    name,
                )
            if expected_type == "boolean" and not isinstance(value, bool):
                raise ValidationError(
                    f"Parametro '{name}' deve ser boolean, recebido {type(value).__name__}",
                    name,
                )

            enum = spec.get("enum")
            if enum and value not in enum:
                raise ValidationError(
                    f"Parametro '{name}'='{value}' invalido. Valores aceitos: {enum}",
                    name,
                )

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                minimum = spec.get("minimum")
                maximum = spec.get("maximum")
                if minimum is not None and value < minimum:
                    raise ValidationError(
                        f"Parametro '{name}'={value} abaixo do minimo {minimum}",
                        name,
                    )
                if maximum is not None and value > maximum:
                    raise ValidationError(
                        f"Parametro '{name}'={value} acima do maximo {maximum}",
                        name,
                    )

            if isinstance(value, str):
                min_len = spec.get("minLength")
                max_len = spec.get("maxLength")
                if min_len is not None and len(value) < min_len:
                    raise ValidationError(
                        f"Parametro '{name}' precisa de pelo menos {min_len} caracteres",
                        name,
                    )
                if max_len is not None and len(value) > max_len:
                    raise ValidationError(
                        f"Parametro '{name}' excede {max_len} caracteres",
                        name,
                    )

        logger.debug(f"Arguments validated for tool: {tool_name}")

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler principal para requisições MCP JSON-RPC 2.0.

        Args:
            request: Requisição JSON-RPC 2.0

        Returns:
            Resposta JSON-RPC 2.0
        """
        try:
            # Validar requisição JSON-RPC 2.0 básica
            if not isinstance(request, dict):
                raise InvalidRequestError("Request must be a JSON object", "request")

            # Verificar versão JSON-RPC 2.0
            if request.get("jsonrpc") != "2.0":
                raise InvalidRequestError("JSON-RPC version must be '2.0'", "jsonrpc")

            method = request.get("method")
            params = request.get("params", {})
            request_id = request.get("id")

            if not method:
                raise ValidationError("Method is required", "method")

            logger.info(f"MCP Handler: processing method {method}")

            # Roteamento para handlers específicos
            if method == "initialize":
                # SPEC-GLPI-ENHANCE-001/F05: Server Instructions + capabilities
                # @MX:NOTE: the instructions must describe the tools that were
                # actually registered, never a fixed roster.
                # @MX:REASON: announcing glpi_manage_ticket_ai_analysis while it
                # is gated off makes the model call a tool that does not exist
                # and then narrate the failure to the user as a GLPI problem.
                n_tools = len(self.tools)
                ai_on = "glpi_manage_ticket_ai_analysis" in self.tools
                n_ticket_tools = 3 if ai_on else 2
                ai_tool_line = (
                    "- glpi_manage_ticket_ai_analysis: Analise IA em 3 passos sequenciais (trigger -> get_result -> publish).\n"
                    if ai_on
                    else ""
                )
                ai_example_block = (
                    "- Analise IA de um ticket (fluxo obrigatorio em 3 passos):\n"
                    "    1) glpi_manage_ticket_ai_analysis(action='trigger', ticket_id=1234)  # retorna job_id\n"
                    "    2) glpi_manage_ticket_ai_analysis(action='get_result', job_id=<job>)  # retorna response\n"
                    "    3) glpi_manage_ticket_ai_analysis(action='publish', job_id=<job>, response=<resp>)  # publica\n"
                    if ai_on
                    else ""
                )
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "mcp-glpi", "version": __version__},
                    "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                    "instructions": (
                        f"Servidor MCP GLPI - Gerenciamento de chamados, ativos, usuarios, ITIL e webhooks ({n_tools} tools)\n\n"
                        "=== CATEGORIAS DE TOOLS ===\n\n"
                        f"TICKETS ({n_ticket_tools} tools):\n"
                        "- glpi_search_helpdesk_tickets: Listar/buscar chamados por status, prioridade, urgencia, tecnico, grupo, solicitante, categoria, texto e periodo. Aceita open_only e ordenacao (sort_by/order). Sem filtros = 10 mais recentes.\n"
                        "- glpi_manage_ticket_operations: Operacoes sobre UM chamado (action: get/get_by_number/create/update/delete/assign/assign_group/close/resolve/add_followup/add_task/add_document/link_tickets/request_validation/answer_validation/get_timeline/get_tasks/get_validations/get_followups/get_history/get_stats/find_similar).\n"
                        f"{ai_tool_line}\n"
                        "ATIVOS (2 tools):\n"
                        "- glpi_search_asset_inventory: Buscar equipamentos, patrimonio (scope: all/computers/monitors/software/devices/reservations/stats).\n"
                        "- glpi_manage_asset_operations: Operacoes sobre UM ativo (action: get/get_details/create/update/delete/get_reservations/create_reservation/update_reservation).\n\n"
                        "ADMIN (2 tools):\n"
                        "- glpi_search_admin_resources: Buscar usuarios, grupos, entidades, localizacoes (resource: users/groups/entities/locations).\n"
                        "- glpi_manage_admin_resources: Operacoes sobre UM recurso (resource + action: get/create/update/delete).\n\n"
                        "WEBHOOKS (2 tools):\n"
                        "- glpi_search_webhook_integrations: Listar webhooks, stats, entregas (scope: list/stats/deliveries).\n"
                        "- glpi_manage_webhook_integrations: CRUD + controle (action: get/create/update/delete/test/trigger/enable/disable/retry).\n\n"
                        "BRIDGE (4 tools):\n"
                        "- glpi_list_available_resources: Catalogo de URIs estaticas (entidades, status, categorias, prioridades).\n"
                        "- glpi_read_resource_by_uri: Le uma URI especifica (glpi://entities, glpi://ticket-status, glpi://ticket-categories, glpi://priorities).\n"
                        "- glpi_list_available_prompts: Catalogo dos 15 relatorios pre-fabricados (SLA, tendencias, produtividade, ROI).\n"
                        "- glpi_get_prompt_template: EXECUTA um relatorio nomeado e retorna DADOS reais. NAO retorna template em branco.\n\n"
                        "ITIL ALEM DO INCIDENTE (2 tools):\n"
                        "- glpi_search_itil_records: Buscar problemas, mudancas, projetos, contratos e fornecedores (record_type). Aceita count_only para so o total.\n"
                        "- glpi_manage_itil_records: Operacoes sobre UM registro ITIL (record_type + action: get/create/update/delete/add_followup/get_followups/link_ticket).\n\n"
                        "BUSCA POR CRITERIOS LIVRES (1 tool):\n"
                        "- glpi_search_records_by_criteria: Consulta livre em QUALQUER itemtype quando as tools acima nao atenderem (scope: search/count/fields). Campos por NOME; scope=fields descobre os campos disponiveis.\n\n"
                        "KNOWLEDGE (2 tools):\n"
                        "- glpi_search_knowledge_unified: PREFERIDA — busca semantica (pgvector + RRF) em chamados resolvidos + help oficial + comunidade. Use para duvidas, mensagens de erro, sintomas, how-to.\n"
                        "- glpi_search_knowledge_articles: Apenas artigos KB nativos via REST do GLPI. Use SOMENTE quando precisar especificamente da base nativa (raro). Default = unified.\n\n"
                        "=== FORMATO ===\n"
                        "- search_*: limit (padrao 10, max 50), offset, filtros especificos. Sem filtros = lista os mais recentes.\n"
                        "- manage_*: action (obrigatorio), IDs inteiros (ticket_id, asset_id, etc).\n"
                        "- Datas: aceita ISO YYYY-MM-DD, BR DD/MM/YYYY, ISO com hora, e palavras 'hoje'/'today'/'ontem'/'yesterday'/'amanha'/'tomorrow'. Normalizado automaticamente — use o formato mais natural.\n"
                        "- Todas as respostas em Markdown (tabelas e detalhes).\n\n"
                        "=== TENANT / ENTITY ===\n"
                        "- O token MCP ja fixa o cliente/tenant. NAO preencha entity_id nem entity_name "
                        "nas chamadas comuns — passe vazio que o GLPI retorna tudo do escopo do token.\n"
                        "- So passe entity_id/entity_name se o usuario pedir explicitamente para filtrar "
                        "uma sub-entidade ou filial especifica dentro do cliente.\n"
                        "- Para 'chamados de hoje', 'tickets abertos', 'ativos do cliente': chame search_* "
                        "SEM entity_id e SEM entity_name.\n\n"
                        "=== EXEMPLOS DE CHAMADA (use o formato de data mais natural — sera normalizado) ===\n"
                        "- Chamados criados hoje (forma simples com keyword):\n"
                        "    glpi_search_helpdesk_tickets(date_after='hoje', date_before='hoje')\n"
                        "- Chamados criados ontem (formato BR):\n"
                        "    glpi_search_helpdesk_tickets(date_after='ontem', date_before='ontem')\n"
                        "- Chamados em aberto (qualquer data):\n"
                        "    glpi_search_helpdesk_tickets(status='new')\n"
                        "- Chamados abertos de janeiro (formato BR DD/MM/YYYY):\n"
                        "    glpi_search_helpdesk_tickets(status='new', date_after='01/01/2026', date_before='31/01/2026', limit=50)\n"
                        "- Buscar 'impressora nao imprime' no titulo/descricao:\n"
                        "    glpi_search_helpdesk_tickets(query='impressora nao imprime')\n"
                        "- Detalhe completo do ticket 1234:\n"
                        "    glpi_manage_ticket_operations(action='get', ticket_id=1234)\n"
                        "- Abrir chamado novo:\n"
                        "    glpi_manage_ticket_operations(action='create', title='Titulo curto', description='Detalhes completos')\n"
                        "- Buscar solucao para erro de banco:\n"
                        "    glpi_search_knowledge_unified(query='ORA-00942 table does not exist')\n"
                        "- Rodar relatorio de SLA dos ultimos 30 dias:\n"
                        "    glpi_get_prompt_template(name='glpi_sla_performance', arguments={'period_days': 30})\n"
                        f"{ai_example_block}\n"
                        "=== WORKFLOWS COMUNS ===\n"
                        "- 'Quantos chamados abertos hoje?': search_helpdesk_tickets com date_after=hoje + date_before=hoje. Conte os retornados (campo 'total' do paginador).\n"
                        "- 'Encontrar solucao para erro X': PRIMEIRO tente search_knowledge_unified(query=erro). NAO use search_knowledge_articles direto.\n"
                        "- 'Atribuir ticket Y ao tecnico Z': search_admin_resources(resource='users', query='nome Z') para pegar user_id; depois manage_ticket_operations(action='assign', ticket_id=Y, user_id=<id>).\n"
                        "- 'Listar ativos do cliente': search_asset_inventory() sem entity (token ja fixa cliente).\n"
                        "- 'Tickets parecidos com o 1234': manage_ticket_operations(action='find_similar', ticket_id=1234).\n\n"
                        "=== DICAS ===\n"
                        "- Comece com search_ para descobrir recursos, depois manage_ para detalhes/acao.\n"
                        "- Use resources (glpi://entities, glpi://ticket-status) para dados estaticos.\n"
                        "- Quando em duvida sobre filtros, chame search_ SEM parametros primeiro para ver o que existe.\n\n"
                        "=== COMO USAR OS PROMPTS (glpi_get_prompt_template) ===\n"
                        "- Fluxo: 1) glpi_list_available_prompts para ver os 15 modelos e seus argumentos; "
                        "2) glpi_get_prompt_template(name=..., arguments={...}).\n"
                        "- period_days e min_occurrences sao INTEIROS em dias/ocorrencias (ex: 30, 90).\n"
                        "- entity_name aqui e opcional. Para deployments single-tenant (uma por cliente), OMITA — relatorio sai automaticamente do escopo do token.\n"
                        "- Prompts que dependem de ticket_id/username/search_term exigem esse argumento.\n"
                        "- IMPORTANTE: os prompts retornam DADOS REAIS do GLPI. Quando uma metrica nao existe "
                        "nesta instancia (custo monetario, NPS/CSAT, ROI financeiro, tempo medio por tecnico), "
                        "o prompt informa 'nao disponivel' em vez de inventar numeros. NUNCA apresente esses "
                        "campos como se fossem reais; repasse o aviso de indisponibilidade ao usuario.\n"
                        "- Prompts de checklist (onboarding, hardware_request, change_management) sao modelos "
                        "de processo (texto-guia), nao consultas de dados."
                    ),
                }
            elif method == "tools/list":
                result = await self.handle_list_tools()
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                if not tool_name:
                    raise ValidationError("Tool name is required", "name")
                # Protocol errors: the call never became a tool execution.
                if tool_name not in self.tools:
                    raise MethodNotFoundError(tool_name)
                if arguments is None:
                    arguments = {}
                if not isinstance(arguments, dict):
                    raise ValidationError("Arguments must be a JSON object", "arguments")

                # @MX:ANCHOR: a failing tool answers INSIDE the result (isError), never as JSON-RPC error.
                # @MX:REASON: MCP separates protocol errors from tool execution errors; the model reads
                # the latter to fix its call. Gateways (ContextForge v1.0.11, measured 28/09/2026) turn an
                # upstream JSON-RPC error into "unhandled errors in a TaskGroup", so "ticket 999 does not
                # exist" or "limit must be an integer" never reached the agent.
                try:
                    result = await self.handle_call_tool(tool_name, arguments)
                except GLPIError as e:
                    result = tool_error_result(describe_failure(e))
            elif method == "resources/list":
                # SPEC-GLPI-ENHANCE-001/F06: MCP Resources
                from src.resources import list_resources
                result = {"resources": list_resources()}
            elif method == "resources/read":
                # SPEC-GLPI-ENHANCE-001/F06: Read specific resource.
                # read_resource uses glpi_client internally (handles auth via
                # SessionManager context vars), so we don't need to pass a session.
                from src.resources import read_resource
                uri = params.get("uri", "")
                try:
                    resource_content = await read_resource(uri)
                    result = {"contents": [resource_content]}
                except ValueError as e:
                    raise InvalidRequestError(str(e))
            elif method == "prompts/list":
                # SPEC-GLPI-ENHANCE-001/F07: Native prompts/list via PROMPTS_CATALOG
                from src.prompts_handlers.prompts import PROMPTS_CATALOG
                result = {"prompts": PROMPTS_CATALOG}
            elif method == "prompts/get":
                # SPEC-GLPI-ENHANCE-001/F07: Native prompts/get via handler
                from src.prompts_handlers.prompts import handle_get_prompt
                prompt_name = params.get("name")
                prompt_args = params.get("arguments", {})
                prompt_result = await handle_get_prompt(name=prompt_name, arguments=prompt_args)
                result = {
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": json.dumps(prompt_result, ensure_ascii=False, default=str) if isinstance(prompt_result, dict) else str(prompt_result),
                            },
                        }
                    ]
                }
            elif method == "notifications/initialized" or method == "initialized":
                # MCP Protocol: confirmação de inicialização (notificação, retorna vazio)
                result = {}
            else:
                raise MethodNotFoundError(method)

            # Construir resposta JSON-RPC 2.0
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}

            logger.info(f"MCP Handler: method {method} completed successfully")
            return response

        except (
            GLPIError,
            NotFoundError,
            ValidationError,
            SimilarityError,
            MethodNotFoundError,
        ) as e:
            # Erros esperados - mapear para JSON-RPC error
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": e.code
                    if hasattr(e, "code") and e.code < 0
                    else HTTP_TO_JSONRPC.get(e.code, -32603)
                    if hasattr(e, "code")
                    else -32603,
                    "message": e.message,
                    "data": {"type": type(e).__name__, "details": str(e)},
                },
            }

            logger.error(f"MCP Handler error: {e.message}")
            return error_response

        except Exception as e:
            # Erros inesperados
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": {"type": "InternalServerError", "details": str(e)},
                },
            }

            logger.error(f"MCP Handler unexpected error: {e}")
            return error_response

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Obtém informações de uma tool específica.

        Args:
            tool_name: Nome da tool

        Returns:
            Informações da tool ou None se não existir
        """
        return self.tools.get(tool_name)

    def get_tools_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Obtém tools por categoria.

        Args:
            category: Categoria (tickets, assets, admin, webhooks)

        Returns:
            Lista de tools da categoria
        """
        return [tool for tool in self.tools.values() if tool["category"] == category]

    def get_handler_stats(self) -> Dict[str, Any]:
        """
        Obtém estatísticas do handler.

        Returns:
            Estatísticas detalhadas
        """
        categories = {}
        for tool in self.tools.values():
            category = tool["category"]
            categories[category] = categories.get(category, 0) + 1

        return {
            "total_tools": len(self.tools),
            "categories": categories,
            "available_methods": ["tools/list", "tools/call"],
            "protocol": "JSON-RPC 2.0",
            "last_updated": datetime.now().isoformat(),
        }


# Instância global do handler MCP
mcp_handler = MCPHandler()

# Alias de compatibilidade legado
ToolHandler = MCPHandler
