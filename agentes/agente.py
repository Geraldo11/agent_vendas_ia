"""O agente: um laço que deixa o modelo escolher tools até ter dados para responder.

Ciclo (cada volta é um 'passo'):
  1. mandamos ao modelo a conversa + a lista de tools;
  2. se ele pedir tools, NÓS as executamos e devolvemos os resultados;
  3. se ele responder com texto, terminou.

O modelo nunca executa nada: só pede. Quem executa é este código, que só aceita tools
registradas e só passa os argumentos que a tool declara.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from .esquemas import esquema_da_tool

PROMPT_DO_SISTEMA = """Você é um assistente de análise de vendas de consórcio e capitalização.
Sua tarefa é explicar, com base em dados e regras, por que uma venda não entrou na carteira de um \
vendedor (ou confirmar que entrou).

Como trabalhar:
1. Descubra a venda ou o vendedor da pergunta. Use get_venda (uma venda) ou listar_vendas_fora_carteira (várias).
2. Identifique a regra que o código aplicou (regra_id) e leia o código dela com ler_codigo_regra, \
incluindo as constantes do módulo.
3. Leia o que o manual diz sobre essa mesma regra com buscar_manual(regra_id=...).
4. Compare o código com o manual. O MANUAL É A FONTE DA VERDADE: se divergirem, informe a divergência, \
diga que o manual prevalece e diga se a venda deveria ou não ter entrado segundo o manual.

Regras:
- Nunca invente dados, números de venda, vendedores, valores ou trechos do manual. Afirme só o que as tools retornaram.
- Se uma tool retornar erro ou "encontrada": false, diga isso claramente e não prossiga como se tivesse os dados.
- Cite sempre os IDs das regras (ex.: COM-03, CONS-01) e os valores relevantes (datas, prazos, tipos).
- Não use o histórico de versões do manual, a menos que a pergunta seja sobre mudanças entre versões.
- Responda em português, de forma direta, em até 10 linhas."""

MAX_CARACTERES_DO_RESULTADO = 8000
ESPERA_MAXIMA_EM_429 = 90        # acima disso é limite DIÁRIO: esperar não adianta, avisamos o usuário


class LimiteDeUsoAtingido(RuntimeError):
    """O provedor recusou por excesso de uso (HTTP 429) e esperar não resolve (ou esgotou as tentativas)."""


@dataclass
class ResultadoDoAgente:
    resposta: str
    passos: List[Dict[str, Any]] = field(default_factory=list)   # registro de cada tool chamada
    parou_por_limite: bool = False
    chamadas_ao_modelo: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    segundos_no_modelo: float = 0.0      # tempo falando com o modelo, SEM contar esperas de 429
    segundos_nas_tools: float = 0.0      # tempo executando tools (consultas ao Databricks, leitura de código...)
    segundos_em_espera: float = 0.0      # tempo dormindo por causa de limite de uso (429)


def _para_texto(valor: Any) -> str:
    texto = json.dumps(valor, ensure_ascii=False, default=str)
    if len(texto) > MAX_CARACTERES_DO_RESULTADO:
        # Resultado enorme estoura o contexto de modelos pequenos; devolvemos só o começo, avisando.
        return json.dumps({"truncado": True, "inicio_do_resultado": texto[:MAX_CARACTERES_DO_RESULTADO]},
                          ensure_ascii=False)
    return texto


def _executar_tool(nome: str, argumentos_json: str, tools: Dict[str, Callable],
                   esquemas: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Executa UMA tool pedida pelo modelo. Qualquer problema vira um dicionário de erro
    que o modelo lê e pode corrigir na próxima volta; nada derruba o agente."""
    if nome not in tools:
        return {"erro": f"tool desconhecida: {nome!r}. Disponíveis: {sorted(tools)}"}
    try:
        argumentos = json.loads(argumentos_json or "{}")
    except json.JSONDecodeError:
        return {"erro": "os argumentos não são um JSON válido"}
    if not isinstance(argumentos, dict):
        return {"erro": "os argumentos devem ser um objeto JSON"}

    permitidos = set(esquemas[nome]["function"]["parameters"]["properties"])
    nao_permitidos = sorted(set(argumentos) - permitidos)
    if nao_permitidos:
        # Barra, por exemplo, o modelo tentar passar 'executor' ou 'leitor'
        return {"erro": f"argumentos não permitidos: {nao_permitidos}. Permitidos: {sorted(permitidos)}"}

    try:
        return tools[nome](**argumentos)
    except TypeError as erro:
        return {"erro": f"argumentos incorretos: {erro}"}
    except ValueError as erro:
        return {"erro": str(erro)}
    except Exception as erro:  # noqa: BLE001 - falha de infraestrutura: informamos sem derrubar o laço
        return {"erro": f"falha ao executar a tool ({type(erro).__name__}): {str(erro)[:300]}"}


