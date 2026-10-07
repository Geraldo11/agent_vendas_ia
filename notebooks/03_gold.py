# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold
# MAGIC Aplica o módulo `regras` (código Python versionado e testado) sobre a silver e produz:
# MAGIC - `gold.avaliacao_venda`: resultado de cada venda (elegível ou não, regra e motivo)
# MAGIC - `gold.vendas_fora_carteira`: só as vendas que ficaram de fora, com a regra e o motivo
# MAGIC - `gold.carteira_vendedor`: carteira CALCULADA pelas regras
# MAGIC - `gold.producao_vendedor`: produção por vendedor, produto e mês
# MAGIC
# MAGIC No fim, compara o resultado com o gabarito e com a carteira da fonte.
# MAGIC
# MAGIC **Pré-requisito:** a pasta `regras/` precisa estar no volume `vendas_ia.apoio.docs`.

# COMMAND ----------

import os
import sys

from pyspark.sql import functions as F

CATALOG = "vendas_ia"
S = f"{CATALOG}.silver"
G = f"{CATALOG}.gold"
A = f"{CATALOG}.apoio"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Carregando o código das regras a partir do volume
# MAGIC O código vive no volume `apoio.docs`, o mesmo lugar que os agentes vão ler depois.

# COMMAND ----------

RAIZ = f"/Volumes/{CATALOG}/apoio/docs"
sys.dont_write_bytecode = True  # não gravar arquivos .pyc dentro do volume

if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# Descarrega versões antigas do módulo, para sempre usar o código mais recente do volume
for nome in [m for m in sys.modules if m == "regras" or m.startswith("regras.")]:
    del sys.modules[nome]

print("Arquivos em regras/:", sorted(os.listdir(f"{RAIZ}/regras")))

from regras import avaliar_venda, MODULOS
print("Produtos com regras registradas:", list(MODULOS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Tabela larga: uma linha por venda com tudo que as regras precisam
# MAGIC Left joins: vendas sem pagamento, sem cancelamento ou de outro produto continuam na tabela, com `null`.

# COMMAND ----------

venda = spark.table(f"{S}.venda")
vendedor = spark.table(f"{S}.vendedor").select(
    "id_vendedor",
    F.col("data_inicio").alias("vendedor_data_inicio"),
    F.col("data_desligamento").alias("vendedor_data_desligamento"),
)
status = spark.table(f"{S}.venda_status")
cons = spark.table(f"{S}.venda_consorcio").select("id_venda", "tipo_consorcio")
cap = spark.table(f"{S}.venda_capitalizacao").select("id_venda", "modalidade", "forma_pagamento")

base = (
    venda.select("id_venda", "produto", "id_vendedor", "canal", "data_venda")
    .join(vendedor, "id_vendedor", "left")
    .join(status, "id_venda", "left")
    .join(cons, "id_venda", "left")
    .join(cap, "id_venda", "left")
)
print("linhas na tabela larga:", base.count())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Aplicando as regras
# MAGIC São ~5 mil linhas, então trazemos para o driver (`toPandas`) e aplicamos a função Python.
# MAGIC Em volume grande, o caminho seria `mapInPandas` ou uma pandas UDF, para distribuir o trabalho.

# COMMAND ----------

registros = base.toPandas().to_dict("records")

linhas = []
for r in registros:
    res = avaliar_venda(r)
    linhas.append((r["id_venda"], res.elegivel, res.regra_id, res.motivo))

avaliacao_df = spark.createDataFrame(
    linhas, schema="id_venda string, elegivel boolean, regra_id string, motivo string"
)

avaliacao = (
    base.select("id_venda", "produto", "id_vendedor", "canal", "data_venda")
    .join(avaliacao_df, "id_venda")
    .withColumn("avaliado_em", F.current_timestamp())
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Gravando as tabelas gold

# COMMAND ----------

def salvar(df, nome):
    (df.write.mode("overwrite").option("overwriteSchema", "true")
       .saveAsTable(f"{G}.{nome}"))
    print(f"gold.{nome}: {spark.table(f'{G}.{nome}').count():,} linhas")


salvar(avaliacao, "avaliacao_venda")

vendas_fora = (
    avaliacao.filter(~F.col("elegivel"))
    .select("id_venda", "produto", "id_vendedor", "canal", "data_venda",
            "regra_id", "motivo", "avaliado_em")
)
salvar(vendas_fora, "vendas_fora_carteira")

carteira_calc = (
    avaliacao.filter("elegivel")
    .join(status.select("id_venda", "data_pagamento"), "id_venda")
    .select("id_vendedor", "id_venda", "produto", F.col("data_pagamento").alias("data_entrada"))
)
salvar(carteira_calc, "carteira_vendedor")

producao = (
    avaliacao.filter("elegivel")
    .withColumn("mes", F.trunc("data_venda", "month"))
    .groupBy("id_vendedor", "produto", "mes")
    .agg(F.count("*").alias("qtd_vendas"))
)
salvar(producao, "producao_vendedor")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Validação 1: o resultado bate com o gabarito?
# MAGIC Para cada venda, comparamos (elegível, regra) calculados com os plantados no notebook 01.

# COMMAND ----------

gab = spark.table(f"{A}.gabarito_casos").select("id_venda", "entra_na_carteira", "regra_esperada")
conf = spark.table(f"{G}.avaliacao_venda").join(gab, "id_venda")

erros = conf.filter(
    (F.col("elegivel") != F.col("entra_na_carteira"))
    | (~F.col("regra_id").eqNullSafe(F.col("regra_esperada")))
)
total, n_erros = conf.count(), erros.count()
print(f"Vendas avaliadas: {total:,} | divergências do gabarito: {n_erros}")
print(f"Acurácia: {(total - n_erros) / total:.2%}")

if n_erros:
    display(erros.select("id_venda", "produto", "elegivel", "regra_id",
                         "entra_na_carteira", "regra_esperada", "motivo").limit(30))
assert n_erros == 0, f"{n_erros} vendas divergem do gabarito"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Validação 2: a carteira calculada é igual à carteira da fonte?

# COMMAND ----------

cols = ["id_venda", "id_vendedor", "data_entrada"]
fonte = spark.table(f"{S}.carteira").select(*cols)
calc = spark.table(f"{G}.carteira_vendedor").select(*cols)

so_calculada = calc.exceptAll(fonte).count()
so_fonte = fonte.exceptAll(calc).count()
print(f"Só na carteira calculada: {so_calculada} | só na carteira da fonte: {so_fonte}")
assert so_calculada == 0 and so_fonte == 0, "carteira calculada diverge da carteira da fonte"
print("As duas carteiras são idênticas.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Resumo: por que as vendas ficaram de fora?

# COMMAND ----------

display(
    spark.table(f"{G}.vendas_fora_carteira")
    .groupBy("regra_id", "produto").count()
    .orderBy("regra_id", "produto")
)

display(spark.table(f"{G}.vendas_fora_carteira").select(
    "id_venda", "produto", "id_vendedor", "regra_id", "motivo").limit(15))
