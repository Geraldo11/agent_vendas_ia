"""Configuração comum das tools."""

CATALOG = "vendas_ia"
SILVER = f"{CATALOG}.silver"
GOLD = f"{CATALOG}.gold"
APOIO = f"{CATALOG}.apoio"

# Onde está a CÓPIA do código das regras que os agentes leem (a mesma que o pipeline usa)
VOLUME_REGRAS = f"/Volumes/{CATALOG}/apoio/docs/regras"

# Variável de ambiente com o ID do SQL Warehouse (campo "HTTP path" termina com esse ID)
ENV_WAREHOUSE = "DATABRICKS_WAREHOUSE_ID"

LIMITE_MAXIMO = 200
