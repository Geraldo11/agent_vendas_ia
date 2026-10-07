import pytest

from agentes.tools.db import ENV_OBRIGATORIAS, validar_ambiente

BOM = {
    "DATABRICKS_HOST": "https://dbc-dc0cd492-f516.cloud.databricks.com",
    "DATABRICKS_TOKEN": "dapi0123456789abcdef",
    "DATABRICKS_WAREHOUSE_ID": "abc123def456",
}
TODAS = ENV_OBRIGATORIAS + ("DATABRICKS_WAREHOUSE_ID",)


def test_ambiente_correto_passa():
    validar_ambiente(TODAS, env=BOM)


def test_host_de_exemplo_e_recusado_na_hora():
    env = {**BOM, "DATABRICKS_HOST": "https://SEU-WORKSPACE.cloud.databricks.com"}
    with pytest.raises(RuntimeError, match="DATABRICKS_HOST ainda tem o valor de exemplo"):
        validar_ambiente(TODAS, env=env)


@pytest.mark.parametrize("valor", ["coloque_o_token_aqui", "cole_o_token_aqui"])
def test_token_de_exemplo_e_recusado(valor):
    with pytest.raises(RuntimeError, match="DATABRICKS_TOKEN"):
        validar_ambiente(TODAS, env={**BOM, "DATABRICKS_TOKEN": valor})


def test_warehouse_de_exemplo_e_recusado():
    with pytest.raises(RuntimeError, match="DATABRICKS_WAREHOUSE_ID"):
        validar_ambiente(TODAS, env={**BOM, "DATABRICKS_WAREHOUSE_ID": "coloque_o_id_do_warehouse_aqui"})


def test_variavel_ausente_e_citada_pelo_nome():
    env = {k: v for k, v in BOM.items() if k != "DATABRICKS_TOKEN"}
    with pytest.raises(RuntimeError, match="DATABRICKS_TOKEN não está definida"):
        validar_ambiente(TODAS, env=env)


def test_host_com_parametro_de_workspace_e_recusado():
    env = {**BOM, "DATABRICKS_HOST": "https://dbc-dc0cd492-f516.cloud.databricks.com/?o=520079234478790"}
    with pytest.raises(RuntimeError, match="sem caminho nem"):
        validar_ambiente(TODAS, env=env)


def test_todos_os_problemas_aparecem_juntos():
    with pytest.raises(RuntimeError) as erro:
        validar_ambiente(TODAS, env={})
    texto = str(erro.value)
    assert all(nome in texto for nome in TODAS)


def test_warehouse_so_e_exigido_quando_pedido():
    # A leitura do código no volume só precisa de host e token
    validar_ambiente(ENV_OBRIGATORIAS, env={k: v for k, v in BOM.items() if k != "DATABRICKS_WAREHOUSE_ID"})


@pytest.mark.parametrize("host", [
    "https:////dbc-dc0cd492-f516.cloud.databricks.com",         # barras demais (o seu caso)
    "//dbc-dc0cd492-f516.cloud.databricks.com",                 # faltou o "https:" (o seu caso real)
    "https:///dbc-dc0cd492-f516.cloud.databricks.com",          # três barras
    "https://https://dbc-dc0cd492-f516.cloud.databricks.com",   # https duplicado
    "https//dbc-dc0cd492-f516.cloud.databricks.com",            # faltou o ':'
    "https:/dbc-dc0cd492-f516.cloud.databricks.com",            # uma barra só
    "http://dbc-dc0cd492-f516.cloud.databricks.com",            # http em vez de https
    "dbc-dc0cd492-f516.cloud.databricks.com",                   # sem o https://
])
def test_host_malformado_e_recusado(host):
    with pytest.raises(RuntimeError, match="DATABRICKS_HOST"):
        validar_ambiente(TODAS, env={**BOM, "DATABRICKS_HOST": host})


def test_mensagem_mostra_o_host_recebido_para_voce_ver_o_defeito():
    with pytest.raises(RuntimeError) as erro:
        validar_ambiente(TODAS, env={**BOM, "DATABRICKS_HOST": "https:////dbc-dc0cd492-f516.cloud.databricks.com"})
    assert "https:////dbc-dc0cd492-f516.cloud.databricks.com" in str(erro.value)


def test_barra_final_e_tolerada():
    validar_ambiente(TODAS, env={**BOM, "DATABRICKS_HOST": "https://dbc-dc0cd492-f516.cloud.databricks.com/"})


