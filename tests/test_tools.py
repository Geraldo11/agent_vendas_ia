from pathlib import Path

import pytest

from agentes.tools import (TOOLS, buscar_manual, get_carteira_vendedor, get_producao, get_venda,
                           ler_codigo_regra, listar_regras_aplicadas, listar_vendas_fora_carteira)
from agentes.tools.db import converter_valor, linhas_para_dicts
from ingestao.manual_chunks import extrair_chunks

RAIZ = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ apoio
class Gravador:
    """Executor falso: guarda o que foi pedido e devolve respostas prontas."""

    def __init__(self, respostas):
        self.respostas = respostas      # lista de resultados, um por chamada
        self.chamadas = []

    def __call__(self, sql, parametros=None):
        self.chamadas.append((sql, parametros))
        return self.respostas[len(self.chamadas) - 1]


def leitor_local(modulo):
    return (RAIZ / "regras" / f"{modulo}.py").read_text(encoding="utf-8")


LINHA_VENDA = {
    "id_venda": "VD000123", "produto": "consorcio", "id_vendedor": "V0007", "canal": "agencia",
    "data_venda": "2026-05-10", "vendedor_data_inicio": "2025-01-01", "vendedor_data_desligamento": None,
    "data_pagamento": "2026-05-12", "data_cancelamento": None, "tipo_consorcio": "moto",
    "modalidade": None, "forma_pagamento": None, "elegivel": False, "regra_id": "CONS-01",
    "motivo": "Tipo de consórcio 'moto' não gera produção", "na_carteira": False,
}


# ------------------------------------------------------------------ db
def test_converter_valor_por_tipo():
    assert converter_valor("5", "INT") == 5
    assert converter_valor("2.5", "DECIMAL") == 2.5
    assert converter_valor("true", "BOOLEAN") is True
    assert converter_valor("false", "BOOLEAN") is False
    assert converter_valor("2026-05-10", "DATE") == "2026-05-10"
    assert converter_valor(None, "INT") is None


def test_linhas_para_dicts():
    class Col:
        def __init__(self, name, type_name):
            self.name, self.type_name = name, type_name

    cols = [Col("id", "STRING"), Col("qtd", "LONG")]
    assert linhas_para_dicts(cols, [["a", "3"], ["b", "4"]]) == [{"id": "a", "qtd": 3}, {"id": "b", "qtd": 4}]
    assert linhas_para_dicts(cols, None) == []


# ------------------------------------------------------------------ dados
def test_get_venda_monta_o_resultado():
    r = get_venda("VD000123", executor=Gravador([[LINHA_VENDA]]))
    assert r["encontrada"] is True
    assert r["vendedor"]["id_vendedor"] == "V0007"
    assert r["detalhe_do_produto"]["tipo_consorcio"] == "moto"
    assert r["entrou_na_carteira"] is False
    assert r["avaliacao_pelo_codigo"]["regra_id"] == "CONS-01"


def test_get_venda_normaliza_o_id_e_usa_parametro():
    g = Gravador([[LINHA_VENDA]])
    get_venda("  vd000123 ", executor=g)
    sql, params = g.chamadas[0]
    assert params == {"id_venda": "VD000123"}
    assert ":id_venda" in sql and "VD000123" not in sql


def test_get_venda_nao_encontrada():
    r = get_venda("VD999999", executor=Gravador([[]]))
    assert r == {"encontrada": False, "id_venda": "VD999999"}


def test_valor_malicioso_nunca_entra_no_texto_do_sql():
    g = Gravador([[]])
    get_venda("VD1' OR '1'='1", executor=g)
    sql, params = g.chamadas[0]
    assert "OR '1'='1" not in sql                   # o SQL não mudou
    assert "OR '1'='1" in params["id_venda"]        # o valor viaja separado, como dado


def test_get_carteira_vendedor_soma_e_agrupa():
    g = Gravador([
        [{"produto": "capitalizacao", "qtd": 10}, {"produto": "consorcio", "qtd": 25}],
        [{"id_venda": "VD1", "produto": "consorcio", "data_entrada": "2026-05-12"}],
    ])
    r = get_carteira_vendedor("v0007", executor=g)
    assert r["total"] == 35
    assert r["por_produto"] == {"capitalizacao": 10, "consorcio": 25}
    assert g.chamadas[0][1] == {"id_vendedor": "V0007"}


def test_get_carteira_vendedor_filtra_por_produto():
    g = Gravador([[], []])
    get_carteira_vendedor("V0007", produto="Consorcio", executor=g)
    sql, params = g.chamadas[1]
    assert ":produto" in sql and params["produto"] == "consorcio"


def test_limite_e_limitado_ao_maximo():
    g = Gravador([[], []])
    get_carteira_vendedor("V0007", limite=999999, executor=g)
    assert "LIMIT 200" in g.chamadas[1][0]


def test_get_producao_valida_o_mes():
    with pytest.raises(ValueError):
        get_producao("V0007", mes="05/2026", executor=Gravador([[]]))


def test_get_producao_soma():
    g = Gravador([[{"mes": "2026-05", "produto": "consorcio", "qtd_vendas": 4},
                   {"mes": "2026-05", "produto": "capitalizacao", "qtd_vendas": 3}]])
    r = get_producao("V0007", mes="2026-05", executor=g)
    assert r["total_vendas"] == 7
    assert g.chamadas[0][1] == {"id_vendedor": "V0007", "mes": "2026-05"}


