"""Integração: cenários da demonstração ponta a ponta (agente REAL + modelo falso), servir_chat.py e Docker.

Nada aqui fala com o Groq ou com o Databricks, nem sobe um servidor de verdade.
"""
import json
import re
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import chat.demo as demo  # noqa: E402
from chat.app import criar_app  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import servir_chat  # noqa: E402


@pytest.fixture
def sem_pausas(monkeypatch):
    monkeypatch.setattr(demo, "_pausa", lambda segundos: None)
    monkeypatch.setattr(demo, "ESPERA_DO_429", 0)          # o agente espera 0 + 1 s de folga


def perguntar_demo(pergunta):
    app = criar_app(demo.executar_demo, demo.CONFIG_DEMO, modo="demonstracao", env={}, timeout_segundos=10)
    r = TestClient(app, base_url="http://127.0.0.1:8000").post(
        "/api/perguntar", content=json.dumps({"pergunta": pergunta}), headers={"Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    return [json.loads(l) for l in r.text.splitlines() if l.strip()]


# ------------------------------------------------------------------ cenários da demonstração
@pytest.mark.parametrize("cenario, evento_final, tipo", [
    ("normal", "fim", None),
    ("espera", "fim", None),
    ("limite", "erro", "limite_de_uso"),
    ("configuracao", "erro", "configuracao"),
    ("provedor", "erro", "provedor"),
    ("interno", "erro", "interno"),
    ("xss", "fim", None),
])
def test_cada_cenario_termina_como_esperado(sem_pausas, cenario, evento_final, tipo):
    eventos = perguntar_demo(f"[demo:{cenario}] pergunta")
    terminais = [e for e in eventos if e["evento"] in ("fim", "erro", "cancelado")]
    assert len(terminais) == 1 and eventos[-1] is terminais[0]
    assert (eventos[-1]["evento"], eventos[-1].get("tipo")) == (evento_final, tipo)


def test_cenario_normal_passa_pelas_tools_e_cita_a_regra(sem_pausas):
    eventos = perguntar_demo("[demo:normal] Por que a venda VD000084 não entrou?")
    tools = [e["tool"] for e in eventos if e["evento"] == "tool_inicio"]
    assert tools == ["get_venda", "ler_codigo_regra", "buscar_manual"]
    assert "CONS-01" in eventos[-1]["resposta"] and eventos[-1]["metricas"]["chamadas_ao_modelo"] == 3


def test_pergunta_sem_marca_usa_o_cenario_normal(sem_pausas):
    assert perguntar_demo("Por que a venda VD000084 não entrou?")[-1]["evento"] == "fim"


def test_cenario_espera_emite_a_espera_pelo_caminho_real_do_429(sem_pausas):
    eventos = perguntar_demo("[demo:espera] pergunta")
    espera = next(e for e in eventos if e["evento"] == "espera")
    assert espera["segundos"] == 1.0 and espera["motivo"] == "limite_de_uso"
    assert eventos[-1]["metricas"]["segundos_em_espera"] >= 0.9


def test_cenario_interno_nao_mostra_o_detalhe_tecnico(sem_pausas):
    eventos = perguntar_demo("[demo:interno] pergunta")
    assert "falha interna simulada" not in json.dumps(eventos)


def test_cenario_xss_entrega_os_payloads_como_dados(sem_pausas):
    # O servidor não "limpa" o texto: quem garante que ele vira TEXTO é o front-end (textContent).
    eventos = perguntar_demo("[demo:xss] pergunta")
    argumentos = [e["argumentos"] for e in eventos if e["evento"] == "tool_inicio"]
    assert argumentos[0] == {"id_venda": "<img src=x onerror=alert(1)>"}
    for payload in demo.XSS:
        assert payload in eventos[-1]["resposta"]


def test_tools_da_demo_tem_os_mesmos_nomes_das_reais_que_imitam():
    from agentes.tools import TOOLS
    reais = {t.__name__ for t in TOOLS}
    assert {"get_venda", "ler_codigo_regra", "buscar_manual"} <= reais
    assert {t.__name__ for t in demo.TOOLS_DEMO} - reais == {"consulta_lenta"}


# ------------------------------------------------------------------ servir_chat.py
def test_argumentos_padrao():
    args = servir_chat.ler_argumentos([])
    assert (args.host, args.porta, args.timeout, args.agente_falso, args.aceitar_rede) == (
        "127.0.0.1", 8000, 180.0, False, False)


def test_host_de_rede_sem_aceitar_rede_e_recusado():
    with pytest.raises(SystemExit) as saida:
        servir_chat.main(["--host", "0.0.0.0", "--agente-falso"])
    assert "autenticação" in str(saida.value) and "--aceitar-rede" in str(saida.value)


@pytest.fixture
def uvicorn_falso(monkeypatch):
    chamadas = []
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda app, **kw: chamadas.append(kw)))
    return chamadas


