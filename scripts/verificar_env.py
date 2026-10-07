"""Diagnostica o arquivo .env SEM mostrar nenhum valor secreto (só nomes e situações).

Uso (na raiz do projeto, no PowerShell ou no container):
    python scripts/verificar_env.py
"""
import sys

sys.path.insert(0, ".")

from agentes.ambiente import RAIZ, analisar_env, diagnosticar, ler_env, valores_do_env  # noqa: E402
from agentes.llm import configuracao_do_llm  # noqa: E402
from agentes.tools.config import ENV_WAREHOUSE  # noqa: E402
from agentes.tools.db import ENV_OBRIGATORIAS, validar_ambiente  # noqa: E402

ESPERADAS = ["DATABRICKS_HOST", "DATABRICKS_TOKEN", ENV_WAREHOUSE, "LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY"]

caminho = RAIZ / ".env"
print(f"Arquivo: {caminho}")
if not caminho.exists():
    print("NÃO ENCONTREI o .env nesta pasta. Copie o modelo:  copy .env.example .env  e preencha.")
    sys.exit(1)

texto, avisos = ler_env(caminho)
linhas = analisar_env(texto)
valores = valores_do_env(linhas)
no_arquivo = {l.nome for l in linhas}

print("\nVariáveis (só o nome e a situação; os valores NÃO são mostrados):")
for nome in ESPERADAS:
    situacao = "preenchida" if nome in valores else ("VAZIA ou com problema" if nome in no_arquivo else "AUSENTE")
    print(f"  {nome:26s} {situacao}")
outras = sorted(no_arquivo - set(ESPERADAS))
if outras:
    print("  outras no arquivo:", ", ".join(outras))

problemas = diagnosticar(texto, avisos)
erros = []
try:
    validar_ambiente(ENV_OBRIGATORIAS + (ENV_WAREHOUSE,), env=valores)
except RuntimeError as erro:
    erros.append(str(erro))
try:
    cfg = configuracao_do_llm(valores)
    print(f"\nModelo configurado: provedor={cfg.provedor} | modelo={cfg.modelo}")
except RuntimeError as erro:
    erros.append(str(erro))

if problemas:
    print("\nProblemas de formato:")
    for p in problemas:
        print("  -", p)
if erros:
    print("\nProblemas de configuração:")
    for e in erros:
        print("  -", e.replace("\n", "\n    "))

if problemas or erros:
    print("\nCorrija o .env (formato NOME=valor, uma por linha, sem espaço no início e sem aspas) e rode de novo.")
    sys.exit(1)
print("\n.env conferido: formato correto e configuração completa.")
