# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Manual em chunks
# MAGIC Lê o PDF do manual no volume, divide em chunks (um por regra, um por seção)
# MAGIC e grava em `apoio.manual_chunks`. É a base da ferramenta `buscar_manual` dos agentes.
# MAGIC
# MAGIC **Pré-requisitos:** PDF em `/Volumes/vendas_ia/apoio/docs/manuais/` e pastas
# MAGIC `regras/` e `ingestao/` no volume `apoio.docs`.

# COMMAND ----------

# MAGIC %pip install pypdf --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import sys

CATALOG = "vendas_ia"
A = f"{CATALOG}.apoio"

RAIZ = f"/Volumes/{CATALOG}/apoio/docs"
sys.dont_write_bytecode = True
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
for nome in [m for m in sys.modules if m.split(".")[0] in ("regras", "ingestao")]:
    del sys.modules[nome]

from ingestao.manual_chunks import extrair_chunks

PDF = f"{RAIZ}/manuais/manual_elegibilidade_v2.3.pdf"
VERSAO = "2.3"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Dividindo o PDF

# COMMAND ----------

chunks = extrair_chunks(PDF, versao=VERSAO)
print(f"{len(chunks)} chunks | {sum(c.tipo == 'regra' for c in chunks)} de regras")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Conferindo: o manual cobre exatamente as regras do código?
# MAGIC Compara os IDs encontrados no PDF com os IDs das funções em `regras/`.
# MAGIC Se alguém criar uma regra no código e esquecer o manual (ou o contrário), o notebook para aqui.

# COMMAND ----------

from regras import capitalizacao, comum, consorcio


def id_da_funcao(f):
    # com_02_digital_sem_vendedor -> COM-02
    prefixo, numero = f.__name__.split("_")[:2]
    return f"{prefixo.upper()}-{numero}"


ids_codigo = {id_da_funcao(f) for m in (comum, consorcio, capitalizacao) for f in m.REGRAS}
ids_manual = {c.regra_id for c in chunks if c.tipo == "regra"}

print("Só no código :", sorted(ids_codigo - ids_manual))
print("Só no manual :", sorted(ids_manual - ids_codigo))
assert ids_codigo == ids_manual, "IDs de regra do código e do manual não coincidem"
print("OK: o manual cobre exatamente as mesmas regras do código.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Gravando a tabela

# COMMAND ----------

schema = ("chunk_id string, versao_manual string, tipo string, regra_id string, "
          "produto string, titulo string, texto string, pagina int")
linhas = [(c.chunk_id, c.versao_manual, c.tipo, c.regra_id, c.produto, c.titulo, c.texto, c.pagina)
          for c in chunks]

(spark.createDataFrame(linhas, schema)
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(f"{A}.manual_chunks"))

display(spark.table(f"{A}.manual_chunks").drop("texto").orderBy("pagina", "chunk_id"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Olhando um chunk

# COMMAND ----------

print(spark.table(f"{A}.manual_chunks").filter("regra_id = 'COM-03'").first()["texto"])
