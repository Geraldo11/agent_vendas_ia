"""Converte funções Python (as tools) no formato de 'function calling' que o modelo entende.

O modelo não vê o nosso código: ele vê uma descrição (nome, docstring e parâmetros) em JSON.
Geramos essa descrição a partir da própria função, para ela nunca ficar desatualizada.
"""
from __future__ import annotations

import inspect
import typing
from typing import Any, Callable, Dict, Union, get_args, get_origin

_TIPOS_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _tipo_json(anotacao: Any) -> str:
    if get_origin(anotacao) is Union:                 # Optional[str] = Union[str, None]
        restantes = [a for a in get_args(anotacao) if a is not type(None)]
        return _tipo_json(restantes[0]) if restantes else "string"
    return _TIPOS_JSON.get(anotacao, "string")


def esquema_da_tool(funcao: Callable) -> Dict[str, Any]:
    assinatura = inspect.signature(funcao)
    dicas = typing.get_type_hints(funcao)              # resolve anotações escritas como texto
    propriedades: Dict[str, Any] = {}
    obrigatorios = []
    for nome, parametro in assinatura.parameters.items():
        if parametro.kind is inspect.Parameter.KEYWORD_ONLY:
            continue                                   # 'executor' e 'leitor' são dependências, o modelo não os vê
        propriedades[nome] = {"type": _tipo_json(dicas.get(nome, str))}
        if parametro.default is inspect.Parameter.empty:
            obrigatorios.append(nome)
    return {
        "type": "function",
        "function": {
            "name": funcao.__name__,
            "description": inspect.getdoc(funcao) or "",
            "parameters": {"type": "object", "properties": propriedades, "required": obrigatorios},
        },
    }
