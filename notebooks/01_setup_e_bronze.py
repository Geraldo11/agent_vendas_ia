# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Setup + Bronze sintética
# MAGIC Cria catálogo/schemas/volumes e gera dados sintéticos de **consórcio** e **capitalização**
# MAGIC com casos de borda plantados (gabarito em `apoio.gabarito_casos`).
# MAGIC
# MAGIC Rodar em compute **serverless**.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Parâmetros

# COMMAND ----------

import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
from pyspark.sql import functions as F

CATALOG = "vendas_ia"   # se não puder criar catálogo, troque por um existente
SEED = 42
N_VENDEDORES = 60
N_VENDAS = 5000
DATA_INI = date(2026, 1, 1)
DATA_FIM = date(2026, 8, 31)

rng = np.random.default_rng(SEED)
rnd = random.Random(SEED)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Estrutura no Unity Catalog

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"USE CATALOG {CATALOG}")

for schema in ["bronze", "silver", "gold", "apoio"]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")

# raw: arquivos brutos | docs: manuais em PDF e código das regras
spark.sql("CREATE VOLUME IF NOT EXISTS bronze.raw")
spark.sql("CREATE VOLUME IF NOT EXISTS apoio.docs")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Definição dos casos plantados
# MAGIC Cada venda nasce com um `caso`. Os casos "ok" entram na carteira; os demais ficam de fora.

# COMMAND ----------

CASOS_CONS = [
    ("ok", .85), ("ok_cancelamento_apos_prazo", .05),
    ("vendedor_inativo", .02), ("digital_sem_vendedor", .02),
    ("cancelamento_arrependimento", .015),
    ("tipo_fora", .03), ("sem_1a_parcela", .015),
]
CASOS_CAP = [
    ("ok", .85), ("ok_cancelamento_apos_prazo", .04),
    ("vendedor_inativo", .02), ("digital_sem_vendedor", .02),
    ("cancelamento_arrependimento", .015),
    ("modalidade_fora", .03), ("mensal_sem_1a_mensalidade", .015),
    ("cancelamento_carencia", .01),
]

REGRA_ESPERADA = {
    "vendedor_inativo": "COM-01",
    "digital_sem_vendedor": "COM-02",
    "cancelamento_arrependimento": "COM-03",
    "tipo_fora": "CONS-01",
    "sem_1a_parcela": "CONS-02",
    "modalidade_fora": "CAP-01",
    "mensal_sem_1a_mensalidade": "CAP-02",
    "cancelamento_carencia": "CAP-03",
}

PRAZO_ARREPENDIMENTO = 7   # dias
CARENCIA_CAP = 60          # dias

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Vendedores

# COMMAND ----------

def rand_date(a, b):
    return a + timedelta(days=int(rng.integers(0, (b - a).days + 1)))

vendedores = []
for i in range(N_VENDEDORES):
    inicio = date(2024, 1, 1) + timedelta(days=int(rng.integers(0, 600)))
    deslig = None
    if i >= N_VENDEDORES - 10:  # 10 vendedores desligados em 2026
        deslig = date(2026, 3, 1) + timedelta(days=int(rng.integers(0, 120)))
    vendedores.append({
        "id_vendedor": f"V{i+1:04d}",
        "nome": f"Vendedor {i+1}",
        "agencia": f"AG{int(rng.integers(1, 15)):03d}",
        "data_inicio": inicio.isoformat(),
        "data_desligamento": deslig.isoformat() if deslig else None,
    })

desligados = [v for v in vendedores if v["data_desligamento"]]

def vendedores_ativos_em(d):
    ativos = []
    for v in vendedores:
        ini = date.fromisoformat(v["data_inicio"])
        fim = date.fromisoformat(v["data_desligamento"]) if v["data_desligamento"] else date(2100, 1, 1)
        if ini <= d < fim:
            ativos.append(v)
    return ativos

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Vendas, extensões por produto, eventos, carteira e gabarito

# COMMAND ----------

TIPOS_CONS = {  # (min credito, max credito, min prazo, max prazo)
    "imovel": (150_000, 600_000, 180, 240),
    "auto": (40_000, 150_000, 60, 100),
    "moto": (10_000, 35_000, 36, 60),
    "servicos": (5_000, 30_000, 24, 48),
}

vendas, cons, caps, eventos, carteira, gabarito = [], [], [], [], [], []

