"""Configuração do modelo de linguagem. Qualquer servidor com API compatível com a da OpenAI serve.

Provedores:
  LLM_PROVIDER=databricks  -> modelos hospedados no seu workspace (usa DATABRICKS_HOST e DATABRICKS_TOKEN)
  LLM_PROVIDER=ollama      -> modelo aberto rodando na sua máquina (Ollama)
  LLM_PROVIDER=groq        -> API do Groq (modelos abertos; plano gratuito com limites) usa GROQ_API_KEY
  LLM_PROVIDER=compat      -> qualquer outro servidor compatível (LLM_BASE_URL e LLM_API_KEY)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional


@dataclass(frozen=True)
class ConfigLLM:
    provedor: str
    base_url: str
    api_key: str
    modelo: str
    temperatura: float = 0.0


def configuracao_do_llm(env: Optional[Mapping[str, str]] = None) -> ConfigLLM:
    env = os.environ if env is None else env
    provedor = (env.get("LLM_PROVIDER") or "").strip().lower()
    modelo = (env.get("LLM_MODEL") or "").strip()
    temperatura = float(env.get("LLM_TEMPERATURE") or 0)

    if provedor not in {"databricks", "ollama", "groq", "compat"}:
        raise RuntimeError(
            "Defina LLM_PROVIDER no .env: databricks, ollama, groq ou compat. "
            "Para conferir o arquivo sem mostrar segredos: python scripts/verificar_env.py"
        )
    if not modelo:
        raise RuntimeError("Defina LLM_MODEL no .env (nome do modelo ou do endpoint)")

    if provedor == "databricks":
        host = (env.get("DATABRICKS_HOST") or "").strip().rstrip("/")
        token = (env.get("DATABRICKS_TOKEN") or "").strip()
        if not host or not token:
            raise RuntimeError("LLM_PROVIDER=databricks exige DATABRICKS_HOST e DATABRICKS_TOKEN")
        return ConfigLLM(provedor, f"{host}/serving-endpoints", token, modelo, temperatura)

    if provedor == "groq":
        chave = (env.get("GROQ_API_KEY") or "").strip()
        if not chave:
            raise RuntimeError("LLM_PROVIDER=groq exige GROQ_API_KEY no .env")
        if re.search(r"[\s\"']", chave):
            raise RuntimeError("GROQ_API_KEY contém espaço, aspas ou quebra de linha (cole só o valor, sem aspas)")
        if any(trecho in chave.lower() for trecho in ("coloque_", "cole_", "_aqui", "sua_chave")):
            raise RuntimeError("GROQ_API_KEY ainda tem o valor de exemplo do .env.example")
        base = (env.get("LLM_BASE_URL") or "https://api.groq.com/openai/v1").strip()
        return ConfigLLM(provedor, base, chave, modelo, temperatura)

    if provedor == "ollama":
        base = (env.get("LLM_BASE_URL") or "http://host.docker.internal:11434/v1").strip()
        return ConfigLLM(provedor, base, "ollama", modelo, temperatura)

    base = (env.get("LLM_BASE_URL") or "").strip()
    if not base:
        raise RuntimeError("LLM_PROVIDER=compat exige LLM_BASE_URL")
    return ConfigLLM(provedor, base, (env.get("LLM_API_KEY") or "sem-chave").strip(), modelo, temperatura)


def criar_cliente(config: ConfigLLM):
    """Cria o cliente (import tardio: os testes não precisam da biblioteca instalada)."""
    from openai import OpenAI

    return OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=120, max_retries=1)


# --------------------------------------------------------------------------- modelos e erros do provedor
_NAO_E_DE_CHAT = ("whisper", "guard", "tts", "orpheus", "embed", "safeguard")


def listar_modelos(cliente: Any) -> List[str]:
    """IDs dos modelos que a SUA chave pode usar (consulta o provedor; a lista nunca fica desatualizada)."""
    return sorted(m.id for m in cliente.models.list())


def modelos_de_chat(ids: List[str]) -> List[str]:
    """Tira da lista os modelos que não são de conversa (voz, moderação, embeddings)."""
    return [i for i in ids if not any(trecho in i.lower() for trecho in _NAO_E_DE_CHAT)]


def explicar_erro_do_provedor(erro: Exception, config: ConfigLLM, cliente: Any = None) -> Optional[str]:
    """Traduz erros HTTP comuns do provedor em orientação em português. None = não reconheci o erro."""
    status = getattr(erro, "status_code", None)
    codigo = getattr(erro, "code", None)

    if status == 404 or codigo == "model_not_found":
        texto = (f"O modelo {config.modelo!r} não existe ou a sua chave não tem acesso a ele (HTTP 404). "
                 "Modelos são descontinuados com frequência (ou o LLM_BASE_URL pode estar errado).")
        if cliente is not None:
            try:
                ids = modelos_de_chat(listar_modelos(cliente))
                texto += "\nModelos de chat disponíveis para a sua chave:\n" + "\n".join(f"  - {i}" for i in ids)
                texto += "\nEscolha um, ajuste LLM_MODEL no .env e rode de novo (o passo [2/3] confirma se ele suporta tools)."
            except Exception:  # noqa: BLE001
                texto += "\nNão consegui listar os modelos agora; rode: python scripts/listar_modelos.py"
        return texto
    if status == 401:
        return "Chave recusada pelo provedor (HTTP 401): confira a chave no .env (sem aspas) ou gere outra."
    if status == 403:
        return "Acesso negado (HTTP 403): a chave ou a organização não tem permissão para este modelo ou região."
    if status == 400:
        return f"Pedido recusado pelo provedor (HTTP 400): {str(erro)[:300]}"
    return None
