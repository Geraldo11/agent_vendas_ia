"""Transforma exceções em mensagens SEGURAS para o navegador.

Regra de ouro: o navegador recebe só {tipo, mensagem} em português. Traceback, caminhos do servidor e
valores do .env nunca saem daqui; o detalhe técnico vai para o log do servidor, também sem segredos.

Tipos de erro: limite_de_uso, provedor, configuracao, tempo_esgotado, interno.
(O "Parar" do usuário não é erro: vira o evento 'cancelado', montado em app.py.)
"""
from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from agentes.agente import LimiteDeUsoAtingido
from agentes.llm import ConfigLLM, explicar_erro_do_provedor

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
SUFIXOS_SECRETOS = ("KEY", "TOKEN", "SECRET")
TAMANHO_MINIMO_DE_SEGREDO = 8      # valores vazios ou curtos destruiriam a mensagem ("".replace troca tudo)
MENSAGEM_INTERNA = "Erro interno ao processar a pergunta. O detalhe técnico ficou no log do servidor."


def valores_secretos(env: Optional[Mapping[str, str]] = None) -> List[str]:
    """Valores das variáveis cujo nome termina em KEY, TOKEN ou SECRET, do maior para o menor
    (o maior primeiro: se um segredo contém outro, o maior é trocado inteiro)."""
    env = os.environ if env is None else env
    valores = {(valor or "").strip() for nome, valor in env.items() if nome.upper().endswith(SUFIXOS_SECRETOS)}
    return sorted((v for v in valores if len(v) >= TAMANHO_MINIMO_DE_SEGREDO), key=len, reverse=True)


def remover_segredos(texto: str, env: Optional[Mapping[str, str]] = None) -> str:
    """Troca segredos por *** e o caminho do projeto por <projeto>."""
    for valor in valores_secretos(env):
        texto = texto.replace(valor, "***")
    return texto.replace(str(RAIZ), "<projeto>")


def evento_de_erro(tipo: str, mensagem: str, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    return {"evento": "erro", "tipo": tipo, "mensagem": remover_segredos(mensagem, env)}


def classificar_erro(erro: BaseException, config: ConfigLLM,
                     env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Exceção -> evento 'erro' seguro. Na dúvida, 'interno' com mensagem genérica (sem str(erro))."""
    if isinstance(erro, LimiteDeUsoAtingido):
        return evento_de_erro("limite_de_uso", str(erro), env)

    status = getattr(erro, "status_code", None)
    if status in (400, 401, 403, 404) or getattr(erro, "code", None) == "model_not_found":
        # cliente=None: no 404 não consultamos a lista de modelos (seria mais uma chamada ao provedor)
        explicacao = explicar_erro_do_provedor(erro, config) or f"O provedor recusou o pedido (HTTP {status})."
        return evento_de_erro("provedor" if status == 400 else "configuracao", explicacao, env)
    if isinstance(status, int) and status >= 500:
        return evento_de_erro("provedor", f"O provedor do modelo está com problemas (HTTP {status}). "
                                          "Tente de novo em instantes.", env)
    if type(erro).__name__ in ("APIConnectionError", "APITimeoutError"):
        return evento_de_erro("provedor", "Não consegui falar com o provedor do modelo (conexão recusada ou "
                                          "tempo esgotado). Confira a internet e tente de novo.", env)
    return evento_de_erro("interno", MENSAGEM_INTERNA, env)


def registrar_erro(erro: BaseException, env: Optional[Mapping[str, str]] = None) -> None:
    """Traceback completo no log do servidor, mas sem segredos e sem o caminho do projeto."""
    detalhe = "".join(traceback.format_exception(type(erro), erro, erro.__traceback__))
    log.error("falha ao responder a pergunta:\n%s", remover_segredos(detalhe, env))
