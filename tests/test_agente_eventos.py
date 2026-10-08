"""Eventos do agente (ao_evento) e cancelamento (deve_parar).

Reaproveita o modelo falso de test_agente.py: o pytest põe a pasta tests/ no sys.path.
"""
import logging
import threading

import pytest

from agentes.agente import (MAX_CARACTERES_DOS_ARGUMENTOS_NO_EVENTO, LimiteDeUsoAtingido, PerguntaCancelada,
                            executar_agente)
from test_agente import (FERRAMENTAS, Erro429, ModeloFalso, ModeloQueFalha, chamada, com_uso, pedido_de_tools,
                         texto)


def rodar_ouvindo(modelo, **kw):
    eventos = []
    resultado = executar_agente("pergunta", modelo, "modelo-x", FERRAMENTAS, ao_evento=eventos.append, **kw)
    return resultado, eventos


def nomes(eventos):
    return [e["evento"] for e in eventos]


# ------------------------------------------------------------------ não regressão
def test_sem_ao_evento_o_agente_se_comporta_como_antes():
    def roteiro():
        return [com_uso(pedido_de_tools(chamada("c1", "somar", {"a": 2, "b": 3})), 100, 10),
                com_uso(texto("deu 5"), 200, 20)]

    sem, com = ModeloFalso(roteiro()), ModeloFalso(roteiro())
    r_sem = executar_agente("pergunta", sem, "modelo-x", FERRAMENTAS)
    r_com, _ = rodar_ouvindo(com)
    assert sem.pedidos == com.pedidos                      # o modelo recebeu exatamente o mesmo
    sem_tempo = lambda r: (r.resposta, [{k: v for k, v in p.items() if k != "segundos"} for p in r.passos],  # noqa: E731
                           r.chamadas_ao_modelo, r.tokens_entrada, r.tokens_saida, r.parou_por_limite)
    assert sem_tempo(r_sem) == sem_tempo(r_com)


# ------------------------------------------------------------------ ordem e conteúdo
def test_ordem_e_conteudo_dos_eventos_com_uma_tool():
    m = ModeloFalso([com_uso(pedido_de_tools(chamada("c1", "somar", {"a": 2, "b": 3})), 100, 10),
                     com_uso(texto("deu 5"), 200, 20)])
    _, eventos = rodar_ouvindo(m)
    assert nomes(eventos) == ["modelo_inicio", "tool_inicio", "tool_fim", "modelo_inicio", "fim"]
    assert [e["chamada"] for e in eventos if e["evento"] == "modelo_inicio"] == [1, 2]
    assert eventos[1] == {"evento": "tool_inicio", "indice": 1, "tool": "somar", "argumentos": {"a": 2, "b": 3}}
    assert (eventos[2]["indice"], eventos[2]["tool"], eventos[2]["erro"]) == (1, "somar", False)
    assert eventos[2]["segundos"] >= 0
    fim = eventos[-1]
    assert fim["resposta"] == "deu 5"
    assert fim["metricas"]["chamadas_ao_modelo"] == 2
    assert (fim["metricas"]["tokens_entrada"], fim["metricas"]["tokens_saida"]) == (300, 30)
    assert fim["metricas"]["parou_por_limite"] is False
    assert {"segundos_no_modelo", "segundos_nas_tools", "segundos_em_espera"} <= set(fim["metricas"])


def test_indices_distinguem_duas_chamadas_da_mesma_tool():
    m = ModeloFalso([pedido_de_tools(chamada("c1", "somar", {"a": 1, "b": 2}), chamada("c2", "somar", {"a": 3, "b": 4})),
                     texto("pronto")])
    _, eventos = rodar_ouvindo(m)
    assert [(e["evento"], e["indice"]) for e in eventos if e["evento"].startswith("tool_")] == [
        ("tool_inicio", 1), ("tool_fim", 1), ("tool_inicio", 2), ("tool_fim", 2)]


def test_tool_com_erro_e_marcada_no_evento():
    m = ModeloFalso([pedido_de_tools(chamada("c1", "explodir", {"x": "a"})), texto("me corrigi")])
    _, eventos = rodar_ouvindo(m)
    assert next(e for e in eventos if e["evento"] == "tool_fim")["erro"] is True


@pytest.mark.parametrize("argumentos, esperado", [
    ("{isto nao e json", "{isto nao e json"),            # JSON inválido: vai como texto
    ("[1, 2]", "[1, 2]"),                                # JSON que não é objeto: texto
    ("", {}),                                            # sem argumentos: objeto vazio
])
def test_argumentos_estranhos_viram_texto(argumentos, esperado):
    m = ModeloFalso([pedido_de_tools(chamada("c1", "somar", argumentos)), texto("ok")])
    _, eventos = rodar_ouvindo(m)
    assert next(e for e in eventos if e["evento"] == "tool_inicio")["argumentos"] == esperado


