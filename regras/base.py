"""Contratos e utilitários comuns a todos os módulos de regras.

Toda regra de negócio do projeto segue o mesmo desenho:

    regra(venda) -> None            # a regra NÃO se aplica: a venda segue para a próxima
    regra(venda) -> Resultado(...)  # a regra BLOQUEIA a venda (fica fora da carteira)

"venda" é um dicionário com os dados da venda já reunidos (ver README das regras).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping, Optional


@dataclass(frozen=True)
class Resultado:
    """Resultado da avaliação de uma venda."""

    elegivel: bool
    regra_id: Optional[str] = None
    motivo: str = "Venda elegível: nenhuma regra de exclusão se aplicou."


Venda = Mapping[str, Any]
Regra = Callable[[Venda], Optional[Resultado]]


def bloqueia(regra_id: str, motivo: str) -> Resultado:
    """Atalho para criar o resultado de uma venda que ficou de fora."""
    return Resultado(elegivel=False, regra_id=regra_id, motivo=motivo)


def executar(venda: Venda, regras: Iterable[Regra]) -> Resultado:
    """Aplica as regras em ordem. A PRIMEIRA que bloquear define o resultado."""
    for regra in regras:
        resultado = regra(venda)
        if resultado is not None:
            return resultado
    return Resultado(elegivel=True)


def vazio(valor: Any) -> bool:
    """True para None e também para NaN/NaT (que o pandas usa no lugar de None).

    Truque: NaN e NaT são os únicos valores diferentes de si mesmos.
    """
    return valor is None or valor != valor


def como_data(valor: Any) -> Optional[date]:
    """Converte datetime/Timestamp em date; devolve None se o valor for vazio."""
    if vazio(valor):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    return valor


def dias_entre(inicio: Any, fim: Any) -> int:
    """Quantidade de dias corridos entre duas datas (fim - inicio)."""
    return (como_data(fim) - como_data(inicio)).days
