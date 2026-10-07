"""Regras do produto CAPITALIZAÇÃO (CAP-xx)."""
from __future__ import annotations

from typing import Optional

from .base import Resultado, Venda, bloqueia, dias_entre, executar, vazio

# Só estas modalidades entram na produção do vendedor
MODALIDADES_ELEGIVEIS = frozenset({"tradicional", "incentivo"})

# Cancelamento até este número de dias após a venda (período de carência) não conta
CARENCIA_DIAS = 60


def cap_01_modalidade_elegivel(venda: Venda) -> Optional[Resultado]:
    """CAP-01: só algumas modalidades entram."""
    modalidade = venda.get("modalidade")
    if vazio(modalidade) or modalidade not in MODALIDADES_ELEGIVEIS:
        return bloqueia(
            "CAP-01",
            f"Modalidade '{modalidade}' não gera produção "
            f"(elegíveis: {', '.join(sorted(MODALIDADES_ELEGIVEIS))}).",
        )
    return None


def cap_02_pagamento_realizado(venda: Venda) -> Optional[Resultado]:
    """CAP-02: pagamento único conta na hora; mensal só após a 1ª mensalidade."""
    if vazio(venda.get("data_pagamento")):
        if venda.get("forma_pagamento") == "mensal":
            return bloqueia("CAP-02", "Pagamento mensal: 1ª mensalidade ainda não paga.")
        return bloqueia("CAP-02", "Pagamento único não identificado.")
    return None


def cap_03_cancelamento_na_carencia(venda: Venda) -> Optional[Resultado]:
    """CAP-03: cancelamento durante a carência não conta."""
    cancelamento = venda.get("data_cancelamento")
    if vazio(cancelamento):
        return None
    dias = dias_entre(venda["data_venda"], cancelamento)
    if dias <= CARENCIA_DIAS:
        return bloqueia(
            "CAP-03",
            f"Cancelamento {dias} dia(s) após a venda, dentro da carência de {CARENCIA_DIAS} dias.",
        )
    return None


REGRAS = [
    cap_01_modalidade_elegivel,
    cap_02_pagamento_realizado,
    cap_03_cancelamento_na_carencia,
]


def avaliar_venda(venda: Venda) -> Resultado:
    return executar(venda, REGRAS)
