"""Tools de CÓDIGO: leem a cópia do código das regras (volume do Databricks) SEM executá-lo.

Usamos o módulo `ast` do Python para analisar o texto do arquivo. Assim o agente enxerga
exatamente o que está no volume, e nenhum código vindo de arquivo é executado.
"""
from __future__ import annotations

import ast
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import VOLUME_REGRAS

LeitorDeFonte = Callable[[str], str]   # recebe o nome do módulo ("comum") e devolve o texto

MODULO_POR_PREFIXO = {"COM": "comum", "CONS": "consorcio", "CAP": "capitalizacao"}
MODULO_POR_PRODUTO = {"consorcio": "consorcio", "capitalizacao": "capitalizacao"}


def leitor_do_volume(modulo: str) -> str:
    from .db import obter_cliente

    resposta = obter_cliente().files.download(f"{VOLUME_REGRAS}/{modulo}.py")
    return resposta.contents.read().decode("utf-8")


def _id_da_funcao(nome: str) -> str:
    # com_02_digital_sem_vendedor -> COM-02
    prefixo, numero = nome.split("_")[:2]
    return f"{prefixo.upper()}-{numero}"


def _analisar(fonte: str) -> Tuple[Dict[str, ast.FunctionDef], List[str], Dict[str, str]]:
    """Devolve (funções do módulo, nomes na ordem de REGRAS, constantes em MAIÚSCULAS)."""
    arvore = ast.parse(fonte)
    funcoes = {n.name: n for n in arvore.body if isinstance(n, ast.FunctionDef)}
    ordem: List[str] = []
    constantes: Dict[str, str] = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
            nome = no.targets[0].id
            if nome == "REGRAS" and isinstance(no.value, ast.List):
                ordem = [e.id for e in no.value.elts if isinstance(e, ast.Name)]
            elif nome.isupper():
                constantes[nome] = ast.get_source_segment(fonte, no.value) or ""
    return funcoes, ordem, constantes


def listar_regras_aplicadas(produto: str, *, leitor: Optional[LeitorDeFonte] = None) -> List[Dict[str, Any]]:
    """Lista, NA ORDEM de avaliação, as regras que o código aplica a um produto.

    `produto` deve ser 'consorcio' ou 'capitalizacao'. Primeiro vêm as regras comuns,
    depois as do produto. A primeira regra que bloqueia a venda define o motivo.
    """
    produto = str(produto).strip().lower()
    if produto not in MODULO_POR_PRODUTO:
        raise ValueError("produto deve ser 'consorcio' ou 'capitalizacao'")
    ler = leitor or leitor_do_volume

    resultado: List[Dict[str, Any]] = []
    for modulo in ("comum", MODULO_POR_PRODUTO[produto]):
        funcoes, ordem, _ = _analisar(ler(modulo))
        for nome in ordem:
            if nome in funcoes:
                resultado.append({
                    "ordem": len(resultado) + 1,
                    "regra_id": _id_da_funcao(nome),
                    "funcao": nome,
                    "arquivo": f"regras/{modulo}.py",
                    "descricao": ast.get_docstring(funcoes[nome]),
                })
    return resultado


def ler_codigo_regra(regra_id: str, *, leitor: Optional[LeitorDeFonte] = None) -> Dict[str, Any]:
    """Devolve o código-fonte da função que implementa uma regra (ex.: 'COM-03').

    Inclui também as constantes do módulo (os parâmetros, como prazos e listas de tipos
    elegíveis), porque são elas que definem os valores que a regra usa.
    """
    regra_id = str(regra_id).strip().upper()
    if not re.fullmatch(r"(COM|CONS|CAP)-\d{2}", regra_id):
        return {"encontrada": False, "regra_id": regra_id, "erro": "ID inválido; use COM-01, CONS-02, CAP-03..."}

    modulo = MODULO_POR_PREFIXO[regra_id.split("-")[0]]
    fonte = (leitor or leitor_do_volume)(modulo)
    funcoes, ordem, constantes = _analisar(fonte)

    for nome in ordem:
        if nome in funcoes and _id_da_funcao(nome) == regra_id:
            return {
                "encontrada": True,
                "regra_id": regra_id,
                "arquivo": f"regras/{modulo}.py",
                "funcao": nome,
                "codigo": ast.get_source_segment(fonte, funcoes[nome]),
                "constantes_do_modulo": constantes,
            }
    return {"encontrada": False, "regra_id": regra_id}
