#!/usr/bin/env python3
"""
Transform GLPI MCP handlers.py:
1. Rename all 68 tools with glpi_ prefix
2. Rewrite all descriptions (250-350 chars, PT-BR, GLPI >=2x, substantive-key first)
3. Add enums, PT-BR param descriptions, ISO 8601 date formats
"""

import re

# === NAME MAPPING ===
NAME_MAP = {
    # TICKETS (18)
    "list_tickets": "glpi_list_tickets",
    "get_ticket": "glpi_get_ticket",
    "get_ticket_by_id": "glpi_get_ticket_by_id",
    "get_ticket_by_number": "glpi_get_ticket_by_number",
    "create_ticket": "glpi_create_ticket",
    "update_ticket": "glpi_update_ticket",
    "delete_ticket": "glpi_delete_ticket",
    "assign_ticket": "glpi_assign_ticket",
    "close_ticket": "glpi_close_ticket",
    "find_similar_tickets": "glpi_find_similar_tickets",
    "search_similar_tickets": "glpi_search_similar_tickets",
    "search_tickets": "glpi_search_tickets",
    "get_ticket_stats": "glpi_get_ticket_stats",
    "get_ticket_history": "glpi_get_ticket_history",
    "add_ticket_followup": "glpi_add_ticket_followup",
    "post_private_note": "glpi_post_private_note",
    "get_ticket_followups": "glpi_get_ticket_followups",
    "resolve_ticket": "glpi_resolve_ticket",
    # ASSETS (20)
    "list_assets": "glpi_list_assets",
    "get_asset": "glpi_get_asset",
    "create_asset": "glpi_create_asset",
    "update_asset": "glpi_update_asset",
    "delete_asset": "glpi_delete_asset",
    "search_assets": "glpi_search_assets",
    "get_asset_reservations": "glpi_get_asset_reservations",
    "create_reservation": "glpi_create_reservation",
    "list_reservations": "glpi_list_reservations",
    "list_reservable_items": "glpi_list_reservable_items",
    "update_reservation": "glpi_update_reservation",
    "get_asset_stats": "glpi_get_asset_stats",
    "list_computers": "glpi_list_computers",
    "get_computer_details": "glpi_get_computer_details",
    "list_monitors": "glpi_list_monitors",
    "get_monitor": "glpi_get_monitor",
    "list_software": "glpi_list_software",
    "get_software": "glpi_get_software",
    "list_devices": "glpi_list_devices",
    "get_device": "glpi_get_device",
    # ADMIN (13)
    "list_users": "glpi_list_users",
    "search_users": "glpi_search_users",
    "get_user": "glpi_get_user",
    "create_user": "glpi_create_user",
    "update_user": "glpi_update_user",
    "delete_user": "glpi_delete_user",
    "list_groups": "glpi_list_groups",
    "get_group": "glpi_get_group",
    "create_group": "glpi_create_group",
    "list_entities": "glpi_list_entities",
    "get_entity": "glpi_get_entity",
    "list_locations": "glpi_list_locations",
    "get_location": "glpi_get_location",
    # WEBHOOKS (12)
    "list_webhooks": "glpi_list_webhooks",
    "get_webhook": "glpi_get_webhook",
    "create_webhook": "glpi_create_webhook",
    "update_webhook": "glpi_update_webhook",
    "delete_webhook": "glpi_delete_webhook",
    "test_webhook": "glpi_test_webhook",
    "get_webhook_deliveries": "glpi_get_webhook_deliveries",
    "trigger_webhook": "glpi_trigger_webhook",
    "get_webhook_stats": "glpi_get_webhook_stats",
    "enable_webhook": "glpi_enable_webhook",
    "disable_webhook": "glpi_disable_webhook",
    "retry_failed_deliveries": "glpi_retry_failed_deliveries",
    # AI (3)
    "trigger_ai_analysis": "glpi_trigger_ai_analysis",
    "get_ai_analysis_result": "glpi_get_ai_analysis_result",
    "publish_ai_response": "glpi_publish_ai_response",
    # PROMPTS (2) - CRUD reorder
    "prompts_list": "glpi_list_prompts",
    "prompts_get": "glpi_get_prompt",
}

