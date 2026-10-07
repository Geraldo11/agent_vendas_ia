from .dados import get_carteira_vendedor, get_producao, get_venda, listar_vendas_fora_carteira
from .manual import buscar_manual
from .regras_codigo import ler_codigo_regra, listar_regras_aplicadas

# Registro das tools: é esta lista que vamos entregar aos agentes
TOOLS = [
    get_venda,
    get_carteira_vendedor,
    get_producao,
    listar_vendas_fora_carteira,
    listar_regras_aplicadas,
    ler_codigo_regra,
    buscar_manual,
]

__all__ = [t.__name__ for t in TOOLS] + ["TOOLS"]
