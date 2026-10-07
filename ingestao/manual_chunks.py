"""Divide o manual de elegibilidade (PDF) em chunks, um por regra e um por seção.

Por que dividir assim: cada regra (COM-01, CONS-02...) é um bloco autocontido, com
parâmetro e exemplo. Um chunk por regra permite que a busca devolva exatamente a regra
perguntada, sem misturar o texto de outras.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import List, Optional

from pypdf import PdfReader

_RE_SECAO = re.compile(r"^(\d)\.\s+(\S.*)$")
_RE_REGRA = re.compile(r"^((?:COM|CONS|CAP)-\d{2})\s+-\s+(\S.*)$")
_RE_RODAPE = re.compile(r"^(Alfa Seguridade S\.A\.|Página \d+$)")

# Tipo de chunk das seções que NÃO são regras
TIPO_POR_SECAO = {
    1: "geral",
    2: "geral",
    3: "ordem_avaliacao",
    7: "quadro_resumo",
    8: "precedencia",
    9: "historico",
}
SECOES_DE_REGRAS = {4, 5, 6}
PRODUTO_POR_PREFIXO = {"COM": "comum", "CONS": "consorcio", "CAP": "capitalizacao"}


@dataclass
class Chunk:
    chunk_id: str
    versao_manual: str
    tipo: str                 # regra | geral | ordem_avaliacao | quadro_resumo | precedencia | historico
    regra_id: Optional[str]   # só para tipo 'regra'
    produto: Optional[str]    # comum | consorcio | capitalizacao (só para tipo 'regra')
    titulo: str
    texto: str
    pagina: int               # página onde o chunk começa

    def como_dict(self) -> dict:
        return asdict(self)


def extrair_chunks(caminho_pdf: str, versao: str) -> List[Chunk]:
    leitor = PdfReader(caminho_pdf)
    chunks: List[Chunk] = []
    atual: Optional[dict] = None
    secao = 0

    def fechar() -> None:
        nonlocal atual
        if atual and atual["linhas"]:
            chunks.append(Chunk(
                chunk_id=atual["chunk_id"], versao_manual=versao, tipo=atual["tipo"],
                regra_id=atual["regra_id"], produto=atual["produto"], titulo=atual["titulo"],
                texto="\n".join(atual["linhas"]), pagina=atual["pagina"],
            ))
        atual = None

    for num_pagina, pagina in enumerate(leitor.pages, start=1):
        for bruta in pagina.extract_text().splitlines():
            linha = bruta.strip()
            if not linha or _RE_RODAPE.match(linha):
                continue

            # Título de seção: só vale se for o próximo número da sequência (evita falsos positivos)
            m_secao = _RE_SECAO.match(linha)
            if m_secao and int(m_secao.group(1)) == secao + 1:
                fechar()
                secao = int(m_secao.group(1))
                if secao in TIPO_POR_SECAO:
                    atual = {
                        "chunk_id": f"manual-v{versao}-secao-{secao}", "tipo": TIPO_POR_SECAO[secao],
                        "regra_id": None, "produto": None, "titulo": linha,
                        "pagina": num_pagina, "linhas": [],
                    }
                continue

            # Título de regra: só vale dentro das seções 4, 5 e 6 (na seção 3 os IDs aparecem em tabela)
            m_regra = _RE_REGRA.match(linha) if secao in SECOES_DE_REGRAS else None
            if m_regra:
                fechar()
                regra_id = m_regra.group(1)
                atual = {
                    "chunk_id": f"manual-v{versao}-{regra_id}", "tipo": "regra",
                    "regra_id": regra_id, "produto": PRODUTO_POR_PREFIXO[regra_id.split("-")[0]],
                    "titulo": linha, "pagina": num_pagina, "linhas": [linha],
                }
                continue

            if atual is not None:
                atual["linhas"].append(linha)

    fechar()
    return chunks