# === NEW DESCRIPTIONS (250-350 chars, PT-BR, GLPI >=2x, substantive-key first) ===
NEW_DESCRIPTIONS = {
    # TICKETS (18)
    "glpi_list_tickets": "Chamados, tickets e incidentes no GLPI — listagem com filtros por status, entidade e paginação. Use quando precisar consultar solicitações abertas, pendentes ou fechadas de um cliente no GLPI. Retorna lista com id, título, status, prioridade e data de abertura. Consulta somente leitura.",
    "glpi_get_ticket": "Chamado e seus detalhes completos no GLPI — consulta por ID com todos os campos do ticket. Use quando já possuir o ID do chamado e precisar de informações detalhadas no GLPI. Retorna id, título, descrição, status, prioridade, urgência, datas, solicitante, entidade e SLA.",
    "glpi_get_ticket_by_id": "Chamado por ID numérico no GLPI — obtém detalhes completos de um ticket, incidente ou requisição específica. Use quando tiver o ID do chamado e precisar de todos os campos no GLPI. Retorna os mesmos dados de glpi_get_ticket. Consulta somente leitura.",
    "glpi_get_ticket_by_number": "Chamado por número (string) no GLPI — busca ticket pelo campo número, que pode diferir do ID interno. Use quando o usuário mencionar 'chamado #X' ou 'ticket número X' no GLPI. Retorna detalhes completos do incidente ou requisição. Em alguns ambientes GLPI, número e ID são distintos.",
    "glpi_create_ticket": "Chamado, incidente ou requisição no GLPI — criação de novo ticket com título, descrição e prioridade. Use quando precisar abrir uma nova solicitação ou demanda de suporte no GLPI. Retorna ID do chamado criado. Aceita entity_name para vincular ao cliente correto.",
    "glpi_update_ticket": "Chamado e suas propriedades no GLPI — atualização de status, prioridade ou técnico atribuído em ticket existente. Use quando precisar modificar dados de um incidente ou requisição no GLPI. Retorna o chamado atualizado. Não altera histórico de acompanhamentos.",
    "glpi_delete_ticket": "Chamado e remoção permanente no GLPI — exclusão definitiva de um ticket, incidente ou requisição do sistema. Use apenas quando for necessário remover completamente um chamado do GLPI. OPERAÇÃO DESTRUTIVA e irreversível. Requer ticket_id obrigatório.",
    "glpi_assign_ticket": "Chamado e atribuição de técnico no GLPI — vincula um ticket a um usuário responsável pelo atendimento. Use quando precisar distribuir ou reatribuir incidentes e requisições a técnicos no GLPI. Requer ticket_id e user_id do técnico. Não altera status do chamado.",
    "glpi_close_ticket": "Chamado e encerramento com resolução no GLPI — fecha um ticket registrando a solução aplicada. Use quando o incidente ou requisição estiver resolvido e precisar registrar a resolução final no GLPI. Muda status para fechado (5). Diferente de glpi_resolve_ticket que marca solucionado (4).",
    "glpi_find_similar_tickets": "Chamados similares no GLPI — busca tickets com problemas parecidos usando algoritmo de similaridade textual. Use quando precisar encontrar incidentes ou requisições semelhantes para reutilizar soluções no GLPI. Aceita threshold (0-1) para ajustar sensibilidade. Retorna lista ranqueada por score.",
    "glpi_search_similar_tickets": "Chamados similares no GLPI — versão simplificada da busca por similaridade textual de tickets e incidentes. Use quando precisar localizar solicitações parecidas sem configurar threshold no GLPI. Diferente de glpi_find_similar_tickets que aceita threshold customizado. Retorna lista de tickets semelhantes.",
    "glpi_search_tickets": "Chamados e busca textual no GLPI — pesquisa tickets por palavras-chave em título e conteúdo. Use quando precisar localizar incidentes, requisições ou solicitações por termos específicos no GLPI. Aceita filtro por entidade. Retorna lista paginada. Mínimo 2 caracteres na query.",
    "glpi_get_ticket_stats": "Estatísticas de chamados no GLPI — métricas agregadas por status, prioridade e entidade. Use quando precisar de relatórios, dashboards ou análise quantitativa de tickets e incidentes no GLPI. Retorna totais por status (abertos, pendentes, resolvidos, fechados) e por prioridade. Consulta somente leitura.",
    "glpi_get_ticket_history": "Histórico de alterações de chamado no GLPI — rastreamento completo de mudanças em um ticket. Use quando precisar auditar quem alterou o quê e quando em um incidente ou requisição no GLPI. Retorna mudanças de status, atribuições, atualizações de campos com autor e timestamp.",
    "glpi_add_ticket_followup": "Acompanhamento de chamado no GLPI — adiciona comentário ou interação a um ticket existente. Use quando precisar registrar comunicações, atualizações ou notas em incidentes e requisições no GLPI. Aceita is_private para notas visíveis apenas a técnicos. Requer ticket_id e content.",
    "glpi_post_private_note": "Nota privada em chamado no GLPI — adiciona anotação interna visível apenas para técnicos e equipe de suporte. Use quando precisar registrar observações internas que o solicitante não deve ver em tickets do GLPI. Diferente de glpi_add_ticket_followup com is_private. Requer ticket_id e content.",
    "glpi_get_ticket_followups": "Acompanhamentos de chamado no GLPI — lista todos os comentários e interações de um ticket específico. Use quando precisar consultar o histórico de comunicações de um incidente ou requisição no GLPI. Retorna lista com id, conteúdo, data, autor e flag de privacidade. Consulta somente leitura.",
    "glpi_resolve_ticket": "Resolução de chamado no GLPI — registra a solução técnica de um ticket, marcando como solucionado (status 4). Use quando o incidente tiver solução definida mas ainda aguardar validação do solicitante no GLPI. Diferente de glpi_close_ticket que fecha diretamente (status 5). Requer ticket_id e solution.",
    # ASSETS (20)
    "glpi_list_assets": "Ativos de TI, equipamentos e patrimônio no GLPI — listagem com filtros por tipo, entidade e paginação. Use quando precisar consultar o inventário de computadores, monitores, impressoras ou periféricos no GLPI. Retorna lista com id, nome, serial, status e localização. Consulta somente leitura.",
    "glpi_get_asset": "Ativo e detalhes completos no GLPI — consulta equipamento específico por tipo e ID. Use quando já possuir o ID e tipo do patrimônio e precisar de informações detalhadas no GLPI. Retorna id, nome, serial, status, localização, fabricante, modelo e usuário responsável pelo equipamento.",
    "glpi_create_asset": "Ativo, equipamento ou patrimônio no GLPI — cadastro de novo item no inventário de TI. Use quando precisar registrar um computador, monitor, impressora ou periférico no GLPI. Requer asset_type e nome obrigatórios. Aceita serial, entidade e localização. Retorna ID do ativo criado.",
    "glpi_update_asset": "Ativo e atualização de propriedades no GLPI — modifica dados de equipamento ou patrimônio existente no inventário. Use quando precisar alterar nome, serial, status ou localização de um item de TI no GLPI. Requer asset_type e asset_id. Retorna o ativo atualizado com os campos modificados.",
    "glpi_delete_asset": "Ativo e remoção permanente no GLPI — exclusão definitiva de equipamento ou patrimônio do inventário de TI. Use apenas quando for necessário remover completamente um item do GLPI. OPERAÇÃO DESTRUTIVA e irreversível. Requer asset_type e asset_id obrigatórios.",
    "glpi_search_assets": "Ativos e busca inteligente no GLPI — Smart Search v2.0 com pesquisa em nome, serial, contact e usuário vinculado. Use quando precisar localizar equipamentos ou patrimônio por texto livre no GLPI. FALLBACK: se o usuário foi deletado (sync LDAP), busca automaticamente em deletados.",
    "glpi_get_asset_reservations": "Reservas de ativo no GLPI — consulta agendamentos de um equipamento específico por tipo e ID. Use quando precisar verificar disponibilidade ou ocupação de um patrimônio reservável no GLPI. Retorna lista de reservas com datas, usuário e comentário. Consulta somente leitura.",
    "glpi_create_reservation": "Reserva de ativo no GLPI — agendamento de uso de equipamento com data início e fim em formato ISO 8601. Use quando precisar reservar computador, monitor ou periférico para um período específico no GLPI. Valida conflitos automaticamente. Requer asset_type, asset_id, start_date e end_date.",
    "glpi_list_reservations": "Reservas de ativos no GLPI — listagem de todos os agendamentos de equipamentos e patrimônio com filtros. Use quando precisar consultar reservas ativas de dispositivos no GLPI. Retorna id, ativo, usuário, período e status de cada reserva. Aceita filtro por entidade. Consulta somente leitura.",
    "glpi_list_reservable_items": "Itens reserváveis no GLPI — lista ativos habilitados para reserva no sistema de patrimônio. Use quando precisar saber quais equipamentos e dispositivos estão configurados como reserváveis no GLPI. Nem todo ativo é reservável — precisa ser habilitado pelo administrador. Aceita filtro por entidade.",
    "glpi_update_reservation": "Reserva e atualização de agendamento no GLPI — modifica datas ou comentário de uma reserva de equipamento existente. Use quando precisar alterar período ou detalhes de uso de um ativo no GLPI. Requer reservation_id obrigatório. Aceita start_date e end_date em formato ISO 8601.",
    "glpi_get_asset_stats": "Estatísticas de ativos no GLPI — métricas agregadas por tipo de equipamento, status, localização e fabricante. Use quando precisar de relatórios quantitativos do inventário de patrimônio e dispositivos no GLPI. Aceita filtro por entidade. Retorna totais categorizados. Consulta somente leitura.",
    "glpi_list_computers": "Computadores e dados enriquecidos no GLPI — listagem com memória, CPU, AnyDesk, contact e informações do usuário em uma única chamada. Use quando precisar consultar máquinas com detalhes de hardware no GLPI. NÃO use glpi_get_computer_details para listar — esta tool já traz dados completos.",
    "glpi_get_computer_details": "Computador e detalhes granulares no GLPI — componentes individuais de memória, CPU, discos, rede, sistema operacional e software instalado. Use quando precisar de informações detalhadas de UMA máquina específica no GLPI. Para listar múltiplos computadores, use glpi_list_computers.",
    "glpi_list_monitors": "Monitores, telas e displays no GLPI — listagem do inventário de vídeo com filtros por entidade. Use quando precisar consultar monitores cadastrados no patrimônio de TI do GLPI. Retorna id, nome, serial, fabricante, modelo e tamanho em polegadas. Consulta somente leitura.",
    "glpi_get_monitor": "Monitor e detalhes completos no GLPI — consulta display específico por ID com todos os campos do patrimônio. Use quando precisar de informações detalhadas de um monitor ou tela do inventário no GLPI. Retorna id, nome, serial, fabricante, modelo, tamanho, comentário, entidade e localização.",
    "glpi_list_software": "Softwares e licenças no GLPI — listagem de programas cadastrados no inventário com contagem de instalações. Use quando precisar consultar aplicativos, programas ou sistemas do parque de TI no GLPI. Retorna id, nome, publisher, validade da licença e total de instalações. Consulta somente leitura.",
    "glpi_get_software": "Software e detalhes completos no GLPI — consulta programa específico por ID com versões e instalações ativas. Use quando precisar de informações detalhadas de um aplicativo ou sistema cadastrado no inventário do GLPI. Retorna id, nome, publisher, versões, instalações e licenças vinculadas.",
    "glpi_list_devices": "Dispositivos de rede, telefones e periféricos no GLPI — listagem por tipo de equipamento do inventário. Use quando precisar consultar switches, roteadores, telefones ou periféricos cadastrados no GLPI. Aceita device_type para filtrar. Retorna lista com id, nome, serial e entidade.",
    "glpi_get_device": "Dispositivo e detalhes específicos no GLPI — consulta equipamento de rede, telefone ou periférico por tipo e ID. Use quando precisar de informações completas de um switch, roteador ou periférico no inventário do GLPI. Requer device_type e device_id obrigatórios. Retorna dados específicos.",
    # ADMIN (13)
    "glpi_list_users": "Usuários, colaboradores e técnicos no GLPI — listagem com filtros por entidade, grupo, perfil e status. Use quando precisar consultar pessoas cadastradas, membros de equipe ou funcionários no GLPI. Retorna id, login, nome, sobrenome, email e status ativo. Consulta somente leitura.",
    "glpi_search_users": "Usuários e busca completa no GLPI — pesquisa por nome, sobrenome, email ou username com todos os 20+ campos. Use quando precisar localizar colaboradores, técnicos ou funcionários por qualquer critério no GLPI. FALLBACK: se nenhum ativo encontrado, busca automaticamente em deletados (sync AD/LDAP).",
    "glpi_get_user": "Usuário e detalhes completos no GLPI — consulta colaborador específico por ID com todos os campos disponíveis. Use quando já possuir o ID do técnico ou funcionário e precisar de informações detalhadas no GLPI. Retorna dados pessoais, contatos, localização, cargo, perfil e status.",
    "glpi_create_user": "Usuário, colaborador ou técnico no GLPI — cadastro de nova pessoa no sistema com dados completos. Use quando precisar criar um novo membro, funcionário ou conta de acesso no GLPI. Requer name (login) obrigatório. Aceita dados pessoais, contato, perfil, grupo e tipo de autenticação (Local, LDAP, Mail).",
    "glpi_update_user": "Usuário e atualização de dados no GLPI — modifica informações de colaborador ou técnico existente no cadastro. Use quando precisar alterar nome, email, telefone, cargo ou status de uma pessoa no GLPI. Requer user_id obrigatório. Retorna usuário atualizado com campos modificados.",
    "glpi_delete_user": "Usuário e remoção no GLPI — exclusão ou desativação de colaborador, técnico ou conta do sistema. Use quando precisar remover acesso de um funcionário ou membro no GLPI. Pode ser desativação lógica ou exclusão física conforme configuração do ambiente. OPERAÇÃO DESTRUTIVA. Requer user_id.",
    "glpi_list_groups": "Grupos, equipes e times no GLPI — listagem de agrupamentos de usuários com filtros por entidade. Use quando precisar consultar departamentos, setores ou equipes técnicas cadastradas no GLPI. Retorna id, nome, descrição, entidade e quantidade de membros. Consulta somente leitura.",
    "glpi_get_group": "Grupo e detalhes completos no GLPI — consulta equipe específica por ID com lista de membros e configurações. Use quando precisar de informações detalhadas de um departamento, setor ou time técnico no GLPI. Retorna id, nome, descrição, entidade e lista de usuários membros.",
    "glpi_create_group": "Grupo, equipe ou departamento no GLPI — criação de novo agrupamento de usuários para organização do suporte. Use quando precisar criar um time, setor ou departamento para organizar colaboradores e técnicos no GLPI. Requer nome obrigatório. Aceita descrição e entidade.",
    "glpi_list_entities": "Entidades, clientes e organizações no GLPI — listagem de empresas cadastradas com hierarquia e filtros. Use quando precisar consultar clientes, filiais ou unidades de negócio no GLPI. Retorna id, nome, caminho completo, entidade pai, endereço e telefone. Aceita filtro por parent_id.",
    "glpi_get_entity": "Entidade e detalhes completos no GLPI — consulta cliente ou organização específica por ID com configurações. Use quando precisar de informações detalhadas de uma empresa, filial ou unidade cadastrada no GLPI. Retorna id, nome, caminho, entidade pai, endereço, contatos e configurações de SLA.",
    "glpi_list_locations": "Localizações, escritórios e filiais no GLPI — listagem de endereços e sites cadastrados no patrimônio. Use quando precisar consultar salas, prédios ou filiais vinculadas ao inventário de TI no GLPI. Retorna id, nome, caminho completo, entidade, endereço, prédio e sala. Consulta somente leitura.",
    "glpi_get_location": "Localização e detalhes completos no GLPI — consulta endereço ou site específico por ID com coordenadas. Use quando precisar de informações detalhadas de um escritório, prédio ou filial cadastrada no GLPI. Retorna id, nome, caminho, entidade, endereço, latitude, longitude, prédio e sala.",
    # WEBHOOKS (12)
    "glpi_list_webhooks": "Webhooks e integrações no GLPI — listagem de endpoints configurados para notificações automáticas de eventos. Use quando precisar consultar integrações ativas ou inativas de callbacks HTTP no GLPI. Retorna id, nome, URL de destino, tipo de evento e status. Aceita filtro por is_active.",
    "glpi_get_webhook": "Webhook e detalhes completos no GLPI — consulta integração específica por ID com estatísticas de entrega. Use quando precisar de informações detalhadas de um endpoint de callback configurado no GLPI. Retorna id, nome, URL, tipo de evento, secret, headers e delivery_stats.",
    "glpi_create_webhook": "Webhook e nova integração no GLPI — cadastro de endpoint para receber notificações automáticas de eventos. Use quando precisar configurar um callback HTTP para tickets, ativos ou outros eventos no GLPI. Requer nome, URL de destino e tipo de evento. Aceita secret para assinatura HMAC.",
    "glpi_update_webhook": "Webhook e atualização de integração no GLPI — modifica configuração de endpoint de notificação existente. Use quando precisar alterar URL, nome ou status de ativação de um callback HTTP no GLPI. Requer webhook_id obrigatório. Aceita name, url e is_active para ativação ou desativação.",
    "glpi_delete_webhook": "Webhook e remoção permanente no GLPI — exclusão definitiva de integração de notificação automática do sistema. Use apenas quando for necessário remover completamente um endpoint de callback do GLPI. OPERAÇÃO DESTRUTIVA e irreversível. Requer webhook_id obrigatório.",
    "glpi_test_webhook": "Webhook e teste de conectividade no GLPI — envia payload de verificação para confirmar funcionamento do endpoint. Use quando precisar validar se uma integração de callback está respondendo corretamente no GLPI. Requer webhook_id. Retorna status HTTP da entrega de teste.",
    "glpi_get_webhook_deliveries": "Entregas de webhook no GLPI — histórico de tentativas de notificação de um endpoint específico configurado. Use quando precisar diagnosticar falhas ou verificar entregas de integrações no GLPI. Retorna tentativas, status HTTP, response_code e detalhes de erro. Consulta somente leitura.",
    "glpi_trigger_webhook": "Webhook e disparo manual no GLPI — envia evento customizado para endpoints de integração configurados. Use quando precisar testar integrações ou disparar notificações manualmente no GLPI. Requer event_type obrigatório. Aceita payload com dados customizados para o evento disparado.",
    "glpi_get_webhook_stats": "Estatísticas de webhooks no GLPI — métricas agregadas de integrações e entregas de notificações automáticas. Use quando precisar de relatórios sobre callbacks HTTP configurados no GLPI. Retorna total configurados, ativos, entregas com sucesso e falha, e latência média. Consulta somente leitura.",
    "glpi_enable_webhook": "Webhook e ativação no GLPI — reativa um endpoint de notificação automática previamente desativado. Use quando precisar religar uma integração de callback que estava pausada no GLPI. Requer webhook_id obrigatório. O webhook volta a receber eventos conforme configuração original.",
    "glpi_disable_webhook": "Webhook e desativação temporária no GLPI — pausa um endpoint de notificação automática sem excluí-lo do sistema. Use quando precisar suspender temporariamente uma integração de callback no GLPI. Requer webhook_id. Para remoção definitiva, use glpi_delete_webhook.",
    "glpi_retry_failed_deliveries": "Entregas falhadas de webhook no GLPI — re-tentativa de notificações que não foram entregues ao endpoint de destino. Use quando o servidor estava indisponível e as entregas falharam no GLPI. Requer webhook_id obrigatório. Reprocessa todas as entregas com status de falha.",
    # AI (3)
    "glpi_trigger_ai_analysis": "Análise de IA em chamados no GLPI — dispara processamento inteligente de tickets pendentes com sugestões automáticas. Use quando precisar de categorização, priorização e sugestões de solução baseadas no histórico do GLPI. Analisa conteúdo dos incidentes e requisições pendentes.",
    "glpi_get_ai_analysis_result": "Resultado de análise de IA no GLPI — obtém sugestões geradas pelo último processamento inteligente de chamados. Use quando precisar consultar recomendações de categorização, priorização e soluções de tickets no GLPI. Retorna tickets analisados, categorias sugeridas e soluções similares.",
    "glpi_publish_ai_response": "Resposta de IA em chamado no GLPI — publica sugestão gerada por inteligência artificial como acompanhamento em um ticket. Use quando precisar adicionar resposta automatizada com marcação de origem IA em incidentes do GLPI. A resposta é adicionada como followup identificado.",
    # PROMPTS (2)
    "glpi_list_prompts": "Prompts profissionais no GLPI — catálogo de 15 modelos prontos para gestores e analistas de suporte técnico. Use quando precisar descobrir quais relatórios e análises estão disponíveis no sistema GLPI. Retorna nome, descrição, categoria (gestão/suporte), público-alvo e argumentos de cada prompt.",
    "glpi_get_prompt": "Prompt e execução de modelo no GLPI — processa um relatório ou análise específica com argumentos customizados. Use quando precisar gerar relatório de SLA, tendências, produtividade ou investigação no GLPI. Retorna resultado em formato compact (10 linhas) e detailed (Markdown completo).",
}