def test_modo_demonstracao_nao_le_o_env_nem_exige_chaves(monkeypatch, uvicorn_falso):
    def nao_pode(*a, **k):
        raise AssertionError("o modo demonstração não deve ler o .env")

    monkeypatch.setattr(servir_chat, "carregar_env", nao_pode)
    for nome in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        monkeypatch.delenv(nome, raising=False)
    servir_chat.main(["--agente-falso"])
    assert uvicorn_falso == [{"host": "127.0.0.1", "port": 8000, "log_level": "info", "server_header": False}]


def test_container_pode_escutar_em_todas_as_interfaces_com_a_flag(uvicorn_falso):
    servir_chat.main(["--agente-falso", "--host", "0.0.0.0", "--aceitar-rede", "--porta", "8123"])
    assert (uvicorn_falso[0]["host"], uvicorn_falso[0]["port"]) == ("0.0.0.0", 8123)


@pytest.mark.parametrize("ausente, trecho", [
    ("DATABRICKS_HOST", "DATABRICKS_HOST"),
    ("DATABRICKS_WAREHOUSE_ID", "DATABRICKS_WAREHOUSE_ID"),
    ("LLM_PROVIDER", "LLM_PROVIDER"),
])
def test_env_incompleto_falha_cedo_com_mensagem_clara_e_sem_segredo(monkeypatch, uvicorn_falso, ausente, trecho):
    monkeypatch.setattr(servir_chat, "carregar_env", lambda: True)   # não lê o .env real
    completo = {"DATABRICKS_HOST": "https://dbc-1.cloud.databricks.com", "DATABRICKS_TOKEN": "dapi_segredo_123456",
                "DATABRICKS_WAREHOUSE_ID": "5743803c731887dd", "LLM_PROVIDER": "groq", "LLM_MODEL": "m",
                "GROQ_API_KEY": "gsk_segredo_abcdef"}
    for nome, valor in completo.items():
        monkeypatch.setenv(nome, valor)
    monkeypatch.delenv(ausente)
    with pytest.raises(SystemExit) as saida:
        servir_chat.main([])
    mensagem = str(saida.value)
    assert trecho in mensagem and "verificar_env.py" in mensagem and "--agente-falso" in mensagem
    assert "dapi_segredo_123456" not in mensagem and "gsk_segredo_abcdef" not in mensagem
    assert uvicorn_falso == []                                         # o servidor não subiu


# ------------------------------------------------------------------ Docker
COMPOSE = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")


def bloco_do_servico(nome):
    m = re.search(rf"^  {nome}:\n((?:    .*\n|\s*\n)*)", COMPOSE, re.M)
    assert m, f"serviço {nome} não encontrado"
    return m.group(1)


def test_docker_publica_a_porta_so_em_127_0_0_1():
    chat = bloco_do_servico("chat")
    assert re.search(r'^\s+- "127\.0\.0\.1:8000:8000"\s*$', chat, re.M)
    portas = re.findall(r'^\s+- "([^"]+)"', chat, re.M)
    assert all(p.startswith("127.0.0.1:") for p in portas), portas


def test_docker_usa_o_agente_real_por_padrao_e_so_sobe_quando_pedido():
    chat = bloco_do_servico("chat")
    assert "--agente-falso" not in chat
    assert "--host 0.0.0.0 --aceitar-rede" in chat
    assert re.search(r"profiles:\s*\[\s*\"chat\"\s*\]", chat)
