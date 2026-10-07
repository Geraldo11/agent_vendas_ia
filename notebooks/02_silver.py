# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver
# MAGIC Lê a bronze e produz tabelas **limpas, tipadas e sem duplicidade**.
# MAGIC Não aplica regra de negócio (isso é o gold).
# MAGIC
# MAGIC Rodar em compute **serverless**. O notebook é idempotente (pode rodar várias vezes).

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.window import Window

CATALOG = "vendas_ia"
B = f"{CATALOG}.bronze"
S = f"{CATALOG}.silver"
A = f"{CATALOG}.apoio"

PAGAMENTOS = ["pagamento_1a_parcela", "pagamento_unico", "pagamento_1a_mensalidade"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Conferindo a bronze antes de começar
# MAGIC Se alguma contagem vier zerada, a bronze não foi gerada: rode o notebook 01 antes.

# COMMAND ----------

for t in ["vendedores_raw", "vendas_raw", "consorcio_cotas_raw",
          "capitalizacao_titulos_raw", "eventos_raw", "carteira_raw"]:
    print(f"{t:30s} {spark.table(f'{B}.{t}').count():>8,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Funções auxiliares

# COMMAND ----------

def dedup(df, chaves):
    """Mantém uma linha por chave, a de ingestão mais recente."""
    w = Window.partitionBy(*chaves).orderBy(F.col("_ingestao_ts").desc())
    return df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")


def salvar(df, nome):
    (df.write.mode("overwrite").option("overwriteSchema", "true")
       .saveAsTable(f"{S}.{nome}"))
    print(f"silver.{nome}: {spark.table(f'{S}.{nome}').count():,} linhas")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Vendedor

# COMMAND ----------

vendedor = (
    dedup(spark.table(f"{B}.vendedores_raw"), ["id_vendedor"])
    .select(
        "id_vendedor",
        F.initcap(F.trim("nome")).alias("nome"),
        F.upper(F.trim("agencia")).alias("agencia"),
        F.to_date("data_inicio").alias("data_inicio"),
        F.to_date("data_desligamento").alias("data_desligamento"),
    )
)
salvar(vendedor, "vendedor")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Venda (comum aos dois produtos)

# COMMAND ----------

venda = (
    dedup(spark.table(f"{B}.vendas_raw"), ["id_venda"])
    .select(
        "id_venda",
        F.lower(F.trim("produto")).alias("produto"),
        "id_vendedor",
        F.lower(F.trim("canal")).alias("canal"),
        F.to_date("data_venda").alias("data_venda"),
        "_ingestao_ts",
    )
)
salvar(venda, "venda")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Extensões por produto

# COMMAND ----------

venda_consorcio = (
    dedup(spark.table(f"{B}.consorcio_cotas_raw"), ["id_venda"])
    .select(
        "id_venda",
        F.upper(F.trim("grupo")).alias("grupo"),
        F.col("cota").cast("int").alias("cota"),
        F.lower(F.trim("tipo_consorcio")).alias("tipo_consorcio"),
        F.col("valor_credito").cast("decimal(14,2)").alias("valor_credito"),
        F.col("prazo_meses").cast("int").alias("prazo_meses"),
    )
)
salvar(venda_consorcio, "venda_consorcio")

venda_capitalizacao = (
    dedup(spark.table(f"{B}.capitalizacao_titulos_raw"), ["id_venda"])
    .select(
        "id_venda",
        F.trim("titulo").alias("titulo"),
        F.lower(F.trim("modalidade")).alias("modalidade"),
        F.lower(F.trim("forma_pagamento")).alias("forma_pagamento"),
        F.col("prazo_meses").cast("int").alias("prazo_meses"),
        F.col("valor").cast("decimal(14,2)").alias("valor"),
        F.col("participa_sorteio").cast("boolean").alias("participa_sorteio"),
    )
)
salvar(venda_capitalizacao, "venda_capitalizacao")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Eventos e carteira

# COMMAND ----------

evento_venda = (
    spark.table(f"{B}.eventos_raw")
    .select(
        "id_venda",
        F.lower(F.trim("tipo_evento")).alias("tipo_evento"),
        F.to_date("data_evento").alias("data_evento"),
    )
    .dropDuplicates(["id_venda", "tipo_evento", "data_evento"])
)
salvar(evento_venda, "evento_venda")

carteira = (
    dedup(spark.table(f"{B}.carteira_raw"), ["id_venda"])
    .select(
        "id_venda",
        "id_vendedor",
        F.to_date("data_entrada").alias("data_entrada"),
    )
)
salvar(carteira, "carteira")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Status da venda (uma linha por venda)
# MAGIC Transforma eventos "em linhas" em colunas: `data_pagamento` e `data_cancelamento`.

# COMMAND ----------

eventos_por_venda = (
    spark.table(f"{S}.evento_venda")
    .groupBy("id_venda")
    .agg(
        F.min(F.when(F.col("tipo_evento").isin(PAGAMENTOS), F.col("data_evento"))).alias("data_pagamento"),
        F.min(F.when(F.col("tipo_evento") == "cancelamento", F.col("data_evento"))).alias("data_cancelamento"),
    )
)

venda_status = (
    spark.table(f"{S}.venda").select("id_venda")
    .join(eventos_por_venda, "id_venda", "left")
)
salvar(venda_status, "venda_status")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Validações (data quality)
# MAGIC Qualquer falha interrompe o notebook com uma mensagem clara.

# COMMAND ----------

v = spark.table(f"{S}.venda")

# 1) mesma quantidade de vendas do gabarito
n_gab = spark.table(f"{A}.gabarito_casos").count()
n_venda = v.count()
assert n_venda == n_gab, f"silver.venda tem {n_venda} linhas, gabarito tem {n_gab}"

# 2) sem id_venda repetido
dups = v.groupBy("id_venda").count().filter("count > 1").count()
assert dups == 0, f"{dups} id_venda repetidos em silver.venda"

# 3) sem data_venda nula
nulos = v.filter(F.col("data_venda").isNull()).count()
assert nulos == 0, f"{nulos} vendas sem data_venda"

# 4) canal só com valores esperados
canais = {r["canal"] for r in v.select("canal").distinct().collect()}
assert canais <= {"agencia", "digital", "telefone"}, f"canais inesperados: {canais}"

# 5) todo vendedor referenciado existe
orfaos = (
    v.filter(F.col("id_vendedor").isNotNull())
     .join(spark.table(f"{S}.vendedor"), "id_vendedor", "left_anti")
     .count()
)
assert orfaos == 0, f"{orfaos} vendas apontam para vendedor inexistente"

print("Todas as validações passaram.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Antes e depois (para conferir o efeito da limpeza)

# COMMAND ----------

print("vendas: bronze =", spark.table(f"{B}.vendas_raw").count(), "| silver =", n_venda)

print("\nCanais na bronze:")
display(spark.table(f"{B}.vendas_raw").groupBy("canal").count().orderBy("canal"))

print("Canais no silver:")
display(v.groupBy("canal").count().orderBy("canal"))

# COMMAND ----------

display(spark.table(f"{S}.venda_status").limit(10))
spark.table(f"{S}.venda").printSchema()