# Validate descriptions
errors = []
for name, desc in NEW_DESCRIPTIONS.items():
    length = len(desc)
    glpi_count = desc.lower().count("glpi")
    if length < 250 or length > 350:
        errors.append(f"  {name}: length={length} (target: 250-350)")
    if glpi_count < 2:
        errors.append(f"  {name}: GLPI mentions={glpi_count} (min: 2)")

print(f"Total descriptions: {len(NEW_DESCRIPTIONS)}")
print(f"Total name mappings: {len(NAME_MAP)}")
if errors:
    print(f"Validation warnings ({len(errors)}):")
    for e in errors:
        print(e)
else:
    print("All descriptions pass validation!")

# === PROCESS HANDLERS.PY ===
filepath = "/opt/mcp-servers/glpi/src/handlers.py"
with open(filepath, "r") as f:
    content = f.read()

# Backup
with open(filepath + ".bak", "w") as f:
    f.write(content)
print("\nBackup saved to handlers.py.bak")

# === STEP 1: Replace tool names in _register_tools() tuples ===
# Pattern: ("old_name", module.method)
for old_name, new_name in NAME_MAP.items():
    if old_name in ("prompts_list", "prompts_get"):
        continue  # Handle separately
    # Replace in tuples like ("list_tickets", ticket_tools.list_tickets)
    content = re.sub(
        rf'\("({re.escape(old_name)})"(,\s*\w+_tools\.\w+)',
        f'("{new_name}"\\2',
        content,
    )

