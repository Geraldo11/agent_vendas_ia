"""Faz uma pergunta ao agente e mostra cada tool chamada e a resposta final.

Uso (na raiz do projeto, dentro do container):
    python scripts/perguntar.py "Por que a venda VD000084 não entrou na carteira?"
    python scripts/perguntar.py "..." --passos 10
"""
import argparse
import json
import sys
import time

sys.path.insert(0, ".")

from agentes.ambiente import carregar_env  # noqa: E402

carregar_env()  # lê o .env da raiz do projeto (no container o Docker já fez isso)

from agentes.agente import LimiteDeUsoAtingido, executar_agente  # noqa: E402
from agentes.llm import configuracao_do_llm, criar_cliente, explicar_erro_do_provedor  # noqa: E402
from agentes.tools import TOOLS  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("pergunta")
parser.add_argument("--passos", type=int, default=8)
args = parser.parse_args()

config = configuracao_do_llm()
cliente = criar_cliente(config)
print(f"[{config.provedor} | {config.modelo}]\nPergunta: {args.pergunta}\n")

inicio = time.time()
try:
    resultado = executar_agente(args.pergunta, cliente, config.modelo, TOOLS,
                                max_passos=args.passos, temperatura=config.temperatura)
except LimiteDeUsoAtingido as erro:
    print(f"\nLIMITE DE USO: {erro}")
    sys.exit(2)
except Exception as erro:  # noqa: BLE001
    explicacao = explicar_erro_do_provedor(erro, config, cliente)
    if explicacao is None:
        raise
    print(f"\nERRO DO PROVEDOR:\n{explicacao}")
    sys.exit(2)

for i, passo in enumerate(resultado.passos, start=1):
    marca = "  <- ERRO" if passo["erro"] else ""
    print(f"  {i}. {passo['tool']}({passo['argumentos']})  [{passo.get('segundos', 0):.1f}s]{marca}")

print(f"\nRESPOSTA:\n{resultado.resposta}")
print(f"\n({len(resultado.passos)} tool(s), {time.time() - inicio:.1f}s"
      f"{', PAROU NO LIMITE DE PASSOS' if resultado.parou_por_limite else ''})")
print(f"Tempo: modelo {resultado.segundos_no_modelo:.1f}s | tools {resultado.segundos_nas_tools:.1f}s | "
      f"esperas por limite de uso {resultado.segundos_em_espera:.1f}s")
print(f"Uso: {resultado.chamadas_ao_modelo} chamada(s) ao modelo | "
      f"{resultado.tokens_entrada} tokens de entrada + {resultado.tokens_saida} de saída "
      f"= {resultado.tokens_entrada + resultado.tokens_saida} no total")