def test_argumentos_longos_sao_cortados_no_evento_mas_nao_na_tool():
    longo = {"x": "y" * 1000}
    m = ModeloFalso([pedido_de_tools(chamada("c1", "enorme", longo)), texto("ok")])
    r, eventos = rodar_ouvindo(m)
    exibido = next(e for e in eventos if e["evento"] == "tool_inicio")["argumentos"]
    assert isinstance(exibido, str) and len(exibido) == MAX_CARACTERES_DOS_ARGUMENTOS_NO_EVENTO + 1
    assert exibido.endswith("…")
    assert r.passos[0]["erro"] is False                   # a tool recebeu os argumentos inteiros


def test_fim_informa_parada_no_limite_de_passos():
    m = ModeloFalso([pedido_de_tools(chamada(f"c{i}", "somar", {"a": 1, "b": 1})) for i in range(2)])
    _, eventos = rodar_ouvindo(m, max_passos=2)
    assert eventos[-1]["evento"] == "fim" and eventos[-1]["metricas"]["parou_por_limite"] is True


# ------------------------------------------------------------------ espera por limite de uso (429)
def test_espera_e_emitida_antes_de_dormir():
    ordem = []
    m = ModeloQueFalha([Erro429(retry_after=20)], texto("deu certo"))
    executar_agente("p", m, "x", FERRAMENTAS, ao_evento=lambda e: ordem.append(e["evento"]),
                    dormir=lambda s: ordem.append(f"dormiu {s}"))
    assert ordem == ["modelo_inicio", "espera", "dormiu 21.0", "fim"]


def test_evento_de_espera_traz_segundos_e_motivo():
    m = ModeloQueFalha([Erro429(retry_after=20)], texto("ok"))
    _, eventos = rodar_ouvindo(m, dormir=lambda s: None)
    espera = next(e for e in eventos if e["evento"] == "espera")
    assert espera == {"evento": "espera", "segundos": 21.0, "motivo": "limite_de_uso"}


# ------------------------------------------------------------------ quem ouve com defeito não derruba o agente
def test_ao_evento_que_falha_nao_derruba_o_agente_e_fica_no_log(caplog):
    def ouvinte_quebrado(evento):
        raise RuntimeError("segredo-que-nao-pode-ir-para-o-log")

    m = ModeloFalso([pedido_de_tools(chamada("c1", "somar", {"a": 2, "b": 3})), texto("deu 5")])
    with caplog.at_level(logging.WARNING, logger="agentes.agente"):
        r = executar_agente("p", m, "x", FERRAMENTAS, ao_evento=ouvinte_quebrado)
    assert r.resposta == "deu 5"
    assert "ao_evento falhou" in caplog.text and "RuntimeError" in caplog.text
    assert "segredo-que-nao-pode-ir-para-o-log" not in caplog.text


# ------------------------------------------------------------------ cancelamento (deve_parar)
def test_parar_antes_da_primeira_chamada_nao_chama_o_modelo():
    m = ModeloFalso([texto("nunca")])
    with pytest.raises(PerguntaCancelada):
        executar_agente("p", m, "x", FERRAMENTAS, deve_parar=lambda: True)
    assert m.pedidos == []


def test_parar_entre_duas_tools_nao_executa_a_segunda():
    executadas = []

    def anotar(x: str) -> dict:
        """Anota a execução."""
        executadas.append(x)
        return {"ok": True}

    eventos = []
    m = ModeloFalso([pedido_de_tools(chamada("c1", "anotar", {"x": "1"}), chamada("c2", "anotar", {"x": "2"})),
                     texto("nunca")])
    parar = lambda: any(e["evento"] == "tool_fim" for e in eventos)  # noqa: E731 - para depois da 1ª tool
    with pytest.raises(PerguntaCancelada):
        executar_agente("p", m, "x", [anotar], ao_evento=eventos.append, deve_parar=parar)
    assert executadas == ["1"]
    assert "fim" not in nomes(eventos)                    # cancelado não emite 'fim'


def test_parar_durante_a_espera_do_429_nao_chama_o_provedor_de_novo():
    # O servidor usa dormir=cancelar.wait: clicar em Parar acorda o agente no meio da espera.
    cancelar = threading.Event()

    def dormir_ate_cancelarem(segundos):
        cancelar.set()                                    # o usuário clicou em Parar durante a espera
        cancelar.wait(segundos)

    m = ModeloQueFalha([Erro429(retry_after=1) for _ in range(10)], texto("nunca"))
    with pytest.raises(PerguntaCancelada):
        executar_agente("p", m, "x", FERRAMENTAS, dormir=dormir_ate_cancelarem, deve_parar=cancelar.is_set)
    assert m.chamadas == 1                                # zero chamadas depois da espera


def test_sem_pedido_de_parada_o_429_persistente_continua_terminando_em_limite():
    m = ModeloQueFalha([Erro429(retry_after=1) for _ in range(10)], texto("nunca"))
    with pytest.raises(LimiteDeUsoAtingido):
        executar_agente("p", m, "x", FERRAMENTAS, dormir=lambda s: None, deve_parar=lambda: False,
                        max_tentativas_429=3)
    assert m.chamadas == 3