# === STEP 2: Replace inline prompt registrations ===
content = content.replace('tools["prompts_list"]', 'tools["glpi_list_prompts"]')
content = content.replace('tools["prompts_get"]', 'tools["glpi_get_prompt"]')
content = content.replace('"name": "prompts_list"', '"name": "glpi_list_prompts"')
content = content.replace('"name": "prompts_get"', '"name": "glpi_get_prompt"')

# === STEP 3: Fix hardcoded prompts references in handle_request ===
content = content.replace(
    'handle_call_tool("prompts_list"', 'handle_call_tool("glpi_list_prompts"'
)
content = content.replace(
    'handle_call_tool("prompts_get"', 'handle_call_tool("glpi_get_prompt"'
)

# === STEP 4: Replace entire descriptions dictionary ===
# Find the descriptions dict and replace it
desc_start = content.find("descriptions = {")
if desc_start == -1:
    print("ERROR: Could not find descriptions dict!")
    exit(1)

# Find matching closing brace
brace_depth = 0
desc_end = desc_start
for idx in range(desc_start, len(content)):
    if content[idx] == "{":
        brace_depth += 1
    elif content[idx] == "}":
        brace_depth -= 1
        if brace_depth == 0:
            desc_end = idx + 1
            break

# Build new descriptions dict
indent = "            "
new_desc_lines = ["descriptions = {"]

