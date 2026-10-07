import json
from datetime import date, timedelta

import pytest

from agentes.casos import CASOS, salvar_casos, selecionar_casos, _sql_do_caso
from regras import avaliar_venda


# ------------------------------------------------------------------ estrutura do conjunto de casos
def test_nomes_unicos():
    nomes = [c.nome for c in CASOS]
    assert len(nomes) == len(set(nomes))


def test_divergencias_e_controles_tem_o_rotulo_certo():
    for c in CASOS:
        if c.nome.startswith("D"):
            assert c.divergencia and c.deve_apontar_divergencia, c.nome
        else:
            assert c.divergencia is None and not c.deve_apontar_divergencia, c.nome


def test_as_quatro_divergencias_estao_cobertas():
    assert sorted(c.divergencia for c in CASOS if c.divergencia) == ["D1", "D2", "D3", "D4"]


def test_expectativas_segundo_o_manual():
    por_nome = {c.nome: c for c in CASOS}
    assert por_nome["D3_moto"].entra_pelo_manual is True          # o manual aceita moto
    assert por_nome["D1_arrependimento_8a10"].entra_pelo_manual is False
    assert por_nome["D2_carencia_61a90"].entra_pelo_manual is False
    assert por_nome["D4_dia_do_desligamento"].entra_pelo_manual is True


def test_d4_e_a_unica_sem_venda_e_a_pergunta_nao_tem_marcadores():
    sem_venda = [c for c in CASOS if c.filtro_sql is None]
    assert [c.nome for c in sem_venda] == ["D4_dia_do_desligamento"]
    assert "{" not in sem_venda[0].pergunta


def test_perguntas_so_usam_marcadores_conhecidos():
    for c in CASOS:
        c.pergunta.format(id_venda="VD1", id_vendedor="V1")      # KeyError se houvesse marcador desconhecido


# ------------------------------------------------------------------ o conjunto é coerente com o CÓDIGO atual
def venda(**kw):
    base = dict(id_venda="VD1", produto="consorcio", id_vendedor="V1", canal="agencia", data_venda=date(2026, 5, 10),
                vendedor_data_inicio=date(2025, 1, 1), vendedor_data_desligamento=None, data_pagamento=date(2026, 5, 11),
                data_cancelamento=None, tipo_consorcio="imovel", modalidade=None, forma_pagamento=None)
    base.update(kw)
    return base


def cap(**kw):
    return venda(**{**dict(produto="capitalizacao", tipo_consorcio=None, modalidade="tradicional",
                           forma_pagamento="unico"), **kw})


DIA = date(2026, 5, 10)
VENDA_DO_CASO = {
    "D3_moto": venda(tipo_consorcio="moto"),
    "D1_arrependimento_8a10": venda(data_cancelamento=DIA + timedelta(days=9)),
    "D2_carencia_61a90": cap(data_cancelamento=DIA + timedelta(days=75)),
    "D4_dia_do_desligamento": venda(vendedor_data_desligamento=DIA),
    "C_servicos": venda(tipo_consorcio="servicos"),
    "C_arrependimento_ate7": venda(data_cancelamento=DIA + timedelta(days=5)),
    "C_carencia_8a60": cap(data_cancelamento=DIA + timedelta(days=30)),
    "C_elegivel_consorcio": venda(),
    "C_elegivel_capitalizacao": cap(),
    "C_vendedor_inativo": venda(vendedor_data_desligamento=date(2026, 4, 1)),
    "C_digital_sem_vendedor": venda(canal="digital", id_vendedor=None),
    "C_sem_primeira_parcela": venda(data_pagamento=None),
    "C_modalidade_fora": cap(modalidade="popular"),
    "C_mensal_sem_mensalidade": cap(forma_pagamento="mensal", data_pagamento=None),
}


def test_todo_caso_tem_uma_venda_de_referencia():
    assert set(VENDA_DO_CASO) == {c.nome for c in CASOS}


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: c.nome)
def test_estado_atual_codigo_discorda_do_manual_so_nas_divergencias(caso):
    """ESTADO ATUAL (divergências D1 a D4 ainda plantadas). Quando o auditor corrigir o código (fase E),
    os casos D1 a D4 passam a concordar e este teste deve ser atualizado de propósito."""
    pelo_codigo = avaliar_venda(VENDA_DO_CASO[caso.nome]).elegivel
    if caso.divergencia:
        assert pelo_codigo != caso.entra_pelo_manual, f"{caso.nome}: deveria divergir do manual"
    else:
        assert pelo_codigo == caso.entra_pelo_manual, f"{caso.nome}: deveria concordar com o manual"


