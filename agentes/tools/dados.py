"""Tools de DADOS: consultam as tabelas silver e gold. Todas são somente leitura.

Cada tool aceita `executor=` (injeção de dependência): em produção usa o Databricks;
nos testes recebe uma função falsa, e assim testamos sem tocar no workspace.

Importante: o que estas tools chamam de "avaliação pelo código" é o resultado das regras
tal como o CÓDIGO as aplica. Ele pode divergir do manual (ver a tabela de divergências).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .config import GOLD, LIMITE_MAXIMO, SILVER
from .db import Executor, executar_sql


def _limite(n: int) -> int:
    # Nomes de tabela e LIMIT não aceitam parâmetro; por isso o LIMIT é convertido em int
    # (e fica entre 1 e o máximo) antes de entrar no texto do SQL.
    return max(1, min(int(n), LIMITE_MAXIMO))


_SQL_VENDA = f"""
SELECT v.id_venda, v.produto, v.id_vendedor, v.canal, v.data_venda,
       ve.data_inicio AS vendedor_data_inicio,
       ve.data_desligamento AS vendedor_data_desligamento,
       s.data_pagamento, s.data_cancelamento,
       co.tipo_consorcio, ca.modalidade, ca.forma_pagamento,
       a.elegivel, a.regra_id, a.motivo,
       (cart.id_venda IS NOT NULL) AS na_carteira
FROM {SILVER}.venda v
LEFT JOIN {SILVER}.vendedor ve ON ve.id_vendedor = v.id_vendedor
LEFT JOIN {SILVER}.venda_status s ON s.id_venda = v.id_venda
LEFT JOIN {SILVER}.venda_consorcio co ON co.id_venda = v.id_venda
LEFT JOIN {SILVER}.venda_capitalizacao ca ON ca.id_venda = v.id_venda
LEFT JOIN {GOLD}.avaliacao_venda a ON a.id_venda = v.id_venda
LEFT JOIN {SILVER}.carteira cart ON cart.id_venda = v.id_venda
WHERE v.id_venda = :id_venda
LIMIT 1
"""


def get_venda(id_venda: str, *, executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Busca os dados de UMA venda pelo número (ex.: 'VD000123').

    Devolve produto, vendedor (com datas de início e desligamento), canal, data da venda,
    datas de pagamento e cancelamento, o tipo/modalidade do produto, se a venda ENTROU na
    carteira, e a avaliação feita pelo código das regras (elegível, regra e motivo).
    Se a venda não existir, devolve {"encontrada": False}.
    """
    chave = str(id_venda).strip().upper()
    linhas = (executor or executar_sql)(_SQL_VENDA, {"id_venda": chave})
    if not linhas:
        return {"encontrada": False, "id_venda": chave}
    l = linhas[0]
    return {
        "encontrada": True,
        "id_venda": l["id_venda"],
        "produto": l["produto"],
        "canal": l["canal"],
        "data_venda": l["data_venda"],
        "vendedor": {
            "id_vendedor": l["id_vendedor"],
            "data_inicio": l["vendedor_data_inicio"],
            "data_desligamento": l["vendedor_data_desligamento"],
        },
        "pagamento_e_cancelamento": {
            "data_pagamento": l["data_pagamento"],
            "data_cancelamento": l["data_cancelamento"],
        },
        "detalhe_do_produto": {
            "tipo_consorcio": l["tipo_consorcio"],
            "modalidade": l["modalidade"],
            "forma_pagamento": l["forma_pagamento"],
        },
        "entrou_na_carteira": bool(l["na_carteira"]),
        "avaliacao_pelo_codigo": {
            "elegivel": l["elegivel"],
            "regra_id": l["regra_id"],
            "motivo": l["motivo"],
        },
    }


def get_carteira_vendedor(id_vendedor: str, produto: Optional[str] = None, limite: int = 20,
                          *, executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Mostra a carteira de um vendedor: total, quantidade por produto e as vendas mais recentes.

    `produto` é opcional ('consorcio' ou 'capitalizacao') e filtra a lista de vendas.
    """
    exec_ = executor or executar_sql
    vendedor = str(id_vendedor).strip().upper()

    por_produto = exec_(
        f"SELECT produto, COUNT(*) AS qtd FROM {GOLD}.carteira_vendedor "
        "WHERE id_vendedor = :id_vendedor GROUP BY produto ORDER BY produto",
        {"id_vendedor": vendedor},
    )

    filtro, params = "", {"id_vendedor": vendedor}
    if produto:
        filtro, params["produto"] = " AND produto = :produto", str(produto).strip().lower()
    vendas = exec_(
        f"SELECT id_venda, produto, data_entrada FROM {GOLD}.carteira_vendedor "
        f"WHERE id_vendedor = :id_vendedor{filtro} ORDER BY data_entrada DESC LIMIT {_limite(limite)}",
        params,
    )
    return {
        "id_vendedor": vendedor,
        "total": sum(int(r["qtd"]) for r in por_produto),
        "por_produto": {r["produto"]: int(r["qtd"]) for r in por_produto},
        "vendas_recentes": vendas,
    }


def get_producao(id_vendedor: str, mes: Optional[str] = None,
                 *, executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Produção de um vendedor (vendas elegíveis por mês e produto).

    `mes` é opcional, no formato 'AAAA-MM' (ex.: '2026-05').
    """
    if mes is not None and not re.fullmatch(r"\d{4}-\d{2}", str(mes)):
        raise ValueError("mes deve estar no formato AAAA-MM, por exemplo '2026-05'")
    vendedor = str(id_vendedor).strip().upper()
    filtro, params = "", {"id_vendedor": vendedor}
    if mes:
        filtro, params["mes"] = " AND date_format(mes, 'yyyy-MM') = :mes", mes
    linhas = (executor or executar_sql)(
        f"SELECT date_format(mes, 'yyyy-MM') AS mes, produto, qtd_vendas "
        f"FROM {GOLD}.producao_vendedor WHERE id_vendedor = :id_vendedor{filtro} ORDER BY mes, produto",
        params,
    )
    return {
        "id_vendedor": vendedor,
        "total_vendas": sum(int(r["qtd_vendas"]) for r in linhas),
        "por_mes_e_produto": linhas,
    }


def listar_vendas_fora_carteira(id_vendedor: str, regra_id: Optional[str] = None, limite: int = 20,
                                *, executor: Optional[Executor] = None) -> Dict[str, Any]:
    """Lista as vendas de um vendedor que NÃO entraram na carteira, com a regra e o motivo.

    É a tool principal para a pergunta "por que minha venda não entrou?". O motivo é o que o
    CÓDIGO das regras decidiu. `regra_id` é opcional (ex.: 'CONS-01') e filtra por regra.
    """
    exec_ = executor or executar_sql
    vendedor = str(id_vendedor).strip().upper()
    filtro, params = "", {"id_vendedor": vendedor}
    if regra_id:
        filtro, params["regra_id"] = " AND regra_id = :regra_id", str(regra_id).strip().upper()

    total = exec_(f"SELECT COUNT(*) AS total FROM {GOLD}.vendas_fora_carteira "
                  f"WHERE id_vendedor = :id_vendedor{filtro}", params)
    vendas = exec_(
        f"SELECT id_venda, produto, canal, data_venda, regra_id, motivo FROM {GOLD}.vendas_fora_carteira "
        f"WHERE id_vendedor = :id_vendedor{filtro} ORDER BY data_venda DESC LIMIT {_limite(limite)}",
        params,
    )
    return {
        "id_vendedor": vendedor,
        "total_fora_da_carteira": int(total[0]["total"]) if total else 0,
        "vendas": vendas,
    }