categories_order = [
    (
        "# ============= TICKETS (18 tools) =============",
        [
            "glpi_list_tickets",
            "glpi_get_ticket",
            "glpi_get_ticket_by_id",
            "glpi_get_ticket_by_number",
            "glpi_create_ticket",
            "glpi_update_ticket",
            "glpi_delete_ticket",
            "glpi_assign_ticket",
            "glpi_close_ticket",
            "glpi_find_similar_tickets",
            "glpi_search_similar_tickets",
            "glpi_search_tickets",
            "glpi_get_ticket_stats",
            "glpi_get_ticket_history",
            "glpi_add_ticket_followup",
            "glpi_post_private_note",
            "glpi_get_ticket_followups",
            "glpi_resolve_ticket",
        ],
    ),
    (
        "\n            # ============= ASSETS (20 tools) =============",
        [
            "glpi_list_assets",
            "glpi_get_asset",
            "glpi_create_asset",
            "glpi_update_asset",
            "glpi_delete_asset",
            "glpi_search_assets",
            "glpi_get_asset_reservations",
            "glpi_create_reservation",
            "glpi_list_reservations",
            "glpi_list_reservable_items",
            "glpi_update_reservation",
            "glpi_get_asset_stats",
            "glpi_list_computers",
            "glpi_get_computer_details",
            "glpi_list_monitors",
            "glpi_get_monitor",
            "glpi_list_software",
            "glpi_get_software",
            "glpi_list_devices",
            "glpi_get_device",
        ],
    ),
    (
        "\n            # ============= ADMIN/USERS (13 tools) =============",
        [
            "glpi_list_users",
            "glpi_search_users",
            "glpi_get_user",
            "glpi_create_user",
            "glpi_update_user",
            "glpi_delete_user",
            "glpi_list_groups",
            "glpi_get_group",
            "glpi_create_group",
            "glpi_list_entities",
            "glpi_get_entity",
            "glpi_list_locations",
            "glpi_get_location",
        ],
    ),
    (
        "\n            # ============= WEBHOOKS (12 tools) =============",
        [
            "glpi_list_webhooks",
            "glpi_get_webhook",
            "glpi_create_webhook",
            "glpi_update_webhook",
            "glpi_delete_webhook",
            "glpi_test_webhook",
            "glpi_get_webhook_deliveries",
            "glpi_trigger_webhook",
            "glpi_get_webhook_stats",
            "glpi_enable_webhook",
            "glpi_disable_webhook",
            "glpi_retry_failed_deliveries",
        ],
    ),
    (
        "\n            # ============= AI TOOLS (3 tools) =============",
        [
            "glpi_trigger_ai_analysis",
            "glpi_get_ai_analysis_result",
            "glpi_publish_ai_response",
        ],
    ),
    (
        "\n            # ============= PROMPTS (2 tools) =============",
        ["glpi_list_prompts", "glpi_get_prompt"],
    ),
]

