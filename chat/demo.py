"""Modo demonstração: o agente DE VERDADE (executar_agente) com um modelo FALSO e tools FALSAS.

Serve para ver e testar a interface sem gastar tokens e sem Databricks. Como o laço é o real, a
demonstração exercita o mesmo código da vida real: eventos, espera por limite de uso (429), Parar,
classificação de erros.

O cenário vem de uma marca no começo da pergunta, por exemplo "[demo:espera] ...":
  normal         consulta a venda, lê o código e o manual e responde
  espera         o "provedor" pede 8 s de espera (429) antes de responder: contagem regressiva
  lento          várias consultas de ~4 s: use para testar o botão Parar ou o --timeout
  limite         429 com espera longa (limite diário): erro limite_de_uso
  configuracao   chave recusada (HTTP 401): erro configuracao
  provedor       provedor fora do ar (HTTP 503): erro provedor
  interno        falha inesperada: erro interno (detalhe só no log)
  xss            argumentos e resposta com conteúdo malicioso, que deve aparecer como TEXTO
Sem marca (ou marca desconhecida), vale "normal".

Os dados e as respostas são SIMULADOS (não vêm do Databricks nem do gabarito).
"""
from __future__ import annotations

import json
import re
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from agentes.agente import executar_agente
from agentes.llm import ConfigLLM

CONFIG_DEMO = ConfigLLM("demonstracao", "", "", "agente-falso")
PAUSA_DO_MODELO = 0.8          # segundos "pensando" por chamada, para dar para ver as etapas
ESPERA_DO_429 = 8              # segundos que o "provedor" pede no cenário espera
RE_CENARIO = re.compile(r"^\s*\[demo:([a-z_]+)\]", re.I)

XSS = ['<img src=x onerror=alert(1)>', '<script>alert(1)</script>', '[x](javascript:alert(1))', '**<b>**']


def _pausa(segundos: float) -> None:
    """Toda pausa simulada passa por aqui (os testes a trocam por uma que não espera)."""
    time.sleep(segundos)


# ------------------------------------------------------------------ tools falsas (mesmos nomes das reais)
def get_venda(id_venda: str) -> dict:
    """Busca os dados de UMA venda (SIMULADO no modo demonstração)."""
    _pausa(0.6)
    return {"simulado": True, "id_venda": id_venda, "produto": "consorcio", "tipo": "moto",
            "avaliacao": {"elegivel": False, "regra_id": "CONS-01"}}


def ler_codigo_regra(regra_id: str) -> dict:
    """Devolve o código de uma regra (SIMULADO no modo demonstração)."""
    _pausa(0.3)
    return {"simulado": True, "regra_id": regra_id, "constantes": {"TIPOS_ELEGIVEIS": ["imovel", "auto"]}}


def buscar_manual(consulta: str = "", regra_id: Optional[str] = None) -> dict:
    """Busca trechos do manual (SIMULADO no modo demonstração)."""
    _pausa(0.4)
    return {"simulado": True, "trechos": [{"regra_id": regra_id, "texto": "Tipos elegíveis: imóvel, auto e moto."}]}


def consulta_lenta(id_venda: str) -> dict:
    """Consulta demorada (SIMULADO): serve para testar o botão Parar."""
    _pausa(4)
    return {"simulado": True, "id_venda": id_venda}


TOOLS_DEMO = [get_venda, ler_codigo_regra, buscar_manual, consulta_lenta]

RESPOSTA_NORMAL = """**Resposta simulada (modo demonstração).**

A venda **VD000084** não entrou na carteira por causa da regra CONS-01:
- o código aceita só os tipos `imovel` e `auto`;
- o manual v2.3 aceita *imóvel, auto e moto*.

> O manual é a fonte da verdade: segundo ele, esta venda **deveria** ter entrado.

| Fonte | Tipos elegíveis |
|---|---|
| Código | imovel, auto |
| Manual v2.3 | imóvel, auto, moto |"""