def test_listar_vendas_fora_da_carteira():
    g = Gravador([[{"total": 2}], [{"id_venda": "VD1", "regra_id": "CONS-01"}, {"id_venda": "VD2", "regra_id": "CONS-01"}]])
    r = listar_vendas_fora_carteira("V0007", regra_id="cons-01", executor=g)
    assert r["total_fora_da_carteira"] == 2 and len(r["vendas"]) == 2
    assert g.chamadas[0][1] == {"id_vendedor": "V0007", "regra_id": "CONS-01"}


# ------------------------------------------------------------------ código das regras
def test_listar_regras_do_consorcio_na_ordem():
    ids = [r["regra_id"] for r in listar_regras_aplicadas("consorcio", leitor=leitor_local)]
    assert ids == ["COM-02", "COM-01", "COM-03", "CONS-01", "CONS-02"]


def test_listar_regras_da_capitalizacao_na_ordem():
    ids = [r["regra_id"] for r in listar_regras_aplicadas("Capitalizacao", leitor=leitor_local)]
    assert ids == ["COM-02", "COM-01", "COM-03", "CAP-01", "CAP-02", "CAP-03"]


def test_listar_regras_traz_descricao_e_ordem():
    regras = listar_regras_aplicadas("consorcio", leitor=leitor_local)
    assert [r["ordem"] for r in regras] == [1, 2, 3, 4, 5]
    assert all(r["descricao"] for r in regras)


def test_listar_regras_produto_invalido():
    with pytest.raises(ValueError):
        listar_regras_aplicadas("seguro", leitor=leitor_local)


def test_ler_codigo_da_regra_traz_funcao_e_constantes():
    r = ler_codigo_regra("com-03", leitor=leitor_local)
    assert r["encontrada"] and r["arquivo"] == "regras/comum.py"
    assert "def com_03_cancelamento_no_arrependimento" in r["codigo"]
    # Verificamos que o parâmetro EXISTE, não o seu valor (o valor vai mudar quando corrigirmos o código)
    assert "PRAZO_ARREPENDIMENTO_DIAS" in r["constantes_do_modulo"]


def test_ler_codigo_de_regra_inexistente_ou_invalida():
    assert ler_codigo_regra("COM-99", leitor=leitor_local)["encontrada"] is False
    assert ler_codigo_regra("XYZ", leitor=leitor_local)["encontrada"] is False


def test_ler_codigo_nao_executa_nada():
    # A análise é só leitura de texto: um "arquivo" com código perigoso não é executado
    perigoso = "REGRAS = []\nraise SystemExit('não deveria executar')\n"
    assert ler_codigo_regra("COM-01", leitor=lambda m: perigoso)["encontrada"] is False


# ------------------------------------------------------------------ manual
CHUNKS = [c.como_dict() for c in extrair_chunks(str(RAIZ / "docs" / "manual_elegibilidade_v2.3.pdf"), "2.3")]


def executor_manual(sql, parametros=None):
    linhas = list(CHUNKS)
    if parametros and "regra_id" in parametros:
        linhas = [l for l in linhas if l["regra_id"] == parametros["regra_id"]]
    return linhas


def top(consulta, **kw):
    return buscar_manual(consulta, executor=executor_manual, **kw)


def test_busca_por_id_devolve_o_chunk_exato():
    r = buscar_manual(regra_id="com-03", executor=executor_manual)
    assert [c["regra_id"] for c in r] == ["COM-03"]
    assert "10 (dez) dias" in r[0]["texto"]


@pytest.mark.parametrize("consulta, esperado", [
    ("qual o prazo de arrependimento?", "COM-03"),
    ("carência da capitalização", "CAP-03"),
    ("consórcio de moto entra na produção?", "CONS-01"),
    ("1ª parcela não paga", "CONS-02"),
    ("vendedor desligado", "COM-01"),
    ("venda digital sem vendedor", "COM-02"),
    ("modalidade popular", "CAP-01"),
    ("mensalidade", "CAP-02"),
])
def test_busca_por_palavras_acerta_a_regra(consulta, esperado):
    assert top(consulta)[0]["regra_id"] == esperado


def test_id_na_consulta_vence():
    assert top("o que diz a regra CAP-02?")[0]["regra_id"] == "CAP-02"


def test_historico_fica_de_fora_por_padrao():
    assert all(c["tipo"] != "historico" for c in top("prazo de arrependimento 7 dias", limite=10))


def test_historico_aparece_quando_pedido():
    tipos = [c["tipo"] for c in top("versão 2.1 histórico de alterações", incluir_historico=True, limite=10)]
    assert "historico" in tipos


def test_consulta_sem_correspondencia_devolve_vazio():
    assert top("zzzxxx") == []


# ------------------------------------------------------------------ registro
def test_registro_das_tools():
    nomes = [t.__name__ for t in TOOLS]
    assert nomes == ["get_venda", "get_carteira_vendedor", "get_producao",
                     "listar_vendas_fora_carteira", "listar_regras_aplicadas", "ler_codigo_regra", "buscar_manual"]
    assert all(t.__doc__ for t in TOOLS)   # a docstring é o que o agente lê para decidir quando usar a tool
