"""Regras COMUNS a todos os produtos (COM-xx)."""
from __future__ import annotations

from typing import Optional

from .base import Resultado, Venda, bloqueia, como_data, dias_entre, vazio

# Parâmetro de negócio (o manual em PDF deve dizer o mesmo valor)
PRAZO_ARREPENDIMENTO_DIAS = 7


def com_02_digital_sem_vendedor(venda: Venda) -> Optional[Resultado]:
    """COM-02: venda pelo canal digital sem vendedor identificado fica fora."""
    if venda.get("canal") == "digital" and vazio(venda.get("id_vendedor")):
        return bloqueia("COM-02", "Venda feita pelo canal digital sem vendedor identificado.")
    return None


def com_01_vendedor_ativo(venda: Venda) -> Optional[Resultado]:
    """COM-01: o vendedor precisa estar ativo na data da venda."""
    if vazio(venda.get("id_vendedor")):
        return bloqueia("COM-01", "Venda sem vendedor identificado.")

    data_venda = como_data(venda.get("data_venda"))
    inicio = como_data(venda.get("vendedor_data_inicio"))
    desligamento = como_data(venda.get("vendedor_data_desligamento"))

    if inicio is None:
        return bloqueia("COM-01", "Vendedor não encontrado no cadastro.")
    if data_venda < inicio:
        return bloqueia(
            "COM-01",
            f"Venda em {data_venda:%d/%m/%Y}, antes do início do vendedor ({inicio:%d/%m/%Y}).",
        )
    # Ativo até o dia ANTERIOR ao desligamento. No dia do desligamento já está inativo.
    if desligamento is not None and data_venda >= desligamento:
        return bloqueia(
            "COM-01",
            f"Vendedor desligado em {desligamento:%d/%m/%Y}; venda feita em {data_venda:%d/%m/%Y}.",
        )
    return None


def com_03_cancelamento_no_arrependimento(venda: Venda) -> Optional[Resultado]:
    """COM-03: cancelamento dentro do prazo de arrependimento não conta."""
    cancelamento = venda.get("data_cancelamento")
    if vazio(cancelamento):
        return None
    dias = dias_entre(venda["data_venda"], cancelamento)
    if dias <= PRAZO_ARREPENDIMENTO_DIAS:
        return bloqueia(
            "COM-03",
            f"Cancelamento {dias} dia(s) após a venda, dentro do prazo de "
            f"arrependimento de {PRAZO_ARREPENDIMENTO_DIAS} dias.",
        )
    return None


# Ordem de avaliação das regras comuns
REGRAS = [
    com_02_digital_sem_vendedor,
    com_01_vendedor_ativo,
    com_03_cancelamento_no_arrependimento,
]
