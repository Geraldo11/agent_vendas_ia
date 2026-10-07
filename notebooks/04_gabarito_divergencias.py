# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Gabarito de divergências (código x manual)
# MAGIC O manual v2.3 e o código das regras divergem **de propósito** em 4 pontos.
# MAGIC Este notebook registra essas divergências em `apoio.gabarito_divergencias`
# MAGIC (a "resposta certa" para avaliar o futuro agente auditor) e mede quantas vendas cada uma afeta.
# MAGIC
# MAGIC **Fonte da verdade: o manual.** O código está desatualizado em relação a ele.
# MAGIC
# MAGIC **Pré-requisitos:** gold gerado (notebook 03) e pasta `regras/` no volume `apoio.docs`.

# COMMAND ----------

import sys

CATALOG = "vendas_ia"
S, G, A = f"{CATALOG}.silver", f"{CATALOG}.gold", f"{CATALOG}.apoio"

RAIZ = f"/Volumes/{CATALOG}/apoio/docs"
sys.dont_write_bytecode = True
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
for nome in [m for m in sys.modules if m == "regras" or m.startswith("regras.")]:
    del sys.modules[nome]

from regras import capitalizacao, comum, consorcio

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Valores do código (lidos do próprio código) e do manual v2.3 (copiados do PDF)

# COMMAND ----------

# --- o que o CÓDIGO diz (lido direto dos módulos, para nunca ficar desatualizado aqui)
COD_ARREP = comum.PRAZO_ARREPENDIMENTO_DIAS
COD_CARENCIA = capitalizacao.CARENCIA_DIAS
COD_TIPOS = set(consorcio.TIPOS_ELEGIVEIS)

# --- o que o MANUAL v2.3 diz (seções 4, 5, 6 e 7 do PDF)
MAN_ARREP = 10
MAN_CARENCIA = 90
MAN_TIPOS = {"imovel", "auto", "moto"}

print("Código :", COD_ARREP, "dias |", COD_CARENCIA, "dias |", sorted(COD_TIPOS))
print("Manual :", MAN_ARREP, "dias |", MAN_CARENCIA, "dias |", sorted(MAN_TIPOS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Impacto de cada divergência nos dados
# MAGIC Quantas vendas hoje **elegíveis pelo código** mudariam de resultado se valesse o manual.

# COMMAND ----------

def contar(sql):
    return spark.sql(sql).first()[0]


# D1: consórcio cancelado entre (prazo do código + 1) e (prazo do manual) dias
n_d1 = contar(f"""
    SELECT COUNT(*) FROM {G}.avaliacao_venda a
    JOIN {S}.venda_status s USING (id_venda)
    WHERE a.produto = 'consorcio' AND a.elegivel
      AND datediff(s.data_cancelamento, a.data_venda) BETWEEN {COD_ARREP + 1} AND {MAN_ARREP}
""")

# D2: capitalização cancelada entre (carência do código + 1) e (carência do manual) dias
n_d2 = contar(f"""
    SELECT COUNT(*) FROM {G}.avaliacao_venda a
    JOIN {S}.venda_status s USING (id_venda)
    WHERE a.produto = 'capitalizacao' AND a.elegivel
      AND datediff(s.data_cancelamento, a.data_venda) BETWEEN {COD_CARENCIA + 1} AND {MAN_CARENCIA}
""")

# D3: vendas bloqueadas por CONS-01 em tipos que o manual aceita e o código não
extras = sorted(MAN_TIPOS - COD_TIPOS)
lista_sql = ", ".join(f"'{t}'" for t in extras)
n_d3 = contar(f"""
    SELECT COUNT(*) FROM {G}.avaliacao_venda a
    JOIN {S}.venda_consorcio c USING (id_venda)
    WHERE a.regra_id = 'CONS-01' AND c.tipo_consorcio IN ({lista_sql})
""")

# D4: vendas feitas exatamente no dia do desligamento do vendedor
n_d4 = contar(f"""
    SELECT COUNT(*) FROM {G}.avaliacao_venda a
    JOIN {S}.vendedor v USING (id_vendedor)
    WHERE a.data_venda = v.data_desligamento
""")

print({"D1": n_d1, "D2": n_d2, "D3": n_d3, "D4": n_d4})

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Gravando o gabarito

# COMMAND ----------

def obs(n):
    return "latente: nenhuma venda afetada nos dados atuais" if n == 0 else "afeta vendas existentes"

linhas = [
    ("D1", "COM-03", "Prazo de arrependimento (dias corridos)",
     str(COD_ARREP), str(MAN_ARREP), "manual",
     f"Alterar PRAZO_ARREPENDIMENTO_DIAS de {COD_ARREP} para {MAN_ARREP} em regras/comum.py",
     int(n_d1), obs(n_d1)),
    ("D2", "CAP-03", "Carência da capitalização (dias corridos)",
     str(COD_CARENCIA), str(MAN_CARENCIA), "manual",
     f"Alterar CARENCIA_DIAS de {COD_CARENCIA} para {MAN_CARENCIA} em regras/capitalizacao.py",
     int(n_d2), obs(n_d2)),
    ("D3", "CONS-01", "Tipos de consórcio elegíveis",
     ", ".join(sorted(COD_TIPOS)), ", ".join(sorted(MAN_TIPOS)), "manual",
     f"Incluir {', '.join(extras)} em TIPOS_ELEGIVEIS em regras/consorcio.py",
     int(n_d3), obs(n_d3)),
    ("D4", "COM-01", "Vendedor no dia do desligamento",
     "inativo (venda no dia do desligamento é bloqueada)",
     "ativo até a data de desligamento, inclusive (venda no dia é elegível)", "manual",
     "Trocar a comparação 'data_venda >= desligamento' por 'data_venda > desligamento' em regras/comum.py",
     int(n_d4), obs(n_d4)),
]

schema = ("id_divergencia string, regra_id string, aspecto string, valor_codigo string, "
          "valor_manual string, fonte_da_verdade string, correcao_esperada string, "
          "vendas_impactadas int, observacao string")

(spark.createDataFrame(linhas, schema)
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{A}.gabarito_divergencias"))

display(spark.table(f"{A}.gabarito_divergencias").orderBy("id_divergencia"))
