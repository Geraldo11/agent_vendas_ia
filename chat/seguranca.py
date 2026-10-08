"""Proteções que valem para TODAS as respostas do servidor.

1. Cabeçalhos: CSP estrita (só scripts e estilos do próprio servidor), nosniff e no-referrer.
2. Host: só 127.0.0.1:<porta> ou localhost:<porta>. Protege contra "DNS rebinding": um site malicioso
   faz o domínio dele apontar para 127.0.0.1 e, sem esta checagem, conversaria com o nosso servidor.
3. Origin: em métodos que alteram algo (POST...), se o navegador mandar Origin, ele tem de ser o nosso.
   Isso impede que outra página aberta no seu navegador dispare perguntas e gaste os seus tokens.

É um middleware ASGI "puro" (e não @app.middleware): este formato não interfere nas respostas em fluxo
nem na detecção de cliente desconectado.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Set

from starlette.responses import JSONResponse

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
CABECALHOS_DE_SEGURANCA = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
]
_NOMES = {nome for nome, _ in CABECALHOS_DE_SEGURANCA}
METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


def hosts_permitidos(porta: int) -> Set[str]:
    return {f"127.0.0.1:{porta}", f"localhost:{porta}"}


def origens_permitidas(porta: int) -> Set[str]:
    return {f"http://{host}" for host in hosts_permitidos(porta)}


def resposta_de_erro(status: int, tipo: str, mensagem: str) -> JSONResponse:
    """Formato único dos erros que NÃO são do fluxo de eventos (validação, 409, recusas)."""
    return JSONResponse({"erro": {"tipo": tipo, "mensagem": mensagem}}, status_code=status,
                        headers={"Cache-Control": "no-store"})


class Seguranca:
    def __init__(self, app: Callable[..., Awaitable[None]], porta: int):
        self.app = app
        self.hosts = hosts_permitidos(porta)
        self.origens = origens_permitidas(porta)

    def _recusa(self, metodo: str, cabecalhos: Dict[str, str]):
        if cabecalhos.get("host", "").lower() not in self.hosts:
            return resposta_de_erro(400, "recusado", "Endereço não permitido. Abra o chat por "
                                                     "http://127.0.0.1 ou http://localhost, na porta configurada.")
        origem = cabecalhos.get("origin")
        if metodo not in METODOS_SEGUROS and origem is not None and origem.lower() not in self.origens:
            return resposta_de_erro(403, "recusado", "Pedido vindo de outra página recusado.")
        return None

    async def __call__(self, scope: Dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def enviar_com_cabecalhos(mensagem: Dict[str, Any]) -> None:
            if mensagem["type"] == "http.response.start":
                atuais = [(n, v) for n, v in mensagem.get("headers", []) if n.lower() not in _NOMES]
                mensagem = {**mensagem, "headers": atuais + CABECALHOS_DE_SEGURANCA}
            await send(mensagem)

        cabecalhos = {n.decode("latin-1").lower(): v.decode("latin-1") for n, v in scope.get("headers", [])}
        recusa = self._recusa(scope["method"], cabecalhos)
        if recusa is not None:
            await recusa(scope, receive, enviar_com_cabecalhos)
            return
        await self.app(scope, receive, enviar_com_cabecalhos)
