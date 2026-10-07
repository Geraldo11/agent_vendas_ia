"""Confere se a SUA cópia do repositório tem os arquivos certos, nas versões certas.

Pega problemas que já nos custaram tempo: arquivos que faltam, nomes com '(1)' ou espaço,
testes que viraram scripts e arquivos desatualizados. NÃO lê o .env.

Uso (na raiz do projeto):  python scripts/verificar_repositorio.py
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

ESPERADOS = [
    "CLAUDE.md", ".claude/settings.json", "docs/CONTEXTO_DO_PROJETO.md", "docs/manual_elegibilidade_v2.3.pdf",
    "requirements.txt", "pytest.ini", ".env.example", ".gitignore", "Dockerfile", "docker-compose.yml",
    "agentes/__init__.py", "agentes/ambiente.py", "agentes/casos.py", "agentes/agente.py", "agentes/esquemas.py", "agentes/llm.py",
    "agentes/tools/__init__.py", "agentes/tools/config.py", "agentes/tools/db.py", "agentes/tools/dados.py",
    "agentes/tools/regras_codigo.py", "agentes/tools/manual.py",
    "regras/__init__.py", "regras/base.py", "regras/comum.py", "regras/consorcio.py",
    "regras/capitalizacao.py", "regras/registro.py",
    "ingestao/__init__.py", "ingestao/manual_chunks.py",
    "notebooks/01_setup_e_bronze.py", "notebooks/02_silver.py", "notebooks/03_gold.py",
    "notebooks/04_gabarito_divergencias.py", "notebooks/05_manual_chunks.py",
    "scripts/gerar_manual.py", "scripts/tools_ao_vivo.py", "scripts/testar_llm.py", "scripts/perguntar.py",
    "scripts/diagnosticar_token.py", "scripts/verificar_env.py", "scripts/listar_modelos.py", "scripts/gerar_casos.py", "scripts/verificar_repositorio.py",
    "tests/test_regras.py", "tests/test_manual_chunks.py", "tests/test_tools.py",
    "tests/test_db_ambiente.py", "tests/test_agente.py", "tests/test_env.py", "tests/test_provedor.py", "tests/test_casos.py",
    "terraform/main.tf", "terraform/variables.tf", "terraform/versions.tf", "terraform/outputs.tf",
]

# Trechos que só existem na versão ATUAL de cada arquivo (detectam cópia antiga)
MARCADORES = {
    "agentes/tools/db.py": ["def extrair_warehouse_id", "def problema_no_host", "def validar_ambiente"],
    "agentes/agente.py": ["class LimiteDeUsoAtingido", "def _chamar_modelo", "segundos_nas_tools"],
    "agentes/llm.py": ['"groq"', "verificar_env.py", "def explicar_erro_do_provedor", "def listar_modelos"],
    "agentes/ambiente.py": ["def carregar_env", "def analisar_env", "def diagnosticar"],
    "scripts/perguntar.py": ["carregar_env"],
    "scripts/testar_llm.py": ["carregar_env"],
    "tests/test_db_ambiente.py": ["def test_extrair_warehouse_id", "test_executar_sql_envia_so_o_id_do_warehouse"],
    "tests/test_tools.py": ["def test_get_venda_monta_o_resultado"],
    "tests/test_agente.py": ["test_429_espera_o_tempo_pedido_pelo_servidor_e_tenta_de_novo"],
}

IGNORAR = {".git", ".terraform", "__pycache__", ".pytest_cache", ".venv", "node_modules"}


def ler(caminho: str) -> str:
    return (RAIZ / caminho).read_text(encoding="utf-8", errors="replace")


problemas = []

# 1) arquivos que faltam
for caminho in ESPERADOS:
    if not (RAIZ / caminho).exists():
        problemas.append(f"FALTA            {caminho}")

# 2) nomes suspeitos: '(1)' ou espaço antes da extensão (o Python ignora esses arquivos)
for p in RAIZ.rglob("*"):
    if any(parte in IGNORAR for parte in p.relative_to(RAIZ).parts) or not p.is_file():
        continue
    if re.search(r" \(\d+\)", p.name) or re.search(r" \.\w+$", p.name):
        problemas.append(f"NOME SUSPEITO   {p.relative_to(RAIZ)}   (renomeie: sem '(1)' nem espaço)")

# 3) arquivos de teste que não têm nenhum teste (ex.: um script manual salvo no lugar do teste)
for p in sorted((RAIZ / "tests").glob("test_*.py")):
    if not re.search(r"^def test_", p.read_text(encoding="utf-8", errors="replace"), re.M):
        problemas.append(f"SEM TESTES       tests/{p.name}   (não tem nenhuma função test_; parece um script)")

# 4) versão desatualizada
for caminho, marcas in MARCADORES.items():
    if (RAIZ / caminho).exists():
        texto = ler(caminho)
        faltam = [m for m in marcas if m not in texto]
        if faltam:
            problemas.append(f"DESATUALIZADO   {caminho}   (falta: {', '.join(faltam)})")

# 5) o .env está no .gitignore? (o conteúdo do .env NÃO é lido)
if (RAIZ / ".gitignore").exists():
    linhas = {l.strip() for l in ler(".gitignore").splitlines()}
    if ".env" not in linhas:
        problemas.append("SEGURANÇA       .gitignore não lista '.env' (o token pode ir para o GitHub)")

if problemas:
    print(f"{len(problemas)} problema(s) encontrado(s):\n")
    for linha in problemas:
        print("  -", linha)
    print("\nCorrija e rode de novo. Depois rode:  pytest")
    sys.exit(1)

print("Repositório conferido: arquivos presentes, nomes corretos, testes com testes e versões atuais.")
print("Agora rode:  pytest   (esperado: 223 passed, ou 221 passed + 2 skipped sem o databricks-sdk)")
