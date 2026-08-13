#!/usr/bin/env bash
#
# Smoke test contra uma instancia GLPI real.
#
# Por que existe: a suite de testes simula as respostas do GLPI, entao ela nao
# consegue ver a semantica do proprio GLPI. Dois defeitos reais so apareceram
# aqui — o operador "menor que" ser inclusivo (o filtro de chamados em aberto
# trazia os solucionados) e o endpoint de listagem simples ignorar filtros em
# silencio (pedir grupos de uma entidade devolvia os de todas).
#
# Uso:
#   GLPI_TOKEN=<token do usuario> ./scripts/smoke_live.sh [porta]
#
# O token vem SEMPRE do ambiente. Nunca deve ser gravado neste arquivo, nem
# adicionado ao .env do servidor: virar fallback faria o servidor aceitar
# chamadas sem token usando essa identidade, quebrando o isolamento entre
# clientes e a autoria correta no GLPI.
#
# Somente leitura por padrao. Para exercitar tambem o ciclo de escrita:
#   SMOKE_WRITE=1 SMOKE_TICKET_ID=<id de um chamado de teste> ...
set -uo pipefail

PORT="${1:-${PORT:-8826}}"
: "${GLPI_TOKEN:?defina GLPI_TOKEN no ambiente}"

PASS=0
FAIL=0

call() {
  curl -s --max-time 30 -X POST "http://127.0.0.1:${PORT}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H "X-GLPI-User-Token: ${GLPI_TOKEN}" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}"
}

# O corpo util vem como JSON escapado dentro do envelope, entao comparar
# sempre sobre o texto desescapado — senao um teste "passa" ou "falha" pelo
# escape, nao pelo conteudo.
payload() {
  printf '%s' "$1" | sed -e 's/\\n/ /g' -e 's/\\"/"/g'
}

# check <descricao> <tool> <args-json> <texto esperado na resposta>
check() {
  local desc="$1" tool="$2" args="$3" expect="$4"
  local out body
  out="$(call "$tool" "$args")"
  body="$(payload "$out")"
  if printf '%s' "$out" | grep -q '"error"'; then
    printf '  FALHOU  %s\n          erro: %s\n' "$desc" "$(printf '%s' "$body" | head -c 200)"
    FAIL=$((FAIL + 1))
    return
  fi
  if printf '%s' "$body" | grep -qF "$expect"; then
    printf '  ok      %s\n' "$desc"
    PASS=$((PASS + 1))
  else
    printf '  FALHOU  %s\n          esperado conter: %s\n          veio: %s\n' \
      "$desc" "$expect" "$(printf '%s' "$body" | head -c 200)"
    FAIL=$((FAIL + 1))
  fi
}

# expect_error <descricao> <tool> <args-json> <texto esperado no erro>
# Recusar entrada invalida com uma mensagem util E o comportamento correto:
# aqui o erro e o resultado esperado, nao uma falha.
expect_error() {
  local desc="$1" tool="$2" args="$3" expect="$4"
  local out body
  out="$(call "$tool" "$args")"
  body="$(payload "$out")"
  if ! printf '%s' "$out" | grep -q '"error"'; then
    printf '  FALHOU  %s\n          deveria ter sido recusado, mas passou\n' "$desc"
    FAIL=$((FAIL + 1))
    return
  fi
  if printf '%s' "$body" | grep -qF "$expect"; then
    printf '  ok      %s\n' "$desc"
    PASS=$((PASS + 1))
  else
    printf '  FALHOU  %s\n          erro sem a orientacao esperada: %s\n' \
      "$desc" "$(printf '%s' "$body" | head -c 200)"
    FAIL=$((FAIL + 1))
  fi
}

# refute <descricao> <tool> <args-json> <texto que NAO pode aparecer>
refute() {
  local desc="$1" tool="$2" args="$3" forbidden="$4"
  local out body
  out="$(call "$tool" "$args")"
  body="$(payload "$out")"
  # Uma chamada que ERRA nao prova ausencia de nada — sem isto, o teste
  # "passaria" justamente quando a tool esta quebrada.
  if printf '%s' "$out" | grep -q '"error"'; then
    printf '  FALHOU  %s\n          a chamada falhou: %s\n' "$desc" "$(printf '%s' "$body" | head -c 160)"
    FAIL=$((FAIL + 1))
    return
  fi
  if printf '%s' "$body" | grep -qF "$forbidden"; then
    printf '  FALHOU  %s\n          nao podia conter: %s\n' "$desc" "$forbidden"
    FAIL=$((FAIL + 1))
  else
    printf '  ok      %s\n' "$desc"
    PASS=$((PASS + 1))
  fi
}

echo "== sessao e catalogo =="
check "lista chamados" glpi_search_helpdesk_tickets '{"limit":2}' '|'
check "descobre campos do chamado" glpi_search_records_by_criteria \
  '{"itemtype":"Ticket","scope":"fields","field_filter":"status"}' '| Campo | ID |'
# A coluna do proprio chamado fica com o rotulo simples; homonimos vindos de
# tabelas associadas sao qualificados. Se este numero mudar, a descoberta
# passou a anunciar um id que a busca nao usaria.
check "campo status resolve para a coluna do proprio chamado" glpi_search_records_by_criteria \
  '{"itemtype":"Ticket","scope":"fields","field_filter":"status"}' '| Status | 12 |'

