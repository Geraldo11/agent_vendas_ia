"""API do chat com agente FALSO: fluxo de eventos, validação, trava, timeout, erros e segurança.

Nada aqui fala com o Groq ou com o Databricks. O "executor do agente" é injetado em criar_app,
como as tools fazem com executor=.
"""
import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agentes.agente import LimiteDeUsoAtingido, PerguntaCancelada, ResultadoDoAgente  # noqa: E402
from agentes.llm import ConfigLLM  # noqa: E402
from chat.app import MAX_CARACTERES_DA_PERGUNTA, criar_app, criar_executor_real  # noqa: E402
from chat.erros import RAIZ, classificar_erro, remover_segredos, valores_secretos  # noqa: E402
from chat.seguranca import CSP  # noqa: E402
from test_agente import FERRAMENTAS, ModeloFalso, chamada, com_uso, pedido_de_tools, texto  # noqa: E402

SEGREDO = "gsk_segredo_muito_secreto_123"
ENV = {"GROQ_API_KEY": SEGREDO, "DATABRICKS_TOKEN": "dapi_token_falso_456", "LLM_MODEL": "modelo-x"}
CONFIG = ConfigLLM("groq", "https://api.groq.com/openai/v1", SEGREDO, "openai/gpt-oss-120b")
BASE = "http://127.0.0.1:8000"
JSON = {"Content-Type": "application/json"}
TERMINAIS = {"fim", "erro", "cancelado"}


# ------------------------------------------------------------------ apoio
def resultado(resposta="resposta final"):
    return ResultadoDoAgente(resposta=resposta, chamadas_ao_modelo=2, tokens_entrada=300, tokens_saida=30,
                             segundos_no_modelo=1.5, segundos_nas_tools=0.5)


class AgenteFalso:
    """Executor falso: emite os eventos dados e então faz `desfecho` (devolver ou lançar)."""

    def __init__(self, eventos=(), desfecho=None):
        self.eventos, self.desfecho, self.perguntas = list(eventos), desfecho, []

    def __call__(self, pergunta, *, ao_evento, deve_parar, dormir):
        self.perguntas.append(pergunta)
        for evento in self.eventos:
            ao_evento(evento)
        if isinstance(self.desfecho, BaseException):
            raise self.desfecho
        return self.desfecho or resultado()


class AgenteQueEspera:
    """Executor falso que fica 'pensando' até pedirem para parar (ou até ser liberado)."""

    def __init__(self):
        self.comecou, self.liberar, self.terminou = threading.Event(), threading.Event(), threading.Event()

    def __call__(self, pergunta, *, ao_evento, deve_parar, dormir):
        try:
            self.comecou.set()
            ao_evento({"evento": "modelo_inicio", "chamada": 1})
            limite = time.monotonic() + 5
            while not self.liberar.is_set() and time.monotonic() < limite:
                if deve_parar():
                    raise PerguntaCancelada("parou")
                time.sleep(0.01)
            return resultado()
        finally:
            self.terminou.set()


TIMEOUT_DOS_TESTES = 5     # curto: se um defeito deixar o fluxo sem terminal, o teste falha rápido (não em 180 s)


def app_de_teste(executor, **kw):
    kw.setdefault("env", ENV)
    kw.setdefault("timeout_segundos", TIMEOUT_DOS_TESTES)
    return criar_app(executor, CONFIG, **kw)


def cliente(executor, base=BASE, **kw):
    return TestClient(app_de_teste(executor, **kw), base_url=base)


def perguntar(c, pergunta="Por que a venda VD000084 não entrou na carteira?", headers=JSON, **kw):
    return c.post("/api/perguntar", content=json.dumps({"pergunta": pergunta}), headers=headers, **kw)


def eventos_de(resposta):
    assert resposta.status_code == 200, resposta.text
    assert resposta.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(linha) for linha in resposta.text.splitlines() if linha.strip()]


def esperar_livre(c, segundos=5):
    """A trava é liberada pela thread do agente, que pode terminar um instante depois do fluxo."""
    limite = time.monotonic() + segundos
    while c.get("/api/saude").json()["ocupado"]:
        assert time.monotonic() < limite, "a trava não foi liberada"
        time.sleep(0.01)


