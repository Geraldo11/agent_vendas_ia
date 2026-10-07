"""Testa o MODELO sozinho, em 3 etapas, para separar problemas do modelo/provedor dos do nosso agente.

Uso (na raiz do projeto, com LLM_PROVIDER e LLM_MODEL no .env):
    python scripts/testar_llm.py
"""
import sys
import time

sys.path.insert(0, ".")

from agentes.ambiente import carregar_env  # noqa: E402

carregar_env()  # lê o .env da raiz do projeto (no container o Docker já fez isso)

from agentes.agente import LimiteDeUsoAtingido, executar_agente  # noqa: E402
from agentes.esquemas import esquema_da_tool  # noqa: E402
from agentes.llm import configuracao_do_llm, criar_cliente, explicar_erro_do_provedor  # noqa: E402


def somar(a: int, b: int) -> dict:
    """Soma dois números inteiros e devolve o resultado."""
    return {"soma": a + b}


def executar(config, cliente):
    print("\n[1/3] Conversa simples")
    t = time.time()
    r = cliente.chat.completions.create(
        model=config.modelo, temperature=0,
        messages=[{"role": "user", "content": "Responda apenas com a palavra: pronto"}],
    )
    print(f"   resposta: {(r.choices[0].message.content or '').strip()[:80]!r}  ({time.time() - t:.1f}s)")

    print("\n[2/3] O modelo consegue PEDIR uma tool?")
    t = time.time()
    r = cliente.chat.completions.create(
        model=config.modelo, temperature=0, tools=[esquema_da_tool(somar)],
        messages=[{"role": "user", "content": "Use a ferramenta somar para calcular 17 + 25."}],
    )
    msg = r.choices[0].message
    if msg.tool_calls:
        c = msg.tool_calls[0]
        print(f"   SIM: pediu {c.function.name}({c.function.arguments})  ({time.time() - t:.1f}s)")
    else:
        print(f"   NÃO: respondeu com texto em vez de chamar a tool: {(msg.content or '')[:120]!r}")
        print("   -> este modelo/provedor provavelmente não suporta function calling.")

    print("\n[3/3] Ciclo completo com o nosso agente (pedir tool, receber o resultado, responder)")
    t = time.time()
    res = executar_agente("Quanto é 17 + 25? Use a ferramenta somar.", cliente, config.modelo, [somar],
                          max_passos=4, temperatura=config.temperatura)
    print(f"   tools chamadas: {[p['tool'] for p in res.passos]}")
    print(f"   resposta: {res.resposta[:200]!r}  ({time.time() - t:.1f}s)")
    print("   contém 42:", "42" in res.resposta)
    print(f"   uso: {res.chamadas_ao_modelo} chamada(s), {res.tokens_entrada} tokens de entrada + {res.tokens_saida} de saída")


config = configuracao_do_llm()
cliente = criar_cliente(config)
print(f"Provedor: {config.provedor} | modelo: {config.modelo} | endereço: {config.base_url}")

try:
    executar(config, cliente)
except LimiteDeUsoAtingido as erro:
    print(f"\nLIMITE DE USO: {erro}")
    sys.exit(2)
except Exception as erro:  # noqa: BLE001
    explicacao = explicar_erro_do_provedor(erro, config, cliente)
    if explicacao is None:
        raise
    print(f"\nERRO DO PROVEDOR:\n{explicacao}")
    sys.exit(2)
