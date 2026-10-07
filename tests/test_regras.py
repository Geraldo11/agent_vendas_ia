from datetime import date, timedelta

import pytest

from regras import avaliar_venda


@pytest.fixture
def consorcio_ok():
    return {
        "id_venda": "VD000001",
        "produto": "consorcio",
        "id_vendedor": "V0001",
        "canal": "agencia",
        "data_venda": date(2026, 5, 10),
        "vendedor_data_inicio": date(2025, 1, 1),
        "vendedor_data_desligamento": None,
        "data_pagamento": date(2026, 5, 12),
        "data_cancelamento": None,
        "tipo_consorcio": "imovel",
        "modalidade": None,
        "forma_pagamento": None,
    }


@pytest.fixture
def cap_ok():
    return {
        "id_venda": "VD000002",
        "produto": "capitalizacao",
        "id_vendedor": "V0001",
        "canal": "agencia",
        "data_venda": date(2026, 5, 10),
        "vendedor_data_inicio": date(2025, 1, 1),
        "vendedor_data_desligamento": None,
        "data_pagamento": date(2026, 5, 10),
        "data_cancelamento": None,
        "tipo_consorcio": None,
        "modalidade": "tradicional",
        "forma_pagamento": "unico",
    }


def com(venda, **mudancas):
    """Cópia da venda com alguns campos alterados."""
    return {**venda, **mudancas}


def cancelada_apos(venda, dias):
    return com(venda, data_cancelamento=venda["data_venda"] + timedelta(days=dias))


# ---------- vendas elegíveis ----------

def test_consorcio_elegivel(consorcio_ok):
    r = avaliar_venda(consorcio_ok)
    assert r.elegivel and r.regra_id is None


def test_capitalizacao_elegivel(cap_ok):
    r = avaliar_venda(cap_ok)
    assert r.elegivel and r.regra_id is None


# ---------- COM-01: vendedor ativo ----------

def test_vendedor_desligado_antes_da_venda(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, vendedor_data_desligamento=date(2026, 4, 1)))
    assert not r.elegivel and r.regra_id == "COM-01"


def test_venda_no_dia_do_desligamento_ja_e_inativo(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, vendedor_data_desligamento=date(2026, 5, 10)))
    assert r.regra_id == "COM-01"


def test_venda_no_dia_anterior_ao_desligamento_ainda_e_ativo(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, vendedor_data_desligamento=date(2026, 5, 11)))
    assert r.elegivel


def test_venda_antes_do_inicio_do_vendedor(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, vendedor_data_inicio=date(2026, 6, 1)))
    assert r.regra_id == "COM-01"


def test_vendedor_inexistente_no_cadastro(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, vendedor_data_inicio=None))
    assert r.regra_id == "COM-01"


# ---------- COM-02: digital sem vendedor ----------

def test_digital_sem_vendedor(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, canal="digital", id_vendedor=None))
    assert r.regra_id == "COM-02"


def test_digital_com_vendedor_e_elegivel(consorcio_ok):
    assert avaliar_venda(com(consorcio_ok, canal="digital")).elegivel


def test_sem_vendedor_em_outro_canal_cai_em_com01(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, canal="agencia", id_vendedor=None))
    assert r.regra_id == "COM-01"


# ---------- COM-03: arrependimento (7 dias) ----------

@pytest.mark.parametrize("dias", [0, 1, 7])
def test_cancelamento_dentro_do_arrependimento(consorcio_ok, dias):
    r = avaliar_venda(cancelada_apos(consorcio_ok, dias))
    assert r.regra_id == "COM-03"


@pytest.mark.parametrize("dias", [8, 30, 90])
def test_cancelamento_apos_arrependimento_consorcio_ainda_conta(consorcio_ok, dias):
    assert avaliar_venda(cancelada_apos(consorcio_ok, dias)).elegivel


# ---------- CONS-01 / CONS-02 ----------

@pytest.mark.parametrize("tipo", ["imovel", "auto"])
def test_tipos_elegiveis(consorcio_ok, tipo):
    assert avaliar_venda(com(consorcio_ok, tipo_consorcio=tipo)).elegivel


@pytest.mark.parametrize("tipo", ["moto", "servicos", None])
def test_tipos_fora(consorcio_ok, tipo):
    r = avaliar_venda(com(consorcio_ok, tipo_consorcio=tipo))
    assert r.regra_id == "CONS-01"


def test_consorcio_sem_primeira_parcela(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, data_pagamento=None))
    assert r.regra_id == "CONS-02"


def test_nan_do_pandas_conta_como_vazio(consorcio_ok):
    r = avaliar_venda(com(consorcio_ok, data_pagamento=float("nan")))
    assert r.regra_id == "CONS-02"


# ---------- CAP-01 / CAP-02 / CAP-03 ----------

@pytest.mark.parametrize("modalidade", ["popular", "instrumento_garantia"])
def test_modalidade_fora(cap_ok, modalidade):
    assert avaliar_venda(com(cap_ok, modalidade=modalidade)).regra_id == "CAP-01"


def test_mensal_sem_primeira_mensalidade(cap_ok):
    r = avaliar_venda(com(cap_ok, forma_pagamento="mensal", data_pagamento=None))
    assert r.regra_id == "CAP-02" and "mensal" in r.motivo.lower()


@pytest.mark.parametrize("dias", [8, 30, 60])
def test_cancelamento_na_carencia(cap_ok, dias):
    assert avaliar_venda(cancelada_apos(cap_ok, dias)).regra_id == "CAP-03"


@pytest.mark.parametrize("dias", [61, 90, 120])
def test_cancelamento_apos_carencia_ainda_conta(cap_ok, dias):
    assert avaliar_venda(cancelada_apos(cap_ok, dias)).elegivel


def test_cancelamento_curto_em_cap_e_com03_e_nao_cap03(cap_ok):
    # Precedência: regras comuns são avaliadas antes das do produto
    assert avaliar_venda(cancelada_apos(cap_ok, 5)).regra_id == "COM-03"


# ---------- precedência e robustez ----------

def test_primeira_regra_que_bloqueia_vence(consorcio_ok):
    # moto (CONS-01) E sem pagamento (CONS-02): CONS-01 vem primeiro
    r = avaliar_venda(com(consorcio_ok, tipo_consorcio="moto", data_pagamento=None))
    assert r.regra_id == "CONS-01"


def test_produto_desconhecido_gera_erro(consorcio_ok):
    with pytest.raises(ValueError):
        avaliar_venda(com(consorcio_ok, produto="seguro"))
