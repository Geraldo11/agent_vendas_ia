"""Regras do produto CONSÓRCIO (CONS-xx)."""
from __future__ import annotations

from typing import Optional

from .base import Resultado, Venda, bloqueia, executar, vazio

# Só estes tipos de consórcio entram na produção do vendedor
TIPOS_ELEGIVEIS = frozenset({"imovel", "auto"})


def cons_01_tipo_elegivel(venda: Venda) -> Optional[Resultado]:
    """CONS-01: só consórcio de imóvel e auto entra."""
    tipo = venda.get("tipo_consorcio")
    if vazio(tipo) or tipo not in TIPOS_ELEGIVEIS:
        return bloqueia(
            "CONS-01",
            f"Tipo de consórcio '{tipo}' não gera produção "
            f"(elegíveis: {', '.join(sorted(TIPOS_ELEGIVEIS))}).",
        )
    return None


def cons_02_primeira_parcela_paga(venda: Venda) -> Optional[Resultado]:
    """CONS-02: a venda só conta após o pagamento da 1ª parcela."""
    if vazio(venda.get("data_pagamento")):
        return bloqueia("CONS-02", "Primeira parcela ainda não paga.")
    return None


REGRAS = [
    cons_01_tipo_elegivel,
    cons_02_primeira_parcela_paga,
]


def avaliar_venda(venda: Venda) -> Resultado:
    return executar(venda, REGRAS)
