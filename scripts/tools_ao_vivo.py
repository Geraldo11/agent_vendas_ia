"""Teste MANUAL das tools contra o workspace real (não é um teste automatizado).

Uso, na raiz do projeto, dentro do container (precisa de DATABRICKS_HOST, DATABRICKS_TOKEN
e DATABRICKS_WAREHOUSE_ID no .env):

    python scripts/tools_ao_vivo.py
"""
import json
import sys

sys.path.insert(0, ".")

from agentes.ambiente import carregar_env  # noqa: E402

carregar_env()  # lê o .env da raiz do projeto (no container o Docker já fez isso)

from agentes.tools import (buscar_manual, get_carteira_vendedor, get_producao, get_venda,  # noqa: E402
                           ler_codigo_regra, listar_regras_aplicadas, listar_vendas_fora_carteira)
from agentes.tools.config import GOLD, SILVER  # noqa: E402
from agentes.tools.db import executar_sql  # noqa: E402


def mostrar(titulo, valor, limite=1800):
    texto = json.dumps(valor, ensure_ascii=False, indent=2, default=str)
    print(f"\n=== {titulo} ===\n{texto[:limite]}{' ...(cortado)' if len(texto) > limite else ''}")


mostrar("1. Conexão", executar_sql("SELECT current_user() AS usuario, current_catalog() AS catalogo"))

# Pega uma venda real de consórcio de MOTO excluída por CONS-01: é o caso da divergência D3
# (o código exclui moto, mas o manual v2.3 diz que moto entra).
amostra = executar_sql(
    f"SELECT f.id_venda, f.id_vendedor FROM {GOLD}.vendas_fora_carteira f "
    f"JOIN {SILVER}.venda_consorcio c ON c.id_venda = f.id_venda "
    "WHERE f.regra_id = 'CONS-01' AND c.tipo_consorcio = 'moto' AND f.id_vendedor IS NOT NULL LIMIT 1"
)
id_venda, id_vendedor = amostra[0]["id_venda"], amostra[0]["id_vendedor"]
print(f"\n(venda de exemplo: {id_venda} | vendedor: {id_vendedor})")

mostrar("2. get_venda", get_venda(id_venda))
mostrar("3. listar_vendas_fora_carteira", listar_vendas_fora_carteira(id_vendedor, limite=3))
mostrar("4. get_carteira_vendedor", get_carteira_vendedor(id_vendedor, limite=3))
mostrar("5. get_producao", get_producao(id_vendedor))

mostrar("6. listar_regras_aplicadas('consorcio')", listar_regras_aplicadas("consorcio"))
mostrar("7. ler_codigo_regra('COM-03')", ler_codigo_regra("COM-03"))

mostrar("8. buscar_manual(regra_id='COM-03')", buscar_manual(regra_id="COM-03"))
mostrar("9. buscar_manual('prazo de arrependimento')",
        [{k: c[k] for k in ("chunk_id", "score")} for c in buscar_manual("prazo de arrependimento")])

print("\nTudo executou sem erro.")