for i in range(N_VENDAS):
    id_venda = f"VD{i+1:06d}"
    produto = "consorcio" if rng.random() < 0.6 else "capitalizacao"
    casos = CASOS_CONS if produto == "consorcio" else CASOS_CAP
    caso = str(rng.choice([c for c, _ in casos], p=[w for _, w in casos]))

    canal = str(rng.choice(["agencia", "digital", "telefone"], p=[.5, .3, .2]))
    data_venda = rand_date(DATA_INI, DATA_FIM)
    id_vendedor = None

    if caso == "vendedor_inativo":
        v = rnd.choice(desligados)
        d = date.fromisoformat(v["data_desligamento"])
        data_venda = min(d + timedelta(days=int(rng.integers(5, 60))), DATA_FIM)
        id_vendedor = v["id_vendedor"]
    elif caso == "digital_sem_vendedor":
        canal = "digital"
        id_vendedor = None
    else:
        id_vendedor = rnd.choice(vendedores_ativos_em(data_venda))["id_vendedor"]

    # --- extensão por produto
    if produto == "consorcio":
        tipo = str(rng.choice(["moto", "servicos"] if caso == "tipo_fora" else ["imovel", "auto"]))
        cmin, cmax, pmin, pmax = TIPOS_CONS[tipo]
        cons.append({
            "id_venda": id_venda,
            "grupo": f"G{int(rng.integers(1000, 1100))}",
            "cota": int(rng.integers(1, 301)),
            "tipo_consorcio": tipo,
            "valor_credito": float(rng.integers(cmin, cmax)),
            "prazo_meses": int(rng.integers(pmin, pmax + 1)),
        })
        evento_pgto = "pagamento_1a_parcela"
        tem_pgto = caso != "sem_1a_parcela"
    else:
        modalidade = str(rng.choice(["popular", "instrumento_garantia"] if caso == "modalidade_fora"
                                    else ["tradicional", "incentivo"]))
        forma = "mensal" if caso == "mensal_sem_1a_mensalidade" else str(rng.choice(["unico", "mensal"]))
        caps.append({
            "id_venda": id_venda,
            "titulo": f"T{i+1:07d}",
            "modalidade": modalidade,
            "forma_pagamento": forma,
            "prazo_meses": int(rng.choice([12, 24, 36, 48])),
            "valor": float(rng.integers(1000, 20000)) if forma == "unico" else float(rng.integers(50, 500)),
            "participa_sorteio": bool(rng.random() < 0.7),
        })
        evento_pgto = "pagamento_unico" if forma == "unico" else "pagamento_1a_mensalidade"
        tem_pgto = caso != "mensal_sem_1a_mensalidade"

    vendas.append({
        "id_venda": id_venda,
        "produto": produto,
        "id_vendedor": id_vendedor,
        "canal": canal,
        "data_venda": data_venda.isoformat(),
    })

    # --- eventos
    data_pgto = None
    if tem_pgto:
        data_pgto = data_venda + timedelta(days=int(rng.integers(0, 4 if "cancelamento" in caso else 11)))
        eventos.append({"id_venda": id_venda, "tipo_evento": evento_pgto, "data_evento": data_pgto.isoformat()})

    dias_cancel = None
    if caso == "cancelamento_arrependimento":
        dias_cancel = int(rng.integers(1, PRAZO_ARREPENDIMENTO + 1))
    elif caso == "cancelamento_carencia":
        dias_cancel = int(rng.integers(PRAZO_ARREPENDIMENTO + 1, CARENCIA_CAP + 1))
    elif caso == "ok_cancelamento_apos_prazo":
        dias_cancel = int(rng.integers(8, 91)) if produto == "consorcio" else int(rng.integers(CARENCIA_CAP + 1, 121))
    if dias_cancel:
        eventos.append({"id_venda": id_venda, "tipo_evento": "cancelamento",
                        "data_evento": (data_venda + timedelta(days=dias_cancel)).isoformat()})

    # --- carteira (o que efetivamente entrou) e gabarito
    entra = caso.startswith("ok")
    if entra:
        carteira.append({"id_venda": id_venda, "id_vendedor": id_vendedor,
                         "data_entrada": data_pgto.isoformat()})
    gabarito.append({"id_venda": id_venda, "produto": produto, "caso": caso,
                     "entra_na_carteira": entra, "regra_esperada": REGRA_ESPERADA.get(caso)})

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Sujeira controlada na `vendas_raw` (para o silver limpar)
# MAGIC 1% de duplicatas e variação de caixa/espaços no canal.

# COMMAND ----------

df_vendas = pd.DataFrame(vendas)
dups = df_vendas.sample(frac=0.01, random_state=SEED)
df_vendas = pd.concat([df_vendas, dups], ignore_index=True)

def suja_canal(c):
    r = rnd.random()
    if r < 0.03: return c.upper()
    if r < 0.05: return f" {c} "
    return c

df_vendas["canal"] = df_vendas["canal"].apply(suja_canal)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Gravação das tabelas

# COMMAND ----------

def salvar(df_pd, nome, schema="bronze", ingestao=True):
    sdf = spark.createDataFrame(df_pd)
    if ingestao:
        sdf = sdf.withColumn("_ingestao_ts", F.current_timestamp())
    (sdf.write.mode("overwrite").option("overwriteSchema", "true")
        .saveAsTable(f"{CATALOG}.{schema}.{nome}"))

salvar(pd.DataFrame(vendedores), "vendedores_raw")
salvar(df_vendas, "vendas_raw")
salvar(pd.DataFrame(cons), "consorcio_cotas_raw")
salvar(pd.DataFrame(caps), "capitalizacao_titulos_raw")
salvar(pd.DataFrame(eventos), "eventos_raw")
salvar(pd.DataFrame(carteira), "carteira_raw")
salvar(pd.DataFrame(gabarito), "gabarito_casos", schema="apoio", ingestao=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Conferência

# COMMAND ----------

for t in ["vendedores_raw", "vendas_raw", "consorcio_cotas_raw",
          "capitalizacao_titulos_raw", "eventos_raw", "carteira_raw"]:
    print(t, spark.table(f"{CATALOG}.bronze.{t}").count())

display(spark.sql(f"""
    SELECT produto, caso, entra_na_carteira, regra_esperada, COUNT(*) AS qtd
    FROM {CATALOG}.apoio.gabarito_casos
    GROUP BY ALL ORDER BY produto, caso
"""))
