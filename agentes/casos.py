"""Casos de teste para AVALIAR o agente: um exemplo real de cada situação, com o resultado esperado
SEGUNDO O MANUAL (a fonte da verdade).

Dois tipos de caso:
  - DIVERGÊNCIA (D1 a D4): código e manual discordam. O agente precisa perceber.
  - CONTROLE (C_...): código e manual concordam. O agente NÃO pode inventar divergência.

Os IDs de venda vêm do banco (gold e silver). Este arquivo é a "prova": os agentes não o leem.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .tools.config import GOLD, SILVER
from .tools.db import executar_sql

_BASE = f"""
SELECT a.id_venda, a.produto, a.id_vendedor, a.data_venda, a.regra_id, a.elegivel,
       s.data_cancelamento, co.tipo_consorcio, ca.modalidade
FROM {GOLD}.avaliacao_venda a
LEFT JOIN {SILVER}.venda_status s ON s.id_venda = a.id_venda
LEFT JOIN {SILVER}.venda_consorcio co ON co.id_venda = a.id_venda
LEFT JOIN {SILVER}.venda_capitalizacao ca ON ca.id_venda = a.id_venda
"""

_EXCLUIDA = "Por que a venda {id_venda} não entrou na carteira do vendedor {id_vendedor}?"
_EXCLUIDA_SEM_VENDEDOR = "Por que a venda {id_venda} não gerou produção para nenhum vendedor?"
_CONFERIR = "A venda {id_venda} entrou na carteira do vendedor {id_vendedor}. Ela deveria ter entrado, segundo as regras vigentes?"


@dataclass(frozen=True)
class Caso:
    nome: str
    descricao: str
    filtro_sql: Optional[str]            # None = caso sem venda (pergunta fixa)
    pergunta: str                        # aceita {id_venda} e {id_vendedor}
    entra_pelo_manual: bool              # a venda deveria estar na carteira segundo o MANUAL?
    divergencia: Optional[str]           # D1..D4, ou None nos controles
    deve_citar: List[str] = field(default_factory=list)
    deve_apontar_divergencia: bool = False


CASOS: List[Caso] = [
    # ---------------- divergências (o agente precisa perceber)
    Caso("D3_moto", "Consórcio de MOTO excluído por CONS-01; o manual aceita moto",
         "a.regra_id = 'CONS-01' AND co.tipo_consorcio = 'moto' AND a.id_vendedor IS NOT NULL",
         _EXCLUIDA, True, "D3", ["CONS-01", "moto"], True),
    Caso("D1_arrependimento_8a10", "Consórcio cancelado entre 8 e 10 dias: o código deixa entrar, o manual (10 dias) excluiria",
         "a.produto = 'consorcio' AND a.elegivel AND datediff(s.data_cancelamento, a.data_venda) BETWEEN 8 AND 10",
         _CONFERIR, False, "D1", ["COM-03", "10"], True),
    Caso("D2_carencia_61a90", "Capitalização cancelada entre 61 e 90 dias: o código deixa entrar, o manual (90 dias) excluiria",
         "a.produto = 'capitalizacao' AND a.elegivel AND datediff(s.data_cancelamento, a.data_venda) BETWEEN 61 AND 90",
         _CONFERIR, False, "D2", ["CAP-03", "90"], True),
    Caso("D4_dia_do_desligamento", "Divergência LATENTE (nenhuma venda a prova): só aparece lendo código e manual",
         None,
         "Um vendedor foi desligado em 10/03/2026 e fez uma venda nesse mesmo dia. Essa venda conta para a carteira dele?",
         True, "D4", ["COM-01"], True),
    # ---------------- controles (código e manual concordam; o agente NÃO pode inventar divergência)
    Caso("C_servicos", "Consórcio de serviços: excluído pelo código e pelo manual",
         "a.regra_id = 'CONS-01' AND co.tipo_consorcio = 'servicos' AND a.id_vendedor IS NOT NULL",
         _EXCLUIDA, False, None, ["CONS-01"]),
    Caso("C_arrependimento_ate7", "Cancelamento em até 7 dias: excluído (COM-03) com 7 ou com 10 dias",
         "a.regra_id = 'COM-03' AND a.id_vendedor IS NOT NULL", _EXCLUIDA, False, None, ["COM-03"]),
    Caso("C_carencia_8a60", "Capitalização cancelada na carência: excluída com 60 ou com 90 dias",
         "a.regra_id = 'CAP-03' AND a.id_vendedor IS NOT NULL", _EXCLUIDA, False, None, ["CAP-03"]),
    Caso("C_elegivel_consorcio", "Consórcio elegível, sem cancelamento: deve estar na carteira",
         "a.produto = 'consorcio' AND a.elegivel AND s.data_cancelamento IS NULL", _CONFERIR, True, None, []),
    Caso("C_elegivel_capitalizacao", "Capitalização elegível, sem cancelamento: deve estar na carteira",
         "a.produto = 'capitalizacao' AND a.elegivel AND s.data_cancelamento IS NULL", _CONFERIR, True, None, []),
    Caso("C_vendedor_inativo", "Venda de vendedor já desligado: excluída (COM-01)",
         "a.regra_id = 'COM-01'", _EXCLUIDA, False, None, ["COM-01"]),
    Caso("C_digital_sem_vendedor", "Venda digital sem vendedor identificado (COM-02)",
         "a.regra_id = 'COM-02'", _EXCLUIDA_SEM_VENDEDOR, False, None, ["COM-02"]),
    Caso("C_sem_primeira_parcela", "Consórcio sem pagamento da 1ª parcela (CONS-02)",
         "a.regra_id = 'CONS-02' AND a.id_vendedor IS NOT NULL", _EXCLUIDA, False, None, ["CONS-02"]),
    Caso("C_modalidade_fora", "Capitalização de modalidade não elegível (CAP-01)",
         "a.regra_id = 'CAP-01' AND a.id_vendedor IS NOT NULL", _EXCLUIDA, False, None, ["CAP-01"]),
    Caso("C_mensal_sem_mensalidade", "Capitalização mensal sem a 1ª mensalidade (CAP-02)",
         "a.regra_id = 'CAP-02' AND a.id_vendedor IS NOT NULL", _EXCLUIDA, False, None, ["CAP-02"]),
]


def _sql_do_caso(caso: Caso, por_caso: int) -> str:
    # O filtro é uma constante deste arquivo; o LIMIT passa por int() e por um teto (não aceita parâmetro).
    return f"{_BASE} WHERE {caso.filtro_sql} ORDER BY a.id_venda LIMIT {max(1, min(int(por_caso), 5))}"


def selecionar_casos(executor: Optional[Callable] = None, por_caso: int = 1) -> List[Dict[str, Any]]:
    """Busca no banco exemplos reais de cada caso. Sem venda encontrada, o caso sai com um aviso."""
    executar = executor or executar_sql
    resultado: List[Dict[str, Any]] = []
    for caso in CASOS:
        base = asdict(caso)
        base.pop("filtro_sql")
        if caso.filtro_sql is None:
            resultado.append({**base, "id_venda": None, "id_vendedor": None})
            continue
        linhas = executar(_sql_do_caso(caso, por_caso), None)
        if not linhas:
            resultado.append({**base, "id_venda": None, "id_vendedor": None,
                              "aviso": "nenhuma venda encontrada para este caso nos dados atuais"})
            continue
        for linha in linhas:
            dados = {"id_venda": linha["id_venda"], "id_vendedor": linha.get("id_vendedor") or ""}
            resultado.append({**base, **dados, "pergunta": caso.pergunta.format(**dados)})
    return resultado


def salvar_casos(casos: List[Dict[str, Any]], caminho: Path) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(casos, ensure_ascii=False, indent=2), encoding="utf-8")
