"""Front-end do chat: varredura estática de segurança e entrega dos arquivos.

Não há Node nesta máquina para executar o JavaScript; então conferimos o TEXTO dos arquivos.
Isso pega as portas de entrada clássicas de XSS e o que a CSP bloquearia (estilo e script inline).
A renderização em si é conferida pelo checklist manual em chat/README.md.
"""
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agentes.llm import ConfigLLM  # noqa: E402
from agentes.tools import TOOLS  # noqa: E402
from chat.app import MAX_CARACTERES_DA_PERGUNTA, criar_app  # noqa: E402
from chat.seguranca import CSP  # noqa: E402

ESTATICOS = Path(__file__).resolve().parent.parent / "chat" / "static"
HTML = (ESTATICOS / "index.html").read_text(encoding="utf-8")
JS = (ESTATICOS / "app.js").read_text(encoding="utf-8")
CSS = (ESTATICOS / "estilo.css").read_text(encoding="utf-8")


# ------------------------------------------------------------------ JavaScript: nada vira HTML
@pytest.mark.parametrize("proibido", [
    r"\binnerHTML\b", r"\bouterHTML\b", r"\binsertAdjacentHTML\b", r"document\.write", r"\beval\s*\(",
    r"\bnew\s+Function\b", r"setAttribute\(\s*['\"]style['\"]", r"setAttribute\(\s*['\"]on",
    r"createContextualFragment", r"DOMParser", r"srcdoc", r"javascript:", r"\.href\s*=",
])
def test_javascript_nao_usa_apis_perigosas(proibido):
    assert not re.search(proibido, JS), f"app.js contém {proibido!r}"


# ------------------------------------------------------------------ HTML: nada inline (a CSP bloquearia)
TAGS = re.findall(r"<[a-zA-Z][^>]*>", HTML)


def test_html_sem_atributo_style():
    assert not [t for t in TAGS if re.search(r"\sstyle\s*=", t, re.I)]


def test_html_sem_atributos_de_evento():
    assert not [t for t in TAGS if re.search(r"\son[a-z]+\s*=", t, re.I)]


def test_html_sem_script_inline():
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", HTML, re.I | re.S)
    assert scripts, "o HTML deveria carregar o app.js"
    for atributos, conteudo in scripts:
        assert re.search(r"\ssrc\s*=", atributos), "script sem src (inline)"
        assert not conteudo.strip(), "script com conteúdo inline"


def test_html_sem_bloco_style_inline():
    assert not re.search(r"<style\b", HTML, re.I)


@pytest.mark.parametrize("nome, texto", [("index.html", HTML), ("app.js", JS), ("estilo.css", CSS)])
def test_nada_vem_de_fora(nome, texto):
    # Sem CDN e sem fontes externas: endereços absolutos ou "//host" são proibidos (data: é permitido).
    assert not re.search(r"(?:src|href)\s*=\s*['\"](?:https?:)?//", texto, re.I), nome
    assert not re.search(r"@import|url\(\s*['\"]?(?:https?:)?//", texto, re.I), nome
    assert not re.search(r"fetch\(\s*['\"](?:https?:)?//", texto, re.I), nome


def test_html_carrega_os_arquivos_do_proprio_servidor():
    assert 'src="/static/app.js"' in HTML and 'href="/static/estilo.css"' in HTML


# ------------------------------------------------------------------ requisitos da interface
def test_html_acessivel_e_em_portugues():
    assert '<html lang="pt-BR">' in HTML
    assert re.search(r'id="conversa"[^>]*aria-live="polite"', HTML)
    assert 'name="viewport"' in HTML
    assert f'maxlength="{MAX_CARACTERES_DA_PERGUNTA}"' in HTML
    assert "Cada pergunta é independente: o assistente não lembra das anteriores." in HTML
    assert 'id="faixa-demo"' in HTML and "MODO DEMONSTRAÇÃO" in HTML


def test_limite_de_caracteres_igual_no_servidor_e_no_navegador():
    assert f"LIMITE_DE_CARACTERES = {MAX_CARACTERES_DA_PERGUNTA};" in JS


def test_todas_as_tools_tem_rotulo_amigavel():
    for tool in TOOLS:
        assert re.search(rf"\b{tool.__name__}:\s*\(a\)", JS), f"sem rótulo para {tool.__name__}"


def test_javascript_trata_todos_os_eventos_do_servidor():
    for evento in ("modelo_inicio", "tool_inicio", "tool_fim", "espera", "fim", "erro", "cancelado"):
        assert f'case "{evento}"' in JS


def test_fluxo_sem_terminal_vira_mensagem_de_conexao_encerrada():
    assert "if (!terminou)" in JS and "conexao" in JS


def test_tema_escuro_e_foco_visivel():
    assert "prefers-color-scheme: dark" in CSS and ":focus-visible" in CSS


# ------------------------------------------------------------------ entrega pelo servidor
@pytest.fixture
def cliente():
    config = ConfigLLM("groq", "https://api.groq.com/openai/v1", "gsk_x_teste_123", "openai/gpt-oss-120b")
    app = criar_app(lambda *a, **k: None, config, env={}, timeout_segundos=5)
    return TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.mark.parametrize("caminho, tipo", [
    ("/", "text/html"),
    ("/static/app.js", "javascript"),
    ("/static/estilo.css", "text/css"),
])
def test_arquivos_servidos_com_tipo_e_cabecalhos_de_seguranca(cliente, caminho, tipo):
    r = cliente.get(caminho)
    assert r.status_code == 200 and tipo in r.headers["content-type"]
    assert r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff"


def test_arquivo_fora_da_pasta_static_nao_e_servido(cliente):
    for caminho in ("/static/../app.py", "/static/%2e%2e/app.py", "/static/..%2fapp.py"):
        assert cliente.get(caminho).status_code == 404