for cat_comment, tool_names in categories_order:
    new_desc_lines.append(f"{indent}{cat_comment}")
    for tname in tool_names:
        desc = NEW_DESCRIPTIONS[tname]
        new_desc_lines.append(f'{indent}"{tname}": "{desc}",')

new_desc_lines.append(f"{indent[:-4]}}}")

new_desc_text = "\n".join(new_desc_lines)
content = content[:desc_start] + new_desc_text + content[desc_end:]

# === STEP 5: Replace schema dictionary keys ===
for old_name, new_name in NAME_MAP.items():
    # Replace schema dict keys: "old_name": {
    content = re.sub(
        rf'(\s+)"{re.escape(old_name)}"(\s*:\s*\{{)', rf'\1"{new_name}"\2', content
    )

# === STEP 6: Add enums to schemas ===
# Status enum for tickets
content = content.replace(
    '"status": {"type": "string", "description": "Filtrar por status (new, processing, pending, solved, closed)"}',
    '"status": {"type": "string", "description": "Status do chamado no GLPI. Valores: new (novo), processing (em atendimento), pending (pendente), solved (solucionado), closed (fechado)", "enum": ["new", "processing", "pending", "solved", "closed"]}',
)
content = content.replace(
    '"status": {"type": "string", "description": "Novo status"}',
    '"status": {"type": "string", "description": "Novo status do chamado no GLPI. Valores: new, processing, pending, solved, closed", "enum": ["new", "processing", "pending", "solved", "closed"]}',
)