def _espera_sugerida(erro: Exception, tentativa: int):
    """Quantos segundos esperar após um 429. None = não vale a pena esperar (limite diário)."""
    cabecalhos = getattr(getattr(erro, "response", None), "headers", None) or {}
    bruto = cabecalhos.get("retry-after")
    try:
        espera = float(bruto) if bruto is not None else None
    except (TypeError, ValueError):
        espera = None
    if espera is None:
        espera = min(15 * (2 ** tentativa), 60)      # sem dica do servidor: espera crescente
    return espera + 1 if espera <= ESPERA_MAXIMA_EM_429 else None


def _chamar_modelo(cliente: Any, argumentos: Dict[str, Any], dormir: Callable[[float], None], max_tentativas: int):
    """Chama o modelo; em caso de 429 (limite por minuto) espera o tempo sugerido e tenta de novo."""
    for tentativa in range(max_tentativas):
        try:
            return cliente.chat.completions.create(**argumentos)
        except Exception as erro:  # noqa: BLE001
            if getattr(erro, "status_code", None) != 429:
                raise
            espera = _espera_sugerida(erro, tentativa)
            if espera is None or tentativa == max_tentativas - 1:
                raise LimiteDeUsoAtingido(
                    "Limite de uso do provedor atingido (HTTP 429). Se for o limite por MINUTO, aguarde 1 minuto; "
                    "se for o DIÁRIO, tente mais tarde ou troque de modelo. "
                    f"Detalhe do provedor: {str(erro)[:300]}"
                ) from erro
            dormir(espera)


def executar_agente(pergunta: str, cliente: Any, modelo: str, tools: Sequence[Callable],
                    *, prompt: str = PROMPT_DO_SISTEMA, max_passos: int = 8,
                    temperatura: float = 0.0, dormir: Callable[[float], None] = time.sleep,
                    max_tentativas_429: int = 4) -> ResultadoDoAgente:
    por_nome = {t.__name__: t for t in tools}
    esquemas = {t.__name__: esquema_da_tool(t) for t in tools}
    lista_de_esquemas = list(esquemas.values())

    mensagens: List[Dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": pergunta},
    ]
    passos: List[Dict[str, Any]] = []
    chamadas = tokens_in = tokens_out = 0
    t_modelo = t_tools = t_espera = 0.0

    def dormir_medindo(segundos: float) -> None:
        nonlocal t_espera
        inicio = time.monotonic()
        dormir(segundos)
        t_espera += time.monotonic() - inicio

    def resultado_final(resposta: str, parou: bool = False) -> ResultadoDoAgente:
        return ResultadoDoAgente(
            resposta=resposta, passos=passos, parou_por_limite=parou, chamadas_ao_modelo=chamadas,
            tokens_entrada=tokens_in, tokens_saida=tokens_out,
            segundos_no_modelo=round(max(0.0, t_modelo - t_espera), 2),
            segundos_nas_tools=round(t_tools, 2), segundos_em_espera=round(t_espera, 2),
        )

    for _ in range(max_passos):
        inicio = time.monotonic()
        resposta = _chamar_modelo(
            cliente, dict(model=modelo, messages=mensagens, tools=lista_de_esquemas, temperature=temperatura),
            dormir_medindo, max_tentativas_429,
        )
        t_modelo += time.monotonic() - inicio
        chamadas += 1
        uso = getattr(resposta, "usage", None)
        tokens_in += int(getattr(uso, "prompt_tokens", 0) or 0)
        tokens_out += int(getattr(uso, "completion_tokens", 0) or 0)
        mensagem = resposta.choices[0].message
        pedidas = getattr(mensagem, "tool_calls", None)

        if not pedidas:
            return resultado_final((mensagem.content or "").strip())

        mensagens.append({
            "role": "assistant",
            "content": mensagem.content,
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in pedidas
            ],
        })
        for chamada in pedidas:
            inicio = time.monotonic()
            resultado = _executar_tool(chamada.function.name, chamada.function.arguments, por_nome, esquemas)
            duracao = time.monotonic() - inicio
            t_tools += duracao
            passos.append({"tool": chamada.function.name, "argumentos": chamada.function.arguments,
                           "erro": isinstance(resultado, dict) and "erro" in resultado,
                           "segundos": round(duracao, 2)})
            mensagens.append({"role": "tool", "tool_call_id": chamada.id, "content": _para_texto(resultado)})

    return resultado_final(
        "Não consegui concluir dentro do limite de passos. Reformule a pergunta ou tente de novo.", parou=True)
