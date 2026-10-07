from pathlib import Path

import pytest

from ingestao.manual_chunks import extrair_chunks

PDF = Path(__file__).resolve().parent.parent / "docs" / "manual_elegibilidade_v2.3.pdf"

pytestmark = pytest.mark.skipif(not PDF.exists(), reason="PDF do manual não encontrado em docs/")


@pytest.fixture(scope="module")
def chunks():
    return extrair_chunks(str(PDF), versao="2.3")


def por_regra(chunks):
    return {c.regra_id: c for c in chunks if c.tipo == "regra"}


def test_um_chunk_por_regra(chunks):
    ids = sorted(por_regra(chunks))
    assert ids == ["CAP-01", "CAP-02", "CAP-03", "COM-01", "COM-02", "COM-03", "CONS-01", "CONS-02"]


def test_ids_de_chunk_sao_unicos(chunks):
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunk_de_regra_tem_o_parametro_certo(chunks):
    r = por_regra(chunks)
    assert "10 (dez) dias" in r["COM-03"].texto
    assert "90 (noventa) dias" in r["CAP-03"].texto
    assert "moto" in r["CONS-01"].texto


def test_chunk_de_regra_nao_mistura_regras(chunks):
    r = por_regra(chunks)
    assert "CAP-03" not in r["COM-03"].titulo
    assert "Carência: 90" not in r["COM-03"].texto
    assert "Prazo de arrependimento: 10" not in r["CAP-03"].texto


def test_produto_vem_do_prefixo(chunks):
    r = por_regra(chunks)
    assert r["COM-01"].produto == "comum"
    assert r["CONS-02"].produto == "consorcio"
    assert r["CAP-01"].produto == "capitalizacao"


def test_secoes_sem_regra_viram_chunks_proprios(chunks):
    tipos = {c.tipo for c in chunks}
    assert {"geral", "ordem_avaliacao", "quadro_resumo", "precedencia", "historico"} <= tipos


def test_ids_na_tabela_de_ordem_nao_viram_chunks_de_regra(chunks):
    # Na seção 3 os IDs aparecem em tabela; não podem ser tomados por títulos de regra
    ordem = next(c for c in chunks if c.tipo == "ordem_avaliacao")
    assert "COM-02" in ordem.texto


def test_rodape_nao_vaza_para_o_texto(chunks):
    assert all("Alfa Seguridade" not in c.texto for c in chunks)


def test_historico_guarda_valores_antigos(chunks):
    # Atenção: o histórico contém "7 dias" e "60 dias", valores que NÃO estão mais em vigor
    hist = next(c for c in chunks if c.tipo == "historico")
    assert "7 dias" in hist.texto and "60" in hist.texto