# Asset type enums
asset_enum = (
    '["Computer", "Monitor", "Printer", "NetworkEquipment", "Phone", "Peripheral"]'
)
content = content.replace(
    '"asset_type": {"type": "string", "description": "Tipo: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral"}',
    f'"asset_type": {{"type": "string", "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral", "enum": {asset_enum}}}',
)
for old_desc in [
    '"asset_type": {"type": "string", "description": "Tipo do asset"}',
]:
    content = content.replace(
        old_desc,
        f'"asset_type": {{"type": "string", "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral", "enum": {asset_enum}}}',
    )

# Device type enum
device_enum = '["NetworkEquipment", "Phone", "Peripheral"]'
content = content.replace(
    '"device_type": {"type": "string", "description": "Tipo: NetworkEquipment, Phone, Peripheral"}',
    f'"device_type": {{"type": "string", "description": "Tipo de dispositivo no GLPI. Valores: NetworkEquipment (rede), Phone (telefone), Peripheral (periférico)", "enum": {device_enum}}}',
)

# Authtype enum
content = content.replace(
    '"authtype": {"type": "integer", "description": "Tipo de autenticação (1=Local, 2=Mail, 3=LDAP)", "default": 1}',
    '"authtype": {"type": "integer", "description": "Tipo de autenticação no GLPI. Valores: 1 (local), 2 (email), 3 (LDAP/AD)", "enum": [1, 2, 3], "default": 1}',
)

