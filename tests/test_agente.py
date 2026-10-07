import copy
import json
from types import SimpleNamespace

import pytest

from agentes.agente import MAX_CARACTERES_DO_RESULTADO, executar_agente
from agentes.esquemas import esquema_da_tool
from agentes.llm import configuracao_do_llm
from agentes.tools import TOOLS


# ------------------------------------------------------------------ apoio: um "modelo" de mentira
def texto(conteudo):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo, tool_calls=None))])


def chamada(id_, nome, argumentos):
    args = argumentos if isinstance(argumentos, str) else json.dumps(argumentos)
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=nome, arguments=args))


def pedido_de_tools(*chamadas):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=list(chamadas)))])


class ModeloFalso:
    """Devolve respostas combinadas de antemão e guarda o que o agente enviou."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._criar))

    def _criar(self, **kwargs):
        self.pedidos.append(copy.deepcopy(kwargs))
        assert self.respostas, "o agente chamou o modelo mais vezes do que o previsto"
        return self.respostas.pop(0)


def somar(a: int, b: int) -> dict:
    """Soma dois números inteiros."""
    return {"soma": a + b}


def explodir(x: str) -> dict:
    """Tool que sempre falha na validação."""
    raise ValueError("valor inválido")


def quebrar(x: str) -> dict:
    """Tool com falha de infraestrutura."""
    raise RuntimeError("warehouse fora do ar")


def enorme(x: str) -> dict:
    """Devolve um resultado gigante."""
    return {"lixo": "x" * (MAX_CARACTERES_DO_RESULTADO * 3)}


FERRAMENTAS = [somar, explodir, quebrar, enorme]


def rodar(modelo, **kw):
    return executar_agente("pergunta", modelo, "modelo-x", FERRAMENTAS, **kw)


def mensagens_tool(modelo, indice_do_pedido):
    return [m for m in modelo.pedidos[indice_do_pedido]["messages"] if m["role"] == "tool"]


# ------------------------------------------------------------------ o laço
def test_resposta_direta_sem_tools():
    r = rodar(ModeloFalso([texto("olá")]))
    assert r.resposta == "olá" and r.passos == [] and not r.parou_por_limite


def test_executa_a_tool_pedida_e_devolve_o_resultado_ao_modelo():
    m = ModeloFalso([pedido_de_tools(chamada("c1", "somar", {"a": 2, "b": 3})), texto("deu 5")])
    r = rodar(m)
    assert r.resposta == "deu 5"
    (passo,) = r.passos
    assert (passo["tool"], passo["argumentos"], passo["erro"]) == ("somar", '{"a": 2, "b": 3}', False)
    assert passo["segundos"] >= 0
    ferramenta = mensagens_tool(m, 1)[0]            # 2º pedido ao modelo já contém o resultado
    assert ferramenta["tool_call_id"] == "c1" and json.loads(ferramenta["content"]) == {"soma": 5}


def test_mensagem_do_assistente_com_a_chamada_entra_na_conversa():
    m = ModeloFalso([pedido_de_tools(chamada("c1", "somar", {"a": 1, "b": 1})), texto("ok")])
    rodar(m)
    assistente = [x for x in m.pedidos[1]["messages"] if x["role"] == "assistant"][0]
    assert assistente["tool_calls"][0]["function"]["name"] == "somar"


def test_envia_a_lista_de_tools_e_o_prompt_do_sistema():
    m = ModeloFalso([texto("ok")])
    rodar(m)
    pedido = m.pedidos[0]
    assert pedido["messages"][0]["role"] == "system"
    assert [t["function"]["name"] for t in pedido["tools"]] == ["somar", "explodir", "quebrar", "enorme"]


def test_varias_tools_no_mesmo_passo():
    m = ModeloFalso([pedido_de_tools(chamada("c1", "somar", {"a": 1, "b": 2}), chamada("c2", "somar", {"a": 3, "b": 4})),
                     texto("pronto")])
    r = rodar(m)
    assert [json.loads(x["content"])["soma"] for x in mensagens_tool(m, 1)] == [3, 7]
    assert len(r.passos) == 2


# ------------------------------------------------------------------ robustez: o modelo erra e o agente não cai
@pytest.mark.parametrize("pedido, trecho", [
    (chamada("c1", "nao_existe", {}), "tool desconhecida"),
    (chamada("c1", "somar", "{isto nao e json"), "JSON válido"),
    (chamada("c1", "somar", "[1, 2]"), "objeto JSON"),
    (chamada("c1", "somar", {"a": 1}), "argumentos incorretos"),
    (chamada("c1", "explodir", {"x": "a"}), "valor inválido"),
    (chamada("c1", "quebrar", {"x": "a"}), "falha ao executar a tool (RuntimeError)"),
])
def test_erros_viram_mensagem_para_o_modelo_e_o_laco_continua(pedido, trecho):
    m = ModeloFalso([pedido_de_tools(pedido), texto("me corrigi")])
    r = rodar(m)
    assert r.resposta == "me corrigi"
    assert trecho in json.loads(mensagens_tool(m, 1)[0]["content"])["erro"]
    assert r.passos[0]["erro"] is True


def test_argumento_fora_do_esquema_e_barrado():
    # O modelo tenta injetar 'executor', um parâmetro que NÃO é dele
    m = ModeloFalso([pedido_de_tools(chamada("c1", "somar", {"a": 1, "b": 2, "executor": "x"})), texto("ok")])
    rodar(m)
    assert "não permitidos" in json.loads(mensagens_tool(m, 1)[0]["content"])["erro"]


def test_resultado_gigante_e_truncado():
    m = ModeloFalso([pedido_de_tools(chamada("c1", "enorme", {"x": "a"})), texto("ok")])
    rodar(m)
    conteudo = json.loads(mensagens_tool(m, 1)[0]["content"])
    assert conteudo["truncado"] is True and len(conteudo["inicio_do_resultado"]) == MAX_CARACTERES_DO_RESULTADO


def test_limite_de_passos_impede_laco_infinito():
    m = ModeloFalso([pedido_de_tools(chamada(f"c{i}", "somar", {"a": 1, "b": 1})) for i in range(3)])
    r = rodar(m, max_passos=3)
    assert r.parou_por_limite and "limite de passos" in r.resposta and len(r.passos) == 3


# ------------------------------------------------------------------ esquemas das tools
def esquema(nome):
    return next(esquema_da_tool(t) for t in TOOLS if t.__name__ == nome)["function"]


def test_esquema_de_get_venda():
    e = esquema("get_venda")
    assert e["parameters"]["properties"] == {"id_venda": {"type": "string"}}
    assert e["parameters"]["required"] == ["id_venda"]
    assert "Busca os dados de UMA venda" in e["description"]


def test_esquema_opcionais_e_tipos():
    e = esquema("buscar_manual")["parameters"]
    assert e["properties"]["incluir_historico"] == {"type": "boolean"}
    assert e["properties"]["limite"] == {"type": "integer"}
    assert e["required"] == []                          # todos têm valor padrão


def test_esquema_nao_expoe_dependencias_de_teste():
    for tool in TOOLS:
        propriedades = esquema_da_tool(tool)["function"]["parameters"]["properties"]
        assert "executor" not in propriedades and "leitor" not in propriedades


def test_todas_as_tools_reais_geram_esquema_valido():
    nomes = [esquema_da_tool(t)["function"]["name"] for t in TOOLS]
    assert len(nomes) == len(set(nomes)) == 7
    for t in TOOLS:
        assert esquema_da_tool(t)["function"]["description"]


# ------------------------------------------------------------------ configuração do modelo
def test_config_databricks_usa_o_host_e_o_token():
    c = configuracao_do_llm({"LLM_PROVIDER": "databricks", "LLM_MODEL": "databricks-gpt-oss-20b",
                             "DATABRICKS_HOST": "https://dbc-1.cloud.databricks.com/", "DATABRICKS_TOKEN": "dapi123"})
    assert c.base_url == "https://dbc-1.cloud.databricks.com/serving-endpoints" and c.api_key == "dapi123"


def test_config_ollama_tem_padrao_para_o_docker():
    c = configuracao_do_llm({"LLM_PROVIDER": "ollama", "LLM_MODEL": "qwen3:8b"})
    assert c.base_url == "http://host.docker.internal:11434/v1" and c.modelo == "qwen3:8b"


@pytest.mark.parametrize("env, trecho", [
    ({}, "LLM_PROVIDER"),
    ({"LLM_PROVIDER": "inventado", "LLM_MODEL": "x"}, "LLM_PROVIDER"),
    ({"LLM_PROVIDER": "ollama"}, "LLM_MODEL"),
    ({"LLM_PROVIDER": "compat", "LLM_MODEL": "x"}, "LLM_BASE_URL"),
    ({"LLM_PROVIDER": "databricks", "LLM_MODEL": "x"}, "DATABRICKS_HOST"),
])
def test_config_incompleta_explica_o_que_falta(env, trecho):
    with pytest.raises(RuntimeError, match=trecho):
        configuracao_do_llm(env)


# ------------------------------------------------------------------ Groq: configuração
GROQ_OK = {"LLM_PROVIDER": "groq", "LLM_MODEL": "llama-3.3-70b-versatile", "GROQ_API_KEY": "gsk_abc123XYZ"}


def test_config_groq_usa_a_chave_e_o_endereco_padrao():
    c = configuracao_do_llm(GROQ_OK)
    assert c.base_url == "https://api.groq.com/openai/v1"
    assert c.api_key == "gsk_abc123XYZ" and c.modelo == "llama-3.3-70b-versatile"


@pytest.mark.parametrize("chave, trecho", [
    ("", "exige GROQ_API_KEY"),
    ('"gsk_abc123"', "espaço, aspas"),
    ("gsk_abc 123", "espaço, aspas"),
    ("coloque_a_chave_aqui", "valor de exemplo"),
    ("cole_sua_chave", "valor de exemplo"),
])
def test_config_groq_recusa_chave_ruim(chave, trecho):
    with pytest.raises(RuntimeError, match=trecho):
        configuracao_do_llm({**GROQ_OK, "GROQ_API_KEY": chave})


def test_mensagem_de_erro_nao_vaza_a_chave():
    with pytest.raises(RuntimeError) as erro:
        configuracao_do_llm({**GROQ_OK, "GROQ_API_KEY": '"gsk_segredo_999"'})
    assert "gsk_segredo_999" not in str(erro.value)


# ------------------------------------------------------------------ contagem de tokens
def com_uso(resposta, entrada, saida):
    resposta.usage = SimpleNamespace(prompt_tokens=entrada, completion_tokens=saida)
    return resposta


def test_soma_os_tokens_de_todas_as_chamadas():
    m = ModeloFalso([
        com_uso(pedido_de_tools(chamada("c1", "somar", {"a": 1, "b": 2})), 1000, 50),
        com_uso(texto("pronto"), 1400, 80),
    ])
    r = rodar(m)
    assert (r.chamadas_ao_modelo, r.tokens_entrada, r.tokens_saida) == (2, 2400, 130)


def test_sem_informacao_de_uso_os_tokens_ficam_zerados():
    r = rodar(ModeloFalso([texto("ok")]))                # o modelo falso não traz 'usage'
    assert (r.chamadas_ao_modelo, r.tokens_entrada, r.tokens_saida) == (1, 0, 0)


# ------------------------------------------------------------------ erro 429 (limite de uso)
class Erro429(Exception):
    def __init__(self, retry_after=None, status=429, mensagem="rate limit"):
        super().__init__(mensagem)
        self.status_code = status
        self.response = SimpleNamespace(headers={} if retry_after is None else {"retry-after": str(retry_after)})


class ModeloQueFalha:
    """Falha com os erros dados e depois responde."""

    def __init__(self, erros, resposta_final):
        self.erros, self.final, self.chamadas = list(erros), resposta_final, 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._criar))

    def _criar(self, **kwargs):
        self.chamadas += 1
        if self.erros:
            raise self.erros.pop(0)
        return self.final


def test_429_espera_o_tempo_pedido_pelo_servidor_e_tenta_de_novo():
    esperas = []
    m = ModeloQueFalha([Erro429(retry_after=20)], texto("deu certo"))
    r = executar_agente("p", m, "x", FERRAMENTAS, dormir=esperas.append)
    assert r.resposta == "deu certo" and m.chamadas == 2
    assert esperas == [21.0]                              # 20 s pedidos + 1 s de folga


def test_429_sem_dica_do_servidor_usa_espera_crescente():
    esperas = []
    m = ModeloQueFalha([Erro429(), Erro429()], texto("ok"))
    executar_agente("p", m, "x", FERRAMENTAS, dormir=esperas.append)
    assert esperas == [16.0, 31.0]                        # 15+1 e 30+1


def test_429_com_espera_longa_e_limite_diario_e_nao_espera():
    from agentes.agente import LimiteDeUsoAtingido
    esperas = []
    m = ModeloQueFalha([Erro429(retry_after=3600, mensagem="tokens per day (TPD) atingido")], texto("nunca"))
    with pytest.raises(LimiteDeUsoAtingido, match="tokens per day"):
        executar_agente("p", m, "x", FERRAMENTAS, dormir=esperas.append)
    assert esperas == [] and m.chamadas == 1


def test_429_persistente_esgota_as_tentativas():
    from agentes.agente import LimiteDeUsoAtingido
    m = ModeloQueFalha([Erro429(retry_after=1) for _ in range(10)], texto("nunca"))
    with pytest.raises(LimiteDeUsoAtingido):
        executar_agente("p", m, "x", FERRAMENTAS, dormir=lambda s: None, max_tentativas_429=3)
    assert m.chamadas == 3


def test_outros_erros_nao_sao_engolidos():
    m = ModeloQueFalha([Erro429(status=401, mensagem="chave inválida")], texto("nunca"))
    with pytest.raises(Exception, match="chave inválida"):
        executar_agente("p", m, "x", FERRAMENTAS, dormir=lambda s: None)
    assert m.chamadas == 1


# ------------------------------------------------------------------ medição de tempo
def test_mede_o_tempo_de_cada_tool_e_o_total():
    import time as _t

    def lenta(x: str) -> dict:
        """Tool lenta de propósito."""
        _t.sleep(0.06)
        return {"ok": True}

    m = ModeloFalso([pedido_de_tools(chamada("c1", "lenta", {"x": "a"})), texto("pronto")])
    r = executar_agente("p", m, "x", [lenta])
    assert r.passos[0]["segundos"] >= 0.05
    assert r.segundos_nas_tools >= 0.05
    assert r.segundos_no_modelo < r.segundos_nas_tools          # o modelo falso responde na hora
    assert r.segundos_em_espera == 0.0


def test_o_tempo_de_espera_por_429_e_separado_do_tempo_do_modelo():
    import time as _t
    m = ModeloQueFalha([Erro429(retry_after=0)], texto("ok"))
    r = executar_agente("p", m, "x", FERRAMENTAS, dormir=lambda s: _t.sleep(0.06))
    assert r.segundos_em_espera >= 0.05
    assert r.segundos_no_modelo < 0.05                           # a espera NÃO conta como tempo do modelo
