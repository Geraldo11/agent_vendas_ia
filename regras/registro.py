"""Registro de produtos: liga cada produto ao seu módulo de regras.

Para adicionar um produto novo: criar o módulo (com `avaliar_venda`) e registrá-lo aqui.
"""
from __future__ import annotations

from . import capitalizacao, comum, consorcio
from .base import Resultado, Venda, executar

MODULOS = {
    "consorcio": consorcio,
    "capitalizacao": capitalizacao,
}


def avaliar_venda(venda: Venda) -> Resultado:
    """Ponto de entrada único: regras comuns primeiro, depois as do produto."""
    resultado = executar(venda, comum.REGRAS)
    if not resultado.elegivel:
        return resultado

    produto = venda.get("produto")
    modulo = MODULOS.get(produto)
    if modulo is None:
        raise ValueError(f"Produto sem módulo de regras: {produto!r}")
    return modulo.avaliar_venda(venda)