def um_terminal_no_fim(eventos):
    terminais = [e for e in eventos if e["evento"] in TERMINAIS]
    assert len(terminais) == 1, eventos
    assert eventos[-1] is terminais[0]
    return terminais[0]


# ------------------------------------------------------------------ fluxo de eventos
def test_fluxo_repassa_os_eventos_na_ordem_e_termina_com_fim():
    agente = AgenteFalso([{"evento": "modelo_inicio", "chamada": 1},
                          {"evento": "tool_inicio", "indice": 1, "tool": "get_venda", "argumentos": {"id_venda": "VD1"}},
                          {"evento": "tool_fim", "indice": 1, "tool": "get_venda", "segundos": 0.4, "erro": False}])
    eventos = eventos_de(perguntar(cliente(agente)))
    assert [e["evento"] for e in eventos] == ["modelo_inicio", "tool_inicio", "tool_fim", "fim"]
    fim = um_terminal_no_fim(eventos)
    assert fim["resposta"] == "resposta final"
    assert (fim["metricas"]["tokens_entrada"], fim["metricas"]["tokens_saida"]) == (300, 30)
    assert agente.perguntas == ["Por que a venda VD000084 não entrou na carteira?"]


def test_pergunta_chega_ao_agente_sem_espacos_nas_pontas():
    agente = AgenteFalso()
    eventos_de(perguntar(cliente(agente), "   oi   "))
    assert agente.perguntas == ["oi"]


def test_com_o_agente_real_e_modelo_falso_sai_um_unico_fim():
    # O agente de verdade emite 'fim' e o servidor também montaria um ao final: só um pode sair.
    modelo = ModeloFalso([com_uso(pedido_de_tools(chamada("c1", "somar", {"a": 2, "b": 3})), 100, 10),
                          com_uso(texto("deu 5"), 200, 20)])
    eventos = eventos_de(perguntar(cliente(criar_executor_real(CONFIG, modelo, FERRAMENTAS))))
    assert [e["evento"] for e in eventos] == ["modelo_inicio", "tool_inicio", "tool_fim", "modelo_inicio", "fim"]
    assert um_terminal_no_fim(eventos)["resposta"] == "deu 5"


class Erro(Exception):
    def __init__(self, status=None, mensagem="falhou"):
        super().__init__(mensagem)
        self.status_code = status


@pytest.mark.parametrize("desfecho, terminal, tipo", [
    (None, "fim", None),
    (LimiteDeUsoAtingido("limite"), "erro", "limite_de_uso"),
    (Erro(401), "erro", "configuracao"),
    (ValueError("bug"), "erro", "interno"),
    (PerguntaCancelada("parou"), "cancelado", None),
])
def test_todo_fluxo_termina_com_exatamente_um_evento_terminal(desfecho, terminal, tipo):
    eventos = eventos_de(perguntar(cliente(AgenteFalso([{"evento": "modelo_inicio", "chamada": 1}], desfecho))))
    ultimo = um_terminal_no_fim(eventos)
    assert ultimo["evento"] == terminal and ultimo.get("tipo") == tipo


def test_eventos_depois_do_terminal_nao_sao_enviados():
    agente = AgenteFalso([{"evento": "fim", "resposta": "a", "metricas": {}},
                          {"evento": "tool_inicio", "indice": 9, "tool": "x", "argumentos": {}}])
    eventos = eventos_de(perguntar(cliente(agente)))
    assert [e["evento"] for e in eventos] == ["fim"]


# ------------------------------------------------------------------ validação
@pytest.mark.parametrize("corpo, trecho", [
    (json.dumps({"pergunta": ""}), "vazia"),
    (json.dumps({"pergunta": "   \n  "}), "vazia"),
    (json.dumps({"pergunta": "x" * (MAX_CARACTERES_DA_PERGUNTA + 1)}), "limite"),
    ("{isto não é json", "JSON válido"),
    (json.dumps({"outra_coisa": "oi"}), "'pergunta'"),
    (json.dumps({"pergunta": 123}), "'pergunta'"),
    (json.dumps(["oi"]), "'pergunta'"),
])
def test_pedido_invalido_e_recusado_sem_chamar_o_agente(corpo, trecho):
    agente = AgenteFalso()
    r = cliente(agente).post("/api/perguntar", content=corpo, headers=JSON)
    assert r.status_code == 400 and r.json()["erro"]["tipo"] == "validacao"
    assert trecho in r.json()["erro"]["mensagem"]
    assert agente.perguntas == []


