"""Acha no banco um exemplo real de cada caso de avaliação e grava avaliacao/casos.json.

Mostra também o comando pronto para perguntar ao agente. Roda ~13 consultas pequenas.

Uso (na raiz do projeto):
    python scripts/gerar_casos.py
    python scripts/gerar_casos.py --por-caso 2
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, ".")

from agentes.ambiente import carregar_env  # noqa: E402

carregar_env()

from agentes.casos import salvar_casos, selecionar_casos  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--por-caso", type=int, default=1)
args = parser.parse_args()

casos = selecionar_casos(por_caso=args.por_caso)
destino = Path("avaliacao/casos.json")
salvar_casos(casos, destino)

print(f"{len(casos)} caso(s) gravado(s) em {destino}\n")
for c in casos:
    rotulo = c["divergencia"] or "controle"
    ident = c["id_venda"] or "(sem venda)"
    print(f"[{rotulo:8s}] {c['nome']:26s} {ident}")
    if c.get("aviso"):
        print(f"            AVISO: {c['aviso']}")
    else:
        print(f'            python scripts/perguntar.py "{c["pergunta"]}"')
