"""Servidor do chat: recebe a pergunta, roda o agente numa thread e devolve os eventos em fluxo (NDJSON).

Por que uma thread: o agente é síncrono e bloqueante (espera o modelo, o warehouse e, no 429, dorme).
Se rodasse direto no servidor, travaria tudo. Então:

    navegador --POST /api/perguntar--> servidor --thread--> agente
              <--- uma linha JSON por evento ---   fila   <-- ao_evento(...)

Formato NDJSON: cada linha é um JSON completo, terminado em "\\n". Como o navegador lê com fetch (e não
com EventSource), o formato SSE não traria vantagem; NDJSON é mais simples de ler dos dois lados.

Garantias do fluxo:
  - termina com EXATAMENTE UM evento terminal: 'fim', 'erro' ou 'cancelado';
  - uma pergunta por vez (trava): a segunda recebe 409;
  - a trava só é liberada quando a thread do agente TERMINA (não quando o navegador desconecta),
    para nunca haver duas perguntas gastando tokens ao mesmo tempo;
  - timeout total (180 s): o fluxo termina com erro 'tempo_esgotado' e o agente recebe pedido de parada.

Limitação conhecida: o pedido de parada (botão Parar, desconexão ou timeout) só é atendido ENTRE etapas.
Uma chamada ao modelo ou uma consulta ao warehouse já em andamento vai até o fim; a espera por limite
de uso (429), essa sim, é interrompida na hora.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agentes.agente import PerguntaCancelada, ResultadoDoAgente, evento_fim, executar_agente
from agentes.llm import ConfigLLM

from .erros import classificar_erro, evento_de_erro, registrar_erro
from .seguranca import Seguranca, resposta_de_erro

ESTATICOS = Path(__file__).resolve().parent / "static"
MAX_CARACTERES_DA_PERGUNTA = 1000
TIMEOUT_PADRAO_EM_SEGUNDOS = 180.0
EVENTOS_TERMINAIS = {"fim", "erro", "cancelado"}
MENSAGEM_CANCELADA = "Pergunta interrompida a seu pedido."

# Assinatura do "executor do agente" (injetado; nos testes é um agente falso):
#   executar(pergunta, *, ao_evento, deve_parar, dormir) -> ResultadoDoAgente
ExecutorDoAgente = Callable[..., ResultadoDoAgente]


def criar_executor_real(config: ConfigLLM, cliente: Any, tools: Sequence[Callable],
                        max_passos: int = 8) -> ExecutorDoAgente:
    """O executor de verdade: o agente do projeto, com o modelo e as tools reais."""
    def executar(pergunta: str, *, ao_evento, deve_parar, dormir) -> ResultadoDoAgente:
        return executar_agente(pergunta, cliente, config.modelo, tools, temperatura=config.temperatura,
                               max_passos=max_passos, ao_evento=ao_evento, deve_parar=deve_parar, dormir=dormir)
    return executar


def _linha(evento: Dict[str, Any]) -> bytes:
    return (json.dumps(evento, ensure_ascii=False, default=str) + "\n").encode("utf-8")


class _Andamento:
    """Estado da pergunta em andamento (no máximo uma)."""

    def __init__(self) -> None:
        self.trava = threading.Lock()
        self.cancelar: Optional[threading.Event] = None


def criar_app(executar: ExecutorDoAgente, config: ConfigLLM, *, modo: str = "real", porta: int = 8000,
              timeout_segundos: float = TIMEOUT_PADRAO_EM_SEGUNDOS,
              env: Optional[Mapping[str, str]] = None) -> Seguranca:
    """Monta a aplicação. `env` só serve para os testes indicarem quais segredos devem ser escondidos
    (None = os do ambiente do processo, onde carregar_env() pôs o .env)."""
    app = FastAPI(title="Chat do agente de vendas", docs_url=None, redoc_url=None, openapi_url=None)
    andamento = _Andamento()

    # ------------------------------------------------------------------ páginas
    @app.get("/", include_in_schema=False)
    def pagina_inicial():
        index = ESTATICOS / "index.html"
        if not index.is_file():
            return resposta_de_erro(404, "nao_encontrado", "O front-end ainda não foi instalado (chat/static/).")
        return FileResponse(index, headers={"Cache-Control": "no-store"})

    if ESTATICOS.is_dir():
        app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    @app.get("/api/saude")
    def saude():
        # Só o que é público: NUNCA chaves, tokens ou endereços do .env.
        return {"ok": True, "modo": modo, "provedor": config.provedor, "modelo": config.modelo,
                "ocupado": andamento.trava.locked()}

    # ------------------------------------------------------------------ perguntar
    @app.post("/api/perguntar")
    async def perguntar(request: Request):
        pergunta, problema = await _ler_pergunta(request)
        if problema is not None:
            return problema
        if not andamento.trava.acquire(blocking=False):
            return resposta_de_erro(409, "ocupado", "Já existe uma pergunta em andamento. Aguarde ela terminar "
                                                    "ou clique em Parar.")
        try:
            loop = asyncio.get_running_loop()
            fila: asyncio.Queue = asyncio.Queue()
            cancelar = threading.Event()
            andamento.cancelar = cancelar

            def entregar(evento: Dict[str, Any]) -> None:
                # Chamado pela thread do agente: só o laço do servidor pode mexer na fila.
                loop.call_soon_threadsafe(fila.put_nowait, evento)

            threading.Thread(target=_trabalhar, args=(pergunta, entregar, cancelar),
                             name="agente-do-chat", daemon=True).start()
        except BaseException:
            andamento.cancelar = None
            andamento.trava.release()
            raise
        return StreamingResponse(_fluxo(fila, cancelar), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/parar")
    async def parar(request: Request):
        if not _e_json(request):
            return resposta_de_erro(415, "validacao", "Envie o pedido como JSON (Content-Type: application/json).")
        cancelar = andamento.cancelar
        if cancelar is not None:
            cancelar.set()
        return {"ok": True, "havia_pergunta": cancelar is not None}

    # ------------------------------------------------------------------ peças internas
    def _trabalhar(pergunta: str, entregar: Callable[[Dict[str, Any]], None], cancelar: threading.Event) -> None:
        """Roda na thread. Sempre entrega um desfecho e SEMPRE libera a trava (finally)."""
        def entregar_com_seguranca(evento: Dict[str, Any]) -> None:
            try:
                entregar(evento)
            except RuntimeError:
                pass                     # o laço do servidor já fechou (cliente foi embora): ninguém ouve

        try:
            try:
                resultado = executar(pergunta, ao_evento=entregar, deve_parar=cancelar.is_set, dormir=cancelar.wait)
            except PerguntaCancelada:
                entregar_com_seguranca({"evento": "cancelado", "mensagem": MENSAGEM_CANCELADA})
            except Exception as erro:  # noqa: BLE001 - qualquer falha vira um evento 'erro' seguro
                registrar_erro(erro, env)
                entregar_com_seguranca(classificar_erro(erro, config, env))
            else:
                # Se o executor já emitiu 'fim', este é ignorado (o fluxo para no primeiro terminal).
                entregar_com_seguranca({"evento": "_retorno", "fim": evento_fim(resultado)})
        finally:
            if andamento.cancelar is cancelar:
                andamento.cancelar = None
            andamento.trava.release()

    async def _fluxo(fila: asyncio.Queue, cancelar: threading.Event):
        """Repassa os eventos da fila até o primeiro terminal (ou o timeout)."""
        limite = time.monotonic() + timeout_segundos
        terminou = False
        try:
            while True:
                try:
                    evento = await asyncio.wait_for(fila.get(), timeout=max(0.0, limite - time.monotonic()))
                except asyncio.TimeoutError:
                    cancelar.set()
                    terminou = True
                    yield _linha(evento_de_erro(
                        "tempo_esgotado", f"A pergunta passou do tempo máximo de {timeout_segundos:g} s e foi "
                                          "interrompida. Tente de novo; se repetir, simplifique a pergunta.", env))
                    return
                if evento.get("evento") == "_retorno":
                    evento = evento["fim"]
                terminal = evento.get("evento") in EVENTOS_TERMINAIS
                terminou = terminou or terminal
                yield _linha(evento)
                if terminal:
                    return
        finally:
            if not terminou:
                cancelar.set()           # o navegador foi embora no meio: pedimos ao agente para parar

    return Seguranca(app, porta)


def _e_json(request: Request) -> bool:
    return request.headers.get("content-type", "").split(";")[0].strip().lower() == "application/json"


async def _ler_pergunta(request: Request):
    """Devolve (pergunta, None) se válida, ou (None, resposta de erro)."""
    if not _e_json(request):
        return None, resposta_de_erro(415, "validacao", "Envie a pergunta como JSON (Content-Type: application/json).")
    try:
        corpo = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return None, resposta_de_erro(400, "validacao", "O corpo do pedido não é um JSON válido.")
    pergunta = corpo.get("pergunta") if isinstance(corpo, dict) else None
    if not isinstance(pergunta, str):
        return None, resposta_de_erro(400, "validacao", "Informe o campo 'pergunta' com um texto.")
    pergunta = pergunta.strip()
    if not pergunta:
        return None, resposta_de_erro(400, "validacao", "A pergunta está vazia.")
    if len(pergunta) > MAX_CARACTERES_DA_PERGUNTA:
        return None, resposta_de_erro(400, "validacao", f"A pergunta tem {len(pergunta)} caracteres; o limite é "
                                                        f"{MAX_CARACTERES_DA_PERGUNTA}.")
    return pergunta, None