# Date format specs
content = content.replace(
    '"start_date": {"type": "string", "description": "Data início (YYYY-MM-DD HH:MM)"}',
    '"start_date": {"type": "string", "description": "Data de início da reserva no formato ISO 8601 (AAAA-MM-DDTHH:mm:ss). Ex: 2025-03-15T09:00:00"}',
)
content = content.replace(
    '"end_date": {"type": "string", "description": "Data fim (YYYY-MM-DD HH:MM)"}',
    '"end_date": {"type": "string", "description": "Data de término da reserva no formato ISO 8601 (AAAA-MM-DDTHH:mm:ss). Ex: 2025-03-15T18:00:00"}',
)

# Webhook event_type enum
event_enum = '["ticket_created", "ticket_updated", "ticket_closed", "ticket_deleted", "asset_created", "asset_updated", "asset_deleted"]'
content = content.replace(
    '"event_type": {"type": "string", "description": "Tipo de evento"}',
    f'"event_type": {{"type": "string", "description": "Tipo de evento do GLPI. Valores: ticket_created, ticket_updated, ticket_closed, ticket_deleted, asset_created, asset_updated, asset_deleted", "enum": {event_enum}}}',
)
content = content.replace(
    '"event_type": {"type": "string", "description": "Tipo de evento para disparar"}',
    f'"event_type": {{"type": "string", "description": "Tipo de evento para disparar no GLPI. Valores: ticket_created, ticket_updated, ticket_closed, ticket_deleted, asset_created, asset_updated, asset_deleted", "enum": {event_enum}}}',
)

# Update inline prompt descriptions
content = re.sub(
    r'"description": "Lista todos os 15 prompts profissionais disponíveis[^"]*"',
    f'"description": "{NEW_DESCRIPTIONS["glpi_list_prompts"]}"',
    content,
)
content = re.sub(
    r'"description": "Executa um prompt específico com argumentos\. Retorna resultado em 2 formatos[^"]*"',
    f'"description": "{NEW_DESCRIPTIONS["glpi_get_prompt"]}"',
    content,
)

# === WRITE OUTPUT ===
with open(filepath, "w") as f:
    f.write(content)

print("handlers.py transformed successfully!")

# === VERIFICATION ===
with open(filepath, "r") as f:
    new_content = f.read()

new_name_count = sum(1 for n in NAME_MAP.values() if f'"{n}"' in new_content)
old_remaining = []
for old_name in NAME_MAP.keys():
    pattern = rf'(?<!glpi_)(?<!\w)"{re.escape(old_name)}"'
    matches = re.findall(pattern, new_content)
    if matches:
        old_remaining.append((old_name, len(matches)))

print("\nVerification:")
print(f"  New names found: {new_name_count}/{len(NAME_MAP)}")
print(f"  Old names remaining: {len(old_remaining)}")
if old_remaining:
    for name, count in old_remaining:
        print(f"    WARNING: '{name}' still has {count} occurrences")

# Check syntax
try:
    compile(new_content, filepath, "exec")
    print("  Syntax check: PASS")
except SyntaxError as e:
    print(f"  Syntax check: FAIL - {e}")