def test_pergunta_com_exatamente_o_limite_e_aceita():
    agente = AgenteFalso()
    eventos_de(perguntar(cliente(agente), "x" * MAX_CARACTERES_DA_PERGUNTA))
    assert len(agente.perguntas) == 1


def test_sem_content_type_json_e_recusado():
    agente = AgenteFalso()
    r = cliente(agente).post("/api/perguntar", content=json.dumps({"pergunta": "oi"}),
                             headers={"Content-Type": "text/plain"})
    assert r.status_code == 415 and agente.perguntas == []


# ------------------------------------------------------------------ uma pergunta por vez
def em_segundo_plano(funcao):
    caixa = {}
    t = threading.Thread(target=lambda: caixa.setdefault("r", funcao()), daemon=True)
    t.start()
    return t, caixa


def test_segunda_pergunta_durante_a_primeira_recebe_409():
    agente = AgenteQueEspera()
    app = app_de_teste(agente)
    primeira, caixa = em_segundo_plano(lambda: perguntar(TestClient(app, base_url=BASE)))
    assert agente.comecou.wait(5)
    segunda = perguntar(TestClient(app, base_url=BASE))
    assert segunda.status_code == 409 and segunda.json()["erro"]["tipo"] == "ocupado"
    assert "andamento" in segunda.json()["erro"]["mensagem"]
    agente.liberar.set()
    primeira.join(5)
    um_terminal_no_fim(eventos_de(caixa["r"]))


def test_trava_e_liberada_depois_de_sucesso_e_de_erro():
    c = cliente(AgenteFalso(desfecho=ValueError("bug")))
    eventos_de(perguntar(c))
    esperar_livre(c)
    eventos_de(perguntar(c))                                # não deu 409: a trava foi liberada
    esperar_livre(c)


def test_trava_so_e_liberada_quando_a_thread_do_agente_termina():
    # Timeout: o fluxo acaba, mas o agente ainda não chegou a um ponto de parada.
    agente = AgenteQueEspera()
    pausa = threading.Event()

    def demora_para_parar(pergunta, **kw):
        kw["deve_parar"] = lambda: pausa.is_set()           # só "ouve" o pedido quando liberarmos
        return agente(pergunta, **kw)

    c = cliente(demora_para_parar, timeout_segundos=0.2)
    um_terminal_no_fim(eventos_de(perguntar(c)))
    assert c.get("/api/saude").json()["ocupado"] is True    # a thread continua: ainda ocupado
    assert perguntar(c).status_code == 409
    pausa.set()
    assert agente.terminou.wait(5)
    esperar_livre(c)


# ------------------------------------------------------------------ timeout e parada
def test_timeout_termina_com_erro_tempo_esgotado_e_pede_para_o_agente_parar():
    agente = AgenteQueEspera()
    c = cliente(agente, timeout_segundos=0.2)
    eventos = eventos_de(perguntar(c))
    ultimo = um_terminal_no_fim(eventos)
    assert (ultimo["evento"], ultimo["tipo"]) == ("erro", "tempo_esgotado")
    assert agente.terminou.wait(5)                          # o agente ouviu o pedido de parada
    esperar_livre(c)


def test_botao_parar_termina_com_cancelado_e_nao_e_erro():
    agente = AgenteQueEspera()
    app = app_de_teste(agente)
    primeira, caixa = em_segundo_plano(lambda: perguntar(TestClient(app, base_url=BASE)))
    assert agente.comecou.wait(5)
    r = TestClient(app, base_url=BASE).post("/api/parar", content="{}", headers=JSON)
    assert r.json() == {"ok": True, "havia_pergunta": True}
    primeira.join(5)
    ultimo = um_terminal_no_fim(eventos_de(caixa["r"]))
    assert ultimo["evento"] == "cancelado" and "interrompida" in ultimo["mensagem"]


def test_parar_sem_pergunta_em_andamento_nao_faz_nada():
    r = cliente(AgenteFalso()).post("/api/parar", content="{}", headers=JSON)
    assert r.json() == {"ok": True, "havia_pergunta": False}


