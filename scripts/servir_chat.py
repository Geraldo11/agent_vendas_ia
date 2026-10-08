"""Sobe a interface de chat em http://127.0.0.1:8000 (uma pergunta por vez, sem autenticação).

Uso (na raiz do projeto):
    python scripts/servir_chat.py                      # agente real (Groq + Databricks, lê o .env)
    python scripts/servir_chat.py --agente-falso       # demonstração: sem chaves, sem tokens, sem Databricks
    python scripts/servir_chat.py --porta 8080 --timeout 60

No container (docker compose), o servidor precisa escutar em 0.0.0.0: use --host 0.0.0.0 --aceitar-rede
e publique a porta SÓ em 127.0.0.1 (ver docker-compose.yml). Detalhes em chat/README.md.
"""
import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from agentes.ambiente import carregar_env  # noqa: E402

HOSTS_LOCAIS = {"127.0.0.1", "localhost"}


def ler_argumentos(argv=None):
    p = argparse.ArgumentParser(description="Interface de chat do agente de vendas")
    p.add_argument("--host", default="127.0.0.1", help="endereço de escuta (padrão: 127.0.0.1)")
    p.add_argument("--porta", type=int, default=8000, help="porta (padrão: 8000)")
    p.add_argument("--aceitar-rede", action="store_true",
                   help="permite --host diferente de 127.0.0.1/localhost (só para o container)")
    p.add_argument("--agente-falso", action="store_true", help="modo demonstração: agente simulado, sem chaves")
    p.add_argument("--timeout", type=float, default=180.0, help="tempo máximo por pergunta, em segundos (padrão: 180)")
    p.add_argument("--passos", type=int, default=8, help="máximo de passos do agente (padrão: 8)")
    return p.parse_args(argv)


def montar(args):
    """Devolve (executor, config, modo). Falha com SystemExit e mensagem clara se o .env estiver errado."""
    if args.agente_falso:
        from chat.demo import CONFIG_DEMO, executar_demo
        return executar_demo, CONFIG_DEMO, "demonstracao"

    from agentes.llm import configuracao_do_llm, criar_cliente
    from agentes.tools import TOOLS
    from agentes.tools.config import ENV_WAREHOUSE
    from agentes.tools.db import ENV_OBRIGATORIAS, validar_ambiente
    from chat.app import criar_executor_real

    try:
        validar_ambiente(tuple(ENV_OBRIGATORIAS) + (ENV_WAREHOUSE,))
        config = configuracao_do_llm()
    except RuntimeError as erro:
        sys.exit(f"Não subi o servidor: a configuração tem problemas.\n{erro}\n\n"
                 "Para conferir o .env sem mostrar valores:  python scripts/verificar_env.py\n"
                 "Para ver a interface sem chaves:           python scripts/servir_chat.py --agente-falso")
    cliente = criar_cliente(config)
    return criar_executor_real(config, cliente, TOOLS, max_passos=args.passos), config, "real"


def main(argv=None):
    args = ler_argumentos(argv)
    if args.host not in HOSTS_LOCAIS and not args.aceitar_rede:
        sys.exit(f"--host {args.host} exporia o chat (e os seus tokens) a outras máquinas, e ele não tem "
                 "autenticação. Use 127.0.0.1. No container, use --host 0.0.0.0 --aceitar-rede e publique a "
                 "porta só em 127.0.0.1.")
    if not args.agente_falso:
        carregar_env()                  # no modo demonstração o .env nem é lido

    executor, config, modo = montar(args)

    import uvicorn
    from chat.app import criar_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = criar_app(executor, config, modo=modo, porta=args.porta, timeout_segundos=args.timeout)
    print(f"\nChat em http://127.0.0.1:{args.porta}  ({'DEMONSTRAÇÃO' if modo == 'demonstracao' else config.provedor}"
          f" | {config.modelo})   Ctrl+C para parar.\n", flush=True)
    uvicorn.run(app, host=args.host, port=args.porta, log_level="info", server_header=False)


if __name__ == "__main__":
    main()
