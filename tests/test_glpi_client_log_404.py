"""Followup sem anexo e RESULTADO, nao falha — e o log tem de dizer isso.

## O defeito, medido no mcp-glpi-<cliente> em 02/09/2026

`GET /TicketFollowup/<id>/Document_Item` devolve 404 quando o followup nao tem
documento anexado. Isso e o caso COMUM, e o chamador ja sabe: `_fu_docs` em
`ticket_service.py` varre `("ITILFollowup", "TicketFollowup")` dentro de um
`try/except Exception: continue`, exatamente porque nao sabe qual nome este GLPI
usa nem se existe anexo.

So que o log acontecia duas camadas abaixo — em `GLPIClient.get()` e de novo em
`GLPIClient.get_subitems()` — onde essa intencao nao existe. Cada followup sem
anexo virava DOIS `ERROR`, e o ETL varre ate 30 followups por chamado. O arquivo
`mcp-glpi-<cliente>-error.log` chegou a 1,4 MB dizendo que estava tudo normal.

Medicao que delimitou a correcao: 12 de 12 ocorrencias de "Get subitems failed"
no log daquele dia eram `TicketFollowup/Document_Item`. Nenhum outro subitem
aparecia — por isso a lista tem um item so.

O QUE ESTES TESTES TRAVAM

1. O 404 de subitem vazio sai em DEBUG, nos DOIS pontos de log (a correcao pela
   metade deixaria o volume caindo pela metade e o log ainda gritando).
2. 404 de recurso que NAO e subitem continua ERROR — "chamado 999999 nao existe"
   e erro de verdade e nao pode sumir junto.
3. Qualquer outro codigo (500, 401, 429) continua ERROR mesmo no Document_Item.
4. O COMPORTAMENTO nao mudou: `get_subitems` continua LEVANTANDO. Baixar o nivel
   de log nao pode virar, sem querer, engolir a excecao — o chamador depende dela
   para tentar o proximo itemtype.
"""

import pytest

from src.models.exceptions import GLPIError
from src.services.glpi_client import (
    GLPIClient,
    _e_ausencia_esperada,
)


class LoggerEspiao:
    """Registra em que nivel cada mensagem saiu."""

    def __init__(self) -> None:
        self.debug_msgs: list = []
        self.error_msgs: list = []

    def debug(self, msg, *a, **k) -> None:
        self.debug_msgs.append(str(msg))

    def error(self, msg, *a, **k) -> None:
        self.error_msgs.append(str(msg))

    def info(self, msg, *a, **k) -> None:
        pass

    def warning(self, msg, *a, **k) -> None:
        pass


# ---------------------------------------------------------------------------
# A decisao, isolada
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "endpoint, erro, esperado",
    [
        # 404 de subitem vazio: ausencia esperada.
        ("/apirest.php/TicketFollowup/12346/Document_Item", GLPIError(404, "x"), True),
        ("/apirest.php/Ticket/500/Document_Item", GLPIError(404, "x"), True),
        # 404 de recurso de verdade: erro que tem de continuar visivel.
        ("/apirest.php/Ticket/999999", GLPIError(404, "x"), False),
        ("/apirest.php/TicketFollowup/12346", GLPIError(404, "x"), False),
        # Outro subitem: nao foi medido, entao nao entra calado.
        ("/apirest.php/Ticket/1/TicketTask", GLPIError(404, "x"), False),
        # Mesmo endpoint, outro codigo: continua ERROR.
        ("/apirest.php/TicketFollowup/12346/Document_Item", GLPIError(500, "x"), False),
        ("/apirest.php/TicketFollowup/12346/Document_Item", GLPIError(401, "x"), False),
        # Excecao que nem e GLPIError (timeout, DNS): continua ERROR.
        ("/apirest.php/TicketFollowup/12346/Document_Item", TimeoutError("t"), False),
    ],
)
def test_so_o_404_medido_e_tratado_como_ausencia(endpoint, erro, esperado) -> None:
    assert _e_ausencia_esperada(endpoint, erro) is esperado


# ---------------------------------------------------------------------------
# Os dois pontos de log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_followup_sem_anexo_sai_em_debug_e_AINDA_levanta(monkeypatch) -> None:
    """O ponto de log de `get_subitems` — e a garantia de que nada foi engolido."""
    espiao = LoggerEspiao()
    monkeypatch.setattr("src.services.glpi_client.logger", espiao)

    cliente = object.__new__(GLPIClient)

    async def _get_que_falha(endpoint, params=None, *a, **k):
        raise GLPIError(404, f"Recurso nao encontrado no GLPI: {endpoint}")

    monkeypatch.setattr(cliente, "get", _get_que_falha, raising=False)

    with pytest.raises(GLPIError) as capturado:
        await cliente.get_subitems("TicketFollowup", 12346, "Document_Item")

    assert capturado.value.code == 404, (
        "a excecao tem de chegar INTACTA ao chamador: `_fu_docs` depende dela "
        "para tentar o proximo itemtype"
    )
    assert not espiao.error_msgs, f"ainda saiu ERROR: {espiao.error_msgs}"
    assert espiao.debug_msgs, "irmao de nao-vacuidade: nao saiu log nenhum"


@pytest.mark.asyncio
async def test_erro_de_verdade_no_subitem_continua_em_error(monkeypatch) -> None:
    espiao = LoggerEspiao()
    monkeypatch.setattr("src.services.glpi_client.logger", espiao)

    cliente = object.__new__(GLPIClient)

    async def _get_que_explode(endpoint, params=None, *a, **k):
        raise GLPIError(500, "HTTP error: banco fora")

    monkeypatch.setattr(cliente, "get", _get_que_explode, raising=False)

    with pytest.raises(GLPIError):
        await cliente.get_subitems("TicketFollowup", 12346, "Document_Item")

    assert espiao.error_msgs, "500 no Document_Item tem de continuar ERROR"