def test_a_regra_citada_pelos_controles_e_a_que_o_codigo_aplica():
    for caso in CASOS:
        if caso.divergencia is None and not caso.entra_pelo_manual:
            assert avaliar_venda(VENDA_DO_CASO[caso.nome]).regra_id in caso.deve_citar


# ------------------------------------------------------------------ seleção no banco (com executor falso)
class Banco:
    def __init__(self, por_consulta=None, linhas_padrao=None):
        self.consultas = []
        self.por_consulta = por_consulta or {}
        self.padrao = linhas_padrao if linhas_padrao is not None else [{"id_venda": "VD000001", "id_vendedor": "V0001"}]

    def __call__(self, sql, parametros=None):
        self.consultas.append(sql)
        for trecho, linhas in self.por_consulta.items():
            if trecho in sql:
                return linhas
        return self.padrao


def test_uma_consulta_por_caso_com_venda_e_o_d4_nao_consulta():
    banco = Banco()
    resultado = selecionar_casos(banco)
    assert len(banco.consultas) == len(CASOS) - 1
    assert len(resultado) == len(CASOS)


def test_a_pergunta_recebe_os_ids_do_banco():
    resultado = selecionar_casos(Banco(linhas_padrao=[{"id_venda": "VD000777", "id_vendedor": "V0042"}]))
    moto = next(r for r in resultado if r["nome"] == "D3_moto")
    assert "VD000777" in moto["pergunta"] and "V0042" in moto["pergunta"]


def test_caso_sem_venda_no_banco_sai_com_aviso():
    resultado = selecionar_casos(Banco(por_consulta={"'moto'": []}))
    moto = next(r for r in resultado if r["nome"] == "D3_moto")
    assert moto["id_venda"] is None and "nenhuma venda" in moto["aviso"]


def test_por_caso_dois_devolve_duas_vendas():
    banco = Banco(linhas_padrao=[{"id_venda": "VD1", "id_vendedor": "V1"}, {"id_venda": "VD2", "id_vendedor": "V2"}])
    resultado = selecionar_casos(banco, por_caso=2)
    assert len([r for r in resultado if r["nome"] == "D3_moto"]) == 2
    assert all("LIMIT 2" in q for q in banco.consultas)


@pytest.mark.parametrize("pedido, limite", [(0, 1), (-3, 1), (1, 1), (99, 5)])
def test_o_limite_e_contido(pedido, limite):
    caso = next(c for c in CASOS if c.filtro_sql)
    assert f"LIMIT {limite}" in _sql_do_caso(caso, pedido)


def test_o_filtro_do_d3_busca_moto_e_o_do_d1_usa_8_a_10_dias():
    sql = {c.nome: _sql_do_caso(c, 1) for c in CASOS if c.filtro_sql}
    assert "co.tipo_consorcio = 'moto'" in sql["D3_moto"]
    assert "BETWEEN 8 AND 10" in sql["D1_arrependimento_8a10"]
    assert "BETWEEN 61 AND 90" in sql["D2_carencia_61a90"]


def test_a_sintaxe_do_sql_e_valida_no_dialeto_databricks():
    sqlglot = pytest.importorskip("sqlglot")          # opcional: sem a biblioteca, o teste é pulado
    for c in CASOS:
        if c.filtro_sql:
            sqlglot.parse_one(_sql_do_caso(c, 1), read="databricks")


# ------------------------------------------------------------------ gravação
def test_salvar_cria_a_pasta_e_o_json_pode_ser_relido(tmp_path):
    destino = tmp_path / "avaliacao" / "casos.json"
    casos = selecionar_casos(Banco())
    salvar_casos(casos, destino)
    relido = json.loads(destino.read_text(encoding="utf-8"))
    assert [c["nome"] for c in relido] == [c.nome for c in CASOS]
    assert "filtro_sql" not in relido[0]                # o SQL não vai para o arquivo de avaliação