@pytest.mark.parametrize("token", [
    '"dapi0123456789abcdef"',     # aspas
    "'dapi0123456789abcdef'",     # aspas simples
    "dapi0123456789abcdef ",      # espaço no fim
    "dapi0123 456789abcdef",      # espaço no meio
    "dapi0123456789abcdef\n",     # quebra de linha
])
def test_token_com_aspas_ou_espacos_e_recusado(token):
    with pytest.raises(RuntimeError, match="DATABRICKS_TOKEN contém"):
        validar_ambiente(TODAS, env={**BOM, "DATABRICKS_TOKEN": token})


def test_mensagem_do_token_nao_vaza_o_valor():
    with pytest.raises(RuntimeError) as erro:
        validar_ambiente(TODAS, env={**BOM, "DATABRICKS_TOKEN": '"dapi-segredo-123"'})
    assert "dapi-segredo-123" not in str(erro.value)


from agentes.tools.db import extrair_warehouse_id  # noqa: E402


@pytest.mark.parametrize("valor, esperado", [
    ("5743803c731887dd", "5743803c731887dd"),                          # só o ID
    ("/sql/1.0/warehouses/5743803c731887dd", "5743803c731887dd"),      # o seu caso: caminho completo
    ("/sql/1.0/warehouses/5743803c731887dd/", "5743803c731887dd"),     # com barra no fim
    ("  5743803c731887dd  ", "5743803c731887dd"),                      # espaços ao redor
    ("", ""),
])
def test_extrair_warehouse_id(valor, esperado):
    assert extrair_warehouse_id(valor) == esperado


def test_caminho_completo_do_warehouse_e_aceito_na_validacao():
    validar_ambiente(TODAS, env={**BOM, "DATABRICKS_WAREHOUSE_ID": "/sql/1.0/warehouses/5743803c731887dd"})


@pytest.mark.parametrize("valor", ["warehouse", "meu-warehouse", "/sql/1.0/warehouses/", "xyz123"])
def test_warehouse_que_nao_parece_um_id_e_recusado(valor):
    with pytest.raises(RuntimeError, match="DATABRICKS_WAREHOUSE_ID não parece um ID"):
        validar_ambiente(TODAS, env={**BOM, "DATABRICKS_WAREHOUSE_ID": valor})


# ---------------------------------------------------------------- executar_sql (com cliente falso)
from types import SimpleNamespace  # noqa: E402


def _cliente_falso(registro):
    """Imita o cliente do Databricks: guarda o que recebeu e devolve uma resposta pronta."""
    from databricks.sdk.service.sql import StatementState

    class Statement:
        def execute_statement(self, **kwargs):
            registro.update(kwargs)
            return SimpleNamespace(
                status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None),
                manifest=SimpleNamespace(schema=SimpleNamespace(
                    columns=[SimpleNamespace(name="x", type_name="INT")])),
                result=SimpleNamespace(data_array=[["1"]]),
            )

    return SimpleNamespace(statement_execution=Statement())


def test_executar_sql_envia_so_o_id_do_warehouse(monkeypatch):
    pytest.importorskip("databricks.sdk")        # sem o SDK instalado (ex.: no seu Windows), este teste é pulado
    import agentes.tools.db as db

    registro = {}
    monkeypatch.setattr(db, "obter_cliente", lambda: _cliente_falso(registro))
    for nome, valor in BOM.items():
        monkeypatch.setenv(nome, valor)
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "/sql/1.0/warehouses/5743803c731887dd")

    resultado = db.executar_sql("SELECT :a AS x", {"a": 1})

    assert registro["warehouse_id"] == "5743803c731887dd"      # o caminho completo NÃO vai para a API
    assert registro["parameters"][0].name == "a" and registro["parameters"][0].type == "BIGINT"
    assert resultado == [{"x": 1}]                              # e a resposta volta convertida para int


def test_executar_sql_recusa_ambiente_incompleto_antes_de_chamar_o_databricks(monkeypatch):
    pytest.importorskip("databricks.sdk")
    import agentes.tools.db as db

    registro = {}
    monkeypatch.setattr(db, "obter_cliente", lambda: _cliente_falso(registro))
    for nome in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"):
        monkeypatch.delenv(nome, raising=False)

    with pytest.raises(RuntimeError, match="Configuração do .env incompleta"):
        db.executar_sql("SELECT 1")
    assert registro == {}                                       # nada foi enviado
