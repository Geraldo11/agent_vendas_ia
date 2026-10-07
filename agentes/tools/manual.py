"""Tool de MANUAL: busca nos chunks do manual (tabela apoio.manual_chunks).

Busca LEXICAL (por palavras), suficiente para um manual de poucos chunks. Se ficar limitada,
a evolução natural é Vector Search (busca semântica) mantendo esta mesma assinatura.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

from .config import APOIO, LIMITE_MAXIMO
from .db import Executor, executar_sql

_COLUNAS = "chunk_id, tipo, regra_id, produto, titulo, texto, pagina"
_RE_ID_REGRA = re.compile(r"\b(?:COM|CONS|CAP)-\d{2}\b")
_PARADAS = {
    "de", "da", "do", "das", "dos", "que", "para", "uma", "uns", "com", "por", "nao", "qual",
    "quais", "como", "entre", "sobre", "ser", "tem", "foi", "sao", "esta", "este", "essa", "esse",
    "aos", "nas", "nos", "mais", "pelo", "pela", "uma", "num", "numa", "quando", "onde",
}


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto)
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn").lower()


def _tokens(consulta: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _normalizar(consulta)) if len(t) >= 3 and t not in _PARADAS]


def _pontuar(chunk: Dict[str, Any], tokens: List[str], ids_na_consulta: List[str]) -> float:
    texto, titulo = _normalizar(chunk["texto"]), _normalizar(chunk["titulo"])
    pontos = float(sum(texto.count(t) + 3 * titulo.count(t) for t in tokens))
    if chunk["tipo"] == "regra":
        pontos *= 1.5          # perguntas costumam ser sobre uma regra específica
    if chunk["regra_id"] and chunk["regra_id"] in ids_na_consulta:
        pontos += 100          # o usuário citou o ID da regra
    return pontos


def buscar_manual(consulta: str = "", regra_id: Optional[str] = None, incluir_historico: bool = False,
                  limite: int = 3, *, executor: Optional[Executor] = None) -> List[Dict[str, Any]]:
    """Busca trechos do manual de elegibilidade (versão em vigor).

    - `regra_id` (ex.: 'COM-03'): devolve exatamente o trecho dessa regra.
    - `consulta`: busca por palavras (ex.: 'prazo de arrependimento'); devolve os trechos mais relevantes.
    - `incluir_historico`: por padrão o histórico de versões fica de fora, porque contém valores
      ANTIGOS (ex.: prazo de 7 dias). Só use True para perguntas sobre mudanças entre versões.
    """
    exec_ = executor or executar_sql
    limite = max(1, min(int(limite), LIMITE_MAXIMO))

    if regra_id:
        linhas = exec_(f"SELECT {_COLUNAS} FROM {APOIO}.manual_chunks WHERE regra_id = :regra_id",
                       {"regra_id": str(regra_id).strip().upper()})
        return [{**l, "score": None} for l in linhas][:limite]

    chunks = exec_(f"SELECT {_COLUNAS} FROM {APOIO}.manual_chunks", None)
    if not incluir_historico:
        chunks = [c for c in chunks if c["tipo"] != "historico"]

    tokens = _tokens(consulta)
    ids = _RE_ID_REGRA.findall(consulta.upper())
    pontuados = [(_pontuar(c, tokens, ids), c) for c in chunks]
    pontuados = [(p, c) for p, c in pontuados if p > 0]
    pontuados.sort(key=lambda par: par[0], reverse=True)
    return [{**c, "score": round(p, 1)} for p, c in pontuados[:limite]]
