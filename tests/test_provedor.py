"""Erros e modelos do provedor: o 404 'model_not_found' que o Groq devolve quando um modelo é descontinuado."""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentes.llm import (ConfigLLM, explicar_erro_do_provedor, listar_modelos, modelos_de_chat)

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = ConfigLLM("groq", "http://x/v1", "gsk_x", "llama-3.3-70b-versatile")
MODELOS = ["whisper-large-v3", "qwen/qwen3.6-27b", "openai/gpt-oss-safeguard-20b", "openai/gpt-oss-120b", "orpheus-v1-english"]


def cliente_falso(ids=MODELOS, falha=False):
    def listar():
        if falha:
            raise RuntimeError("sem rede")
        return [SimpleNamespace(id=i) for i in ids]
    return SimpleNamespace(models=SimpleNamespace(list=listar))


def erro(status=None, code=None, msg="erro"):
    e = Exception(msg)
    e.status_code, e.code = status, code
    return e


# ------------------------------------------------------------------ listar e filtrar
def test_listar_modelos_devolve_ids_ordenados():
    assert listar_modelos(cliente_falso(["b", "a"])) == ["a", "b"]


def test_modelos_de_chat_tira_voz_moderacao_e_embeddings():
    assert modelos_de_chat(sorted(MODELOS)) == ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"]


# ------------------------------------------------------------------ tradução dos erros
def test_404_cita_o_modelo_e_lista_os_disponiveis():
    texto = explicar_erro_do_provedor(erro(404, "model_not_found"), CONFIG, cliente_falso())
    assert "llama-3.3-70b-versatile" in texto and "descontinuados" in texto
    assert "- openai/gpt-oss-120b" in texto and "- qwen/qwen3.6-27b" in texto
    assert "whisper" not in texto and "orpheus" not in texto            # só modelos de chat


def test_model_not_found_sem_status_tambem_e_reconhecido():
    assert explicar_erro_do_provedor(erro(None, "model_not_found"), CONFIG, cliente_falso())


def test_404_sem_conseguir_listar_aponta_o_script():
    texto = explicar_erro_do_provedor(erro(404), CONFIG, cliente_falso(falha=True))
    assert "scripts/listar_modelos.py" in texto


def test_404_sem_cliente_nao_quebra():
    assert "HTTP 404" in explicar_erro_do_provedor(erro(404), CONFIG)


@pytest.mark.parametrize("status, trecho", [(401, "Chave recusada"), (403, "Acesso negado"), (400, "HTTP 400")])
def test_outros_status(status, trecho):
    assert trecho in explicar_erro_do_provedor(erro(status, msg="detalhe"), CONFIG)


def test_erro_desconhecido_devolve_none():
    assert explicar_erro_do_provedor(erro(500), CONFIG) is None
    assert explicar_erro_do_provedor(ValueError("x"), CONFIG) is None


# ------------------------------------------------------------------ servidor local que imita o Groq
@pytest.fixture
def groq_falso():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, codigo, corpo):
            dados = json.dumps(corpo).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            if self.path.endswith("/models"):
                self._json(200, {"object": "list", "data": [
                    {"id": i, "object": "model", "created": 0, "owned_by": "x"} for i in MODELOS]})
            else:
                self._json(404, {"error": {"message": "rota inexistente"}})

        def do_POST(self):
            corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if corpo["model"] != "openai/gpt-oss-120b":      # igual ao Groq com modelo descontinuado
                return self._json(404, {"error": {
                    "message": f"The model `{corpo['model']}` does not exist or you do not have access to it.",
                    "type": "invalid_request_error", "code": "model_not_found"}})
            ultima = corpo["messages"][-1]
            if ultima["role"] == "tool":
                msg, fim = {"role": "assistant", "content": f"O resultado é {json.loads(ultima['content'])['soma']}.",
                            "tool_calls": None}, "stop"
            elif corpo.get("tools") and "somar" in ultima["content"]:
                msg, fim = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "somar", "arguments": json.dumps({"a": 17, "b": 25})}}]}, "tool_calls"
            else:
                msg, fim = {"role": "assistant", "content": "pronto", "tool_calls": None}, "stop"
            self._json(200, {"id": "x", "object": "chat.completion", "created": 0, "model": corpo["model"],
                             "choices": [{"index": 0, "message": msg, "finish_reason": fim}],
                             "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    servidor = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}/v1"
    servidor.shutdown()


def test_cliente_real_expoe_status_e_codigo_do_404(groq_falso):
    pytest.importorskip("openai")
    from agentes.llm import criar_cliente
    config = ConfigLLM("groq", groq_falso, "gsk_x", "llama-3.3-70b-versatile")
    cliente = criar_cliente(config)
    with pytest.raises(Exception) as capturado:
        cliente.chat.completions.create(model=config.modelo, messages=[{"role": "user", "content": "oi"}])
    assert capturado.value.status_code == 404 and capturado.value.code == "model_not_found"
    texto = explicar_erro_do_provedor(capturado.value, config, cliente)
    assert "- openai/gpt-oss-120b" in texto


def rodar_script(nome, groq_falso, modelo, extra_args=()):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "GROQ_"))}
    env.update(LLM_PROVIDER="groq", LLM_MODEL=modelo, GROQ_API_KEY="gsk_teste", LLM_BASE_URL=groq_falso)
    return subprocess.run([sys.executable, f"scripts/{nome}", *extra_args], cwd=RAIZ, env=env,
                          capture_output=True, text=True, timeout=60)


def test_testar_llm_com_modelo_descontinuado_explica_em_vez_de_traceback(groq_falso):
    pytest.importorskip("openai")
    r = rodar_script("testar_llm.py", groq_falso, "llama-3.3-70b-versatile")
    assert r.returncode == 2 and "Traceback" not in r.stderr
    assert "ERRO DO PROVEDOR" in r.stdout and "- openai/gpt-oss-120b" in r.stdout


def test_testar_llm_com_modelo_valido_fecha_o_ciclo(groq_falso):
    pytest.importorskip("openai")
    r = rodar_script("testar_llm.py", groq_falso, "openai/gpt-oss-120b")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SIM: pediu somar" in r.stdout and "contém 42: True" in r.stdout


def test_perguntar_com_modelo_descontinuado_explica(groq_falso):
    pytest.importorskip("openai")
    r = rodar_script("perguntar.py", groq_falso, "llama-3.3-70b-versatile", ("Por que a venda VD1 não entrou?",))
    assert r.returncode == 2 and "ERRO DO PROVEDOR" in r.stdout


def test_listar_modelos_marca_o_modelo_atual_e_avisa_se_nao_existe(groq_falso):
    pytest.importorskip("openai")
    bom = rodar_script("listar_modelos.py", groq_falso, "openai/gpt-oss-120b")
    assert bom.returncode == 0 and "<- é o seu LLM_MODEL atual" in bom.stdout and "DISPONÍVEL" in bom.stdout
    ruim = rodar_script("listar_modelos.py", groq_falso, "llama-3.3-70b-versatile")
    assert ruim.returncode == 1 and "NÃO está na lista" in ruim.stdout
