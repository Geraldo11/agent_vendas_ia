"""Lista os modelos que a SUA chave pode usar no provedor configurado (Groq, Databricks, Ollama...).

Modelos são descontinuados e criados com frequência; este script consulta o provedor na hora.

Uso (na raiz do projeto):  python scripts/listar_modelos.py
"""
import sys

sys.path.insert(0, ".")

from agentes.ambiente import carregar_env  # noqa: E402

carregar_env()

from agentes.llm import configuracao_do_llm, criar_cliente, listar_modelos, modelos_de_chat  # noqa: E402

config = configuracao_do_llm()
cliente = criar_cliente(config)
print(f"Provedor: {config.provedor} | endereço: {config.base_url}")

try:
    todos = listar_modelos(cliente)
except Exception as erro:  # noqa: BLE001
    print(f"Não consegui listar os modelos: {type(erro).__name__}: {str(erro)[:300]}")
    sys.exit(2)

chat = modelos_de_chat(todos)
print(f"\nModelos de chat ({len(chat)}):")
for modelo in chat:
    marca = "   <- é o seu LLM_MODEL atual" if modelo == config.modelo else ""
    print(f"  - {modelo}{marca}")

outros = [m for m in todos if m not in chat]
if outros:
    print(f"\nOutros (voz, moderação, embeddings; não servem para o agente): {len(outros)}")

if config.modelo in todos:
    print(f"\nO seu LLM_MODEL ({config.modelo}) está DISPONÍVEL.")
else:
    print(f"\nATENÇÃO: o seu LLM_MODEL ({config.modelo}) NÃO está na lista. Troque no .env por um modelo de chat acima.")
    sys.exit(1)
