"""Leitura do arquivo .env: carrega variáveis para o ambiente e DIAGNOSTICA problemas de formato.

Por que existe: o Python não lê o .env sozinho. No container, o Docker Compose injeta as variáveis
(`env_file`); no PowerShell do Windows ninguém injeta. `carregar_env()` resolve os dois casos.

Regras do carregamento:
  - só preenche variáveis AUSENTES ou VAZIAS no ambiente (o que já está definido tem prioridade);
  - valor vazio no arquivo (`NOME=`) é ignorado, para nunca anular um valor preenchido;
  - se um nome aparece mais de uma vez, vale o último valor NÃO vazio.
Nada aqui imprime valores: os diagnósticos falam só de nomes e situações.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, MutableMapping, Optional, Tuple

RAIZ = Path(__file__).resolve().parent.parent
_RE_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class LinhaEnv:
    numero: int
    nome: str
    valor: Optional[str]          # None quando a linha não tem '='
    problema: Optional[str] = None


def ler_env(caminho: Path) -> Tuple[str, List[str]]:
    """Lê o arquivo e devolve (texto, avisos de codificação). Aceita UTF-8, UTF-8 com BOM e UTF-16."""
    bruto = Path(caminho).read_bytes()
    avisos: List[str] = []
    if bruto.startswith((b"\xff\xfe", b"\xfe\xff")):
        avisos.append("arquivo salvo em UTF-16 (comum com `echo ... > .env` no PowerShell); salve como UTF-8")
        return bruto.decode("utf-16").lstrip("\ufeff"), avisos
    if bruto.startswith(b"\xef\xbb\xbf"):
        avisos.append("arquivo UTF-8 com BOM; o Docker pode ignorar a primeira variável. Salve como UTF-8 sem BOM")
        return bruto.decode("utf-8-sig").lstrip("\ufeff"), avisos
    return bruto.decode("utf-8", errors="replace"), avisos


def analisar_env(texto: str) -> List[LinhaEnv]:
    """Interpreta o texto do .env linha a linha, marcando o que está fora do formato NOME=valor."""
    linhas: List[LinhaEnv] = []
    for numero, bruta in enumerate(texto.splitlines(), start=1):
        corpo = bruta.strip()
        if not corpo or corpo.startswith("#"):
            continue
        problema = "espaço no início da linha (remova)" if bruta != bruta.lstrip() else None
        if corpo.startswith("export "):
            corpo = corpo[len("export "):].lstrip()
        if "=" not in corpo:
            linhas.append(LinhaEnv(numero, corpo, None, "sem '=' (o formato é NOME=valor)"))
            continue
        nome, valor = (parte.strip() for parte in corpo.split("=", 1))
        if not _RE_NOME.match(nome):
            problema = problema or "nome de variável inválido"
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]                      # aspas externas, como o Docker e o dotenv fazem
        linhas.append(LinhaEnv(numero, nome, valor, problema))
    return linhas


def valores_do_env(linhas: List[LinhaEnv]) -> Dict[str, str]:
    """Nome -> valor, ignorando linhas inválidas e valores vazios; o último valor não vazio vence."""
    valores: Dict[str, str] = {}
    for l in linhas:
        if l.valor:
            valores[l.nome] = l.valor
    return valores


def carregar_env(caminho: Optional[Path] = None, ambiente: Optional[MutableMapping[str, str]] = None) -> bool:
    """Carrega o .env da raiz do projeto. Devolve False se o arquivo não existir."""
    ambiente = os.environ if ambiente is None else ambiente
    arquivo = Path(caminho) if caminho else RAIZ / ".env"
    if not arquivo.exists():
        return False
    texto, _ = ler_env(arquivo)
    for nome, valor in valores_do_env(analisar_env(texto)).items():
        if not (ambiente.get(nome) or "").strip():
            ambiente[nome] = valor
    return True


def diagnosticar(texto: str, avisos_de_codificacao: Optional[List[str]] = None) -> List[str]:
    """Lista de problemas encontrados no .env, em português, SEM revelar nenhum valor."""
    problemas = [f"codificação: {a}" for a in (avisos_de_codificacao or [])]
    linhas = analisar_env(texto)
    por_nome: Dict[str, List[LinhaEnv]] = {}
    for l in linhas:
        if l.problema:
            problemas.append(f"linha {l.numero} ({l.nome}): {l.problema}")
        por_nome.setdefault(l.nome, []).append(l)
    for nome, ocorrencias in por_nome.items():
        if len(ocorrencias) > 1:
            numeros = ", ".join(str(o.numero) for o in ocorrencias)
            ultima_vazia = not (ocorrencias[-1].valor or "")
            extra = " A ÚLTIMA ESTÁ VAZIA e, no Docker, anula as anteriores." if ultima_vazia else ""
            problemas.append(f"{nome} aparece {len(ocorrencias)} vezes (linhas {numeros}).{extra}")
        elif ocorrencias[0].valor == "":
            problemas.append(f"linha {ocorrencias[0].numero} ({nome}): valor vazio")
    return problemas