echo
echo "== filtros que ja falharam em producao =="
# O operador do GLPI e inclusivo: o limite tem de ser o ultimo status aberto.
refute "chamados em aberto nao trazem solucionados" glpi_search_helpdesk_tickets \
  '{"open_only":true,"limit":20}' 'Solucionado'
refute "chamados em aberto nao trazem fechados" glpi_search_helpdesk_tickets \
  '{"open_only":true,"limit":20}' 'Fechado'
check "ordenacao por data e aceita" glpi_search_helpdesk_tickets \
  '{"sort_by":"date","order":"asc","limit":2}' '|'
check "filtro por grupo atribuido e aceito" glpi_search_helpdesk_tickets \
  '{"assigned_group":"nao-existe-xyz","limit":2}' 'Nenhum'

echo
echo "== isolamento entre clientes =="
# Listagem simples ignora filtros: uma entidade inexistente tem de vir vazia.
check "entidade inexistente nao devolve grupos de outras" glpi_search_admin_resources \
  '{"resource":"groups","entity_id":999999,"limit":5}' 'Nenhum'
check "entidade inexistente nao devolve localizacoes de outras" glpi_search_admin_resources \
  '{"resource":"locations","entity_id":999999,"limit":5}' 'Nenhum'

echo
echo "== contagem barata =="
check "conta chamados sem paginar" glpi_search_records_by_criteria \
  '{"itemtype":"Ticket","scope":"count"}' 'registro(s)'
check "conta registros ITIL sem paginar" glpi_search_itil_records \
  '{"record_type":"contracts","count_only":true}' 'registro'

echo
echo "== ITIL alem do incidente =="
check "lista contratos" glpi_search_itil_records '{"record_type":"contracts","limit":2}' '|'
check "lista fornecedores" glpi_search_itil_records '{"record_type":"suppliers","limit":2}' '|'
# Expectativa vazia casaria com QUALQUER resposta — inclusive vazia.
check "lista problemas" glpi_search_itil_records '{"record_type":"problems","limit":2}' 'problema'

echo
echo "== busca textual cobre titulo E descricao =="
check "termo so na descricao e encontrado" glpi_search_helpdesk_tickets \
  '{"query":"paletizado","limit":3}' '|'
refute "chamados em aberto incluem os atribuidos, nao so os pendentes" \
  glpi_search_helpdesk_tickets '{"open_only":true,"limit":20}' 'Nenhum'

echo
echo "== paginacao nao afirma completude que nao tem =="
refute "pagina cheia nao e anunciada como lista completa" glpi_search_helpdesk_tickets \
  '{"limit":3}' 'Mostrando todos'

echo
echo "== paginacao: paginas consecutivas sem repetir nem pular =="
# Erro de fronteira nao aparece em teste unitario e continua plausivel na
# resposta: a segunda pagina repetindo a primeira parece apenas "mais dados".
page_ids() {
  payload "$(call glpi_search_helpdesk_tickets \
    "{\"sort_by\":\"date\",\"order\":\"asc\",\"limit\":5,\"offset\":$1}")" \
    | grep -oE '\| \[[0-9]+\]' | grep -oE '[0-9]+' | tr '\n' ' '
}
P1="$(page_ids 0)"
P2="$(page_ids 5)"
if [ -z "$P1" ] || [ -z "$P2" ]; then
  printf '  FALHOU  paginacao devolveu pagina vazia (p1="%s" p2="%s")\n' "$P1" "$P2"
  FAIL=$((FAIL + 1))
else
  overlap=0
  for id in $P1; do
    case " $P2 " in *" $id "*) overlap=1 ;; esac
  done
  if [ "$overlap" -eq 1 ]; then
    printf '  FALHOU  paginas 1 e 2 compartilham registros\n          p1: %s\n          p2: %s\n' "$P1" "$P2"
    FAIL=$((FAIL + 1))
  else
    printf '  ok      paginas consecutivas nao repetem registros\n'
    PASS=$((PASS + 1))
  fi
fi

echo
echo "== entrada invalida e recusada com orientacao =="
expect_error "tipo de registro invalido lista os aceitos" glpi_search_itil_records \
  '{"record_type":"inexistente"}' 'contracts'
expect_error "campo inexistente orienta o proximo passo" glpi_search_records_by_criteria \
  '{"itemtype":"Ticket","criteria":[{"field":"campo_que_nao_existe","value":1}]}' 'scope=fields'
expect_error "operador invalido lista os aceitos" glpi_search_records_by_criteria \
  '{"itemtype":"Ticket","criteria":[{"field":"status","searchtype":"quase","value":1}]}' 'contains'

if [ "${SMOKE_WRITE:-0}" = "1" ]; then
  echo
  echo "== ciclo de escrita (SMOKE_WRITE=1) =="
  : "${SMOKE_TICKET_ID:?defina SMOKE_TICKET_ID com um chamado de teste}"
  check "adiciona tarefa" glpi_manage_ticket_operations \
    "{\"action\":\"add_task\",\"ticket_id\":${SMOKE_TICKET_ID},\"content\":\"Smoke test automatizado. Registro de verificacao.\",\"is_private\":true}" \
    'sucesso'
  check "tarefa aparece na linha do tempo" glpi_manage_ticket_operations \
    "{\"action\":\"get_timeline\",\"ticket_id\":${SMOKE_TICKET_ID}}" 'Tarefa'
fi

echo
echo "-----------------------------------------"
printf 'passou: %d   falhou: %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
