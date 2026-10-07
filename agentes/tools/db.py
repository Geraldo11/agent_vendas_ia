"""Acesso ao Databricks: executa SQL com PARÂMETROS e devolve lista de dicionários.

Autenticação: o WorkspaceClient lê DATABRICKS_HOST e DATABRICKS_TOKEN do ambiente.
O ID do SQL Warehouse vem de DATABRICKS_WAREHOUSE_ID.
"""
from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

from .config import ENV_WAREHOUSE

Linha = Dict[str, Any]
Executor = Callable[[str, Optional[Dict[str, Any]]], List[Linha]]

_cliente = None

ENV_OBRIGATORIAS = ("DATABRICKS_HOST", "DATABRICKS_TOKEN")
# Trechos que só existem nos valores de EXEMPLO do .env.example
_VALORES_DE_EXEMPLO = ("seu-workspace", "coloque_", "cole_", "_aqui")


def extrair_warehouse_id(valor: str) -> str:
    """Aceita só o ID ('5743803c731887dd') ou o HTTP path completo
    ('/sql/1.0/warehouses/5743803c731887dd') e devolve apenas o ID."""
    partes = [p for p in (valor or "").strip().split("/") if p]
    return partes[-1] if partes else ""


def problema_no_host(host: str) -> Optional[str]:
    """Devolve a descrição do problema se o host for malformado; None se estiver correto.

    Forma correta: exatamente  https://<nome>.cloud.databricks.com  (barra final é tolerada).
    """
    if not host:
        return None  # ausência já é tratada em validar_ambiente
    p = urllib.parse.urlparse(host)
    if p.scheme != "https" or not p.netloc:
        return (f"DATABRICKS_HOST malformado (recebido: {host!r}); "
                "deve ser exatamente https://<nome>.cloud.databricks.com, com duas barras depois de 'https:'")
    if p.query or p.params or p.path.strip("/"):
        return "DATABRICKS_HOST deve ser só o endereço, sem caminho nem '?o=...' no final"
    return None


def validar_ambiente(nomes=ENV_OBRIGATORIAS, env=None) -> None:
    """Confere o .env ANTES de falar com o Databricks e explica o que está errado.

    Sem isto, um host de exemplo (SEU-WORKSPACE...) faz o SDK esperar 5 minutos por uma
    resposta que nunca virá. Aqui o erro aparece na hora.
    """
    env = os.environ if env is None else env
    problemas = []
    for nome in nomes:
        valor = (env.get(nome) or "").strip()
        if not valor:
            problemas.append(f"{nome} não está definida")
        elif any(trecho in valor.lower() for trecho in _VALORES_DE_EXEMPLO):
            problemas.append(f"{nome} ainda tem o valor de exemplo do .env.example")
    token = env.get("DATABRICKS_TOKEN") or ""
    if token and re.search(r"[\s\"']", token) and not any(p.startswith("DATABRICKS_TOKEN") for p in problemas):
        problemas.append("DATABRICKS_TOKEN contém espaço, aspas ou quebra de linha (cole só o valor, sem aspas)")
    bruto_wh = (env.get(ENV_WAREHOUSE) or "").strip()
    if ENV_WAREHOUSE in nomes and bruto_wh and not any(p.startswith(ENV_WAREHOUSE) for p in problemas):
        if not re.fullmatch(r"[0-9a-fA-F]{8,}", extrair_warehouse_id(bruto_wh)):
            problemas.append(
                f"{ENV_WAREHOUSE} não parece um ID de warehouse (recebido: {bruto_wh!r}); "
                "use só o final do HTTP path, por exemplo 5743803c731887dd"
            )
    problema = problema_no_host((env.get("DATABRICKS_HOST") or "").strip())
    if problema and not any(p.startswith("DATABRICKS_HOST") for p in problemas):
        problemas.append(problema)
    if problemas:
        raise RuntimeError(
            "Configuração do .env incompleta:\n  - " + "\n  - ".join(problemas)
            + "\nCorrija o .env, saia do container (exit) e entre de novo."
        )


def obter_cliente():
    """Cria o cliente uma vez só (import tardio: os testes não precisam do SDK)."""
    global _cliente
    if _cliente is None:
        validar_ambiente()
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.core import Config

        # Limites de tempo: falhar em segundos/minuto em vez de esperar 5 min em silêncio
        host = "https://" + urllib.parse.urlparse(os.environ["DATABRICKS_HOST"].strip()).netloc
        _cliente = WorkspaceClient(config=Config(host=host, http_timeout_seconds=30, retry_timeout_seconds=60))
    return _cliente


def _tipo_do_parametro(valor: Any) -> str:
    if isinstance(valor, bool):          # bool vem antes de int (True é um int em Python)
        return "BOOLEAN"
    if isinstance(valor, int):
        return "BIGINT"
    if isinstance(valor, float):
        return "DOUBLE"
    return "STRING"


def converter_valor(valor: Optional[str], tipo: Any) -> Any:
    """A API devolve tudo como texto; converte para o tipo Python da coluna."""
    if valor is None:
        return None
    nome = str(getattr(tipo, "value", tipo)).upper()
    if nome in {"BYTE", "SHORT", "INT", "LONG"}:
        return int(valor)
    if nome in {"FLOAT", "DOUBLE", "DECIMAL"}:
        return float(valor)
    if nome == "BOOLEAN":
        return str(valor).lower() == "true"
    return valor  # STRING, DATE (texto ISO "2026-05-10"), TIMESTAMP...


def linhas_para_dicts(colunas: List[Any], matriz: Optional[List[List[Optional[str]]]]) -> List[Linha]:
    resultado = []
    for linha in matriz or []:
        resultado.append({
            col.name: converter_valor(valor, col.type_name)
            for col, valor in zip(colunas, linha)
        })
    return resultado


def executar_sql(sql: str, parametros: Optional[Dict[str, Any]] = None) -> List[Linha]:
    """Executa uma consulta no SQL Warehouse. Valores entram SEMPRE como parâmetros (:nome)."""
    from databricks.sdk.service.sql import StatementParameterListItem, StatementState

    validar_ambiente(ENV_OBRIGATORIAS + (ENV_WAREHOUSE,))
    warehouse_id = extrair_warehouse_id(os.environ[ENV_WAREHOUSE])

    lista = [
        StatementParameterListItem(name=nome, value=str(valor), type=_tipo_do_parametro(valor))
        for nome, valor in (parametros or {}).items()
    ]
    resposta = obter_cliente().statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, parameters=lista or None, wait_timeout="30s",
    )

    if resposta.status.state != StatementState.SUCCEEDED:
        erro = resposta.status.error.message if resposta.status.error else str(resposta.status.state)
        raise RuntimeError(f"Consulta falhou: {erro}")

    colunas = resposta.manifest.schema.columns
    matriz = resposta.result.data_array if resposta.result else None
    return linhas_para_dicts(colunas, matriz)