# ------------------------------------------------------------------ modelo falso
def _chamada(id_: str, nome: str, argumentos: Dict[str, Any]):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=nome, arguments=json.dumps(argumentos)))


def _resposta(conteudo: Optional[str] = None, chamadas: Optional[List[Any]] = None, entrada=900, saida=120):
    mensagem = SimpleNamespace(content=conteudo, tool_calls=chamadas)
    return SimpleNamespace(choices=[SimpleNamespace(message=mensagem)],
                           usage=SimpleNamespace(prompt_tokens=entrada, completion_tokens=saida))


class ErroSimulado(Exception):
    """Imita os erros HTTP da biblioteca openai (status_code e cabeçalhos)."""

    def __init__(self, mensagem: str, status: int, retry_after: Optional[int] = None):
        super().__init__(mensagem)
        self.status_code = status
        self.response = SimpleNamespace(headers={} if retry_after is None else {"retry-after": str(retry_after)})


def _roteiro(cenario: str) -> List[Any]:
    """O que o modelo falso faz a cada chamada (na ordem)."""
    venda = [_chamada("c1", "get_venda", {"id_venda": "VD000084"})]
    codigo_e_manual = [_chamada("c2", "ler_codigo_regra", {"regra_id": "CONS-01"}),
                       _chamada("c3", "buscar_manual", {"regra_id": "CONS-01"})]
    if cenario == "lento":
        return [_resposta(chamadas=[_chamada(f"l{i}", "consulta_lenta", {"id_venda": f"VD00000{i}"})])
                for i in range(1, 8)] + [_resposta(RESPOSTA_NORMAL)]
    if cenario == "espera":
        return [_resposta(chamadas=venda), ErroSimulado("Rate limit reached (simulado)", 429, retry_after=ESPERA_DO_429),
                _resposta(chamadas=codigo_e_manual), _resposta(RESPOSTA_NORMAL)]
    if cenario == "limite":
        return [ErroSimulado("Rate limit reached: tokens per day (TPD) (simulado)", 429, retry_after=3600)]
    if cenario == "configuracao":
        return [ErroSimulado("Invalid API Key (simulado)", 401)]
    if cenario == "provedor":
        return [_resposta(chamadas=venda), ErroSimulado("Service Unavailable (simulado)", 503)]
    if cenario == "interno":
        return [_resposta(chamadas=venda), RuntimeError("falha interna simulada (este texto só aparece no log)")]
    if cenario == "xss":
        return [_resposta(chamadas=[_chamada("x1", "get_venda", {"id_venda": XSS[0]}),
                                    _chamada("x2", "buscar_manual", {"consulta": XSS[1]})]),
                _resposta("**Resposta simulada com conteúdo malicioso.** Tudo abaixo deve aparecer como texto:\n\n"
                          + "\n".join(f"- {p}" for p in XSS) + "\n\nRegra citada: CAP-03.")]
    return [_resposta(chamadas=venda), _resposta(chamadas=codigo_e_manual), _resposta(RESPOSTA_NORMAL)]


class ModeloDemo:
    """Cliente no formato do openai (cliente.chat.completions.create) que segue um roteiro."""

    def __init__(self, cenario: str):
        self.roteiro = _roteiro(cenario)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._criar))

    def _criar(self, **_kwargs):
        _pausa(PAUSA_DO_MODELO)
        passo = self.roteiro.pop(0) if self.roteiro else _resposta("Fim do roteiro da demonstração.")
        if isinstance(passo, BaseException):
            raise passo
        return passo


def cenario_da_pergunta(pergunta: str) -> str:
    m = RE_CENARIO.match(pergunta)
    return m.group(1).lower() if m else "normal"


def executar_demo(pergunta: str, *, ao_evento, deve_parar, dormir):
    """Executor no mesmo formato do real (ver chat.app.criar_executor_real)."""
    return executar_agente(pergunta, ModeloDemo(cenario_da_pergunta(pergunta)), CONFIG_DEMO.modelo, TOOLS_DEMO,
                           ao_evento=ao_evento, deve_parar=deve_parar, dormir=dormir)