def test_parar_durante_espera_por_limite_de_uso_nao_chama_o_provedor_de_novo():
    # Integração com o agente REAL: dormir=cancelar.wait. O 429 manda esperar 60 s; paramos no meio.
    class Erro429(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "60"})

    chamadas = []

    def criar(**kwargs):
        chamadas.append(1)
        raise Erro429("rate limit")

    modelo = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=criar)))
    app = app_de_teste(criar_executor_real(CONFIG, modelo, FERRAMENTAS))
    primeira, caixa = em_segundo_plano(lambda: perguntar(TestClient(app, base_url=BASE)))
    limite = time.monotonic() + 5
    while not chamadas:
        assert time.monotonic() < limite
        time.sleep(0.01)
    time.sleep(0.05)                                         # já está dormindo os 60 s
    TestClient(app, base_url=BASE).post("/api/parar", content="{}", headers=JSON)
    primeira.join(5)
    eventos = eventos_de(caixa["r"])
    assert [e["evento"] for e in eventos] == ["modelo_inicio", "espera", "cancelado"]
    assert eventos[1]["segundos"] == 61.0
    assert len(chamadas) == 1                                # zero chamadas depois da espera


# ------------------------------------------------------------------ erros sem vazamento
@pytest.mark.parametrize("erro", [
    LimiteDeUsoAtingido(f"429 do provedor; cabeçalho Authorization: Bearer {SEGREDO}"),
    Erro(400, f"bad request com a chave {SEGREDO}"),
    ValueError(f"bug interno com {SEGREDO} em {RAIZ}"),
])
def test_mensagem_de_erro_nunca_contem_a_chave_nem_caminhos(erro, caplog):
    with caplog.at_level(logging.ERROR, logger="chat.erros"):
        r = perguntar(cliente(AgenteFalso(desfecho=erro)))
    assert SEGREDO not in r.text and str(RAIZ) not in r.text and "Traceback" not in r.text
    assert SEGREDO not in caplog.text and str(RAIZ) not in caplog.text


def test_erro_interno_fica_no_log_e_nao_vai_para_o_navegador(caplog):
    with caplog.at_level(logging.ERROR, logger="chat.erros"):
        eventos = eventos_de(perguntar(cliente(AgenteFalso(desfecho=ValueError("detalhe-tecnico-xyz")))))
    assert "detalhe-tecnico-xyz" not in json.dumps(eventos)
    assert "detalhe-tecnico-xyz" in caplog.text and "ValueError" in caplog.text


class APIConnectionError(Exception):
    """Mesmo nome da exceção da biblioteca openai (a classificação é pelo nome)."""


@pytest.mark.parametrize("erro, tipo, trecho", [
    (LimiteDeUsoAtingido("Limite de uso do provedor atingido"), "limite_de_uso", "Limite de uso"),
    (Erro(401), "configuracao", "HTTP 401"),
    (Erro(403), "configuracao", "HTTP 403"),
    (Erro(404), "configuracao", "openai/gpt-oss-120b"),
    (Erro(400, "pedido ruim"), "provedor", "HTTP 400"),
    (Erro(503), "provedor", "HTTP 503"),
    (APIConnectionError("recusada"), "provedor", "Não consegui falar"),
    (KeyError("x"), "interno", "log do servidor"),
])
def test_classificacao_dos_erros(erro, tipo, trecho):
    evento = classificar_erro(erro, CONFIG, ENV)
    assert evento["evento"] == "erro" and evento["tipo"] == tipo and trecho in evento["mensagem"]


# ------------------------------------------------------------------ remoção de segredos (ajuste B)
def test_remove_segredos_so_de_nomes_terminados_em_key_token_ou_secret():
    env = {"GROQ_API_KEY": "gsk_aaaaaaaa", "DATABRICKS_TOKEN": "dapi_bbbbbbbb", "CLIENT_SECRET": "cccccccccc",
           "LLM_MODEL": "modelo-publico-123"}
    texto = "gsk_aaaaaaaa dapi_bbbbbbbb cccccccccc modelo-publico-123"
    assert remover_segredos(texto, env) == "*** *** *** modelo-publico-123"


@pytest.mark.parametrize("valor", ["", "   ", "curto", "1234567"])
def test_valor_vazio_ou_curto_nao_e_tratado_como_segredo(valor):
    env = {"GROQ_API_KEY": valor}
    assert valores_secretos(env) == []
    assert remover_segredos("mensagem intacta", env) == "mensagem intacta"


def test_segredo_maior_e_trocado_antes_do_menor():
    env = {"A_KEY": "abcdefgh", "B_KEY": "abcdefgh_e_mais"}
    assert remover_segredos("abcdefgh_e_mais", env) == "***"


# ------------------------------------------------------------------ cabeçalhos de segurança
def conferir_cabecalhos(r):
    assert r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_cabecalhos_em_todas_as_respostas():
    c = cliente(AgenteFalso())
    respostas = [
        c.get("/api/saude"),
        perguntar(c),                                                   # fluxo
        c.post("/api/perguntar", content="{}", headers=JSON),          # 400
        c.post("/api/perguntar", content="{}"),                        # 415
        c.get("/nao-existe"),                                           # 404
        c.get("/api/saude", headers={"Host": "evil.com"}),              # recusado pelo Host
        perguntar(c, headers={**JSON, "Origin": "https://evil.com"}),   # recusado pelo Origin
    ]
    for r in respostas:
        conferir_cabecalhos(r)


def test_cabecalhos_tambem_no_409():
    agente = AgenteQueEspera()
    app = app_de_teste(agente)
    primeira, _ = em_segundo_plano(lambda: perguntar(TestClient(app, base_url=BASE)))
    assert agente.comecou.wait(5)
    r = perguntar(TestClient(app, base_url=BASE))
    assert r.status_code == 409
    conferir_cabecalhos(r)
    agente.liberar.set()
    primeira.join(5)


# ------------------------------------------------------------------ Host e Origin
@pytest.mark.parametrize("base", ["http://evil.com:8000", "http://127.0.0.1:9999", "http://localhost", "http://0.0.0.0:8000"])
def test_host_desconhecido_e_recusado(base):
    agente = AgenteFalso()
    c = cliente(agente, base=base)
    assert c.get("/api/saude").status_code == 400
    assert perguntar(c).status_code == 400 and agente.perguntas == []


@pytest.mark.parametrize("base", ["http://127.0.0.1:8000", "http://localhost:8000"])
def test_hosts_locais_na_porta_certa_sao_aceitos(base):
    assert cliente(AgenteFalso(), base=base).get("/api/saude").status_code == 200


def test_porta_configurada_vale_para_o_host():
    c = cliente(AgenteFalso(), base="http://127.0.0.1:8123", porta=8123)
    assert c.get("/api/saude").status_code == 200


@pytest.mark.parametrize("origem", ["https://evil.com", "http://127.0.0.1:9999", "null", "http://127.0.0.1:8000.evil.com"])
def test_origin_de_outra_pagina_e_recusado(origem):
    agente = AgenteFalso()
    c = cliente(agente)
    r = perguntar(c, headers={**JSON, "Origin": origem})
    assert r.status_code == 403 and agente.perguntas == []
    assert c.post("/api/parar", content="{}", headers={**JSON, "Origin": origem}).status_code == 403


@pytest.mark.parametrize("origem", [None, "http://127.0.0.1:8000", "http://localhost:8000"])
def test_origin_proprio_ou_ausente_e_aceito(origem):
    headers = dict(JSON) if origem is None else {**JSON, "Origin": origem}
    eventos_de(perguntar(cliente(AgenteFalso()), headers=headers))


# ------------------------------------------------------------------ /api/saude
def test_saude_informa_modo_provedor_e_modelo_sem_segredos():
    r = cliente(AgenteFalso()).get("/api/saude")
    assert r.json() == {"ok": True, "modo": "real", "provedor": "groq", "modelo": "openai/gpt-oss-120b",
                        "ocupado": False}
    for valor in (SEGREDO, ENV["DATABRICKS_TOKEN"], CONFIG.base_url):
        assert valor not in r.text


def test_saude_informa_o_modo_demonstracao():
    assert cliente(AgenteFalso(), modo="demonstracao").get("/api/saude").json()["modo"] == "demonstracao"


def test_sem_documentacao_automatica_exposta():
    c = cliente(AgenteFalso())
    assert [c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")] == [404, 404, 404]
