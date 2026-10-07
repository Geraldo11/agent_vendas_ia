# CLAUDE.md

Projeto de estudo: agentes de IA sobre dados no Databricks que explicam por que uma venda **não entrou na
carteira** de um vendedor (empresa fictícia; produtos Consórcio e Capitalização).

Contexto completo, decisões, divergências e roteiro: `docs/CONTEXTO_DO_PROJETO.md`.
**Não é carregado automaticamente: leia quando precisar** (estado atual, fases do projeto, armadilhas).
Se o documento e o código divergirem, **vale o código**; avise-me para eu atualizar o documento.

## Como trabalhar comigo

- Responda em **português do Brasil**.
- Atue como **professor paciente**: eu estou aprendendo. Explique cada arquivo criado ou alterado e o
  **porquê** das decisões, com exemplos, em vez de só entregar código.
- Mudanças grandes: **proponha o plano e espere meu OK**. Prefira passos pequenos.
- Rode `pytest` depois de mexer em código e diga com clareza **o que não foi testado**.
- Se perceber um erro seu anterior (contagem, previsão, código), diga na hora.
- **Nunca** leia, imprima, edite ou me peça para colar o conteúdo do `.env` (tem token do Databricks e chave
  do Groq). Para configuração, trabalhe só com `.env.example` e os **nomes** das variáveis.
- **Não rode sem eu confirmar:** `terraform apply` ou `destroy`, `git push`, `databricks fs cp --overwrite`.
- Antes de afirmar algo sobre o estado do código, **confira os arquivos** (rode `scripts/verificar_repositorio.py`).
- Você **não enxerga o workspace do Databricks**. Para saber o estado dele, peça a saída de um comando.

## Ambiente

- Windows, PowerShell, VS Code. Python local 3.13; o container usa Python 3.11.
- `pytest` roda direto na máquina. Última contagem (07/10/2026): **223 testes** (221 passam e 2 são pulados
  sem o `databricks-sdk` instalado).
- **Terraform e Databricks CLI só existem no container:** `docker compose run --rm dev`
  (o Docker Desktop precisa estar ligado). Comandos Linux (`find`, `databricks`, `terraform`) não funcionam
  no PowerShell.
- O código das regras tem uma **cópia no volume** `/Volumes/vendas_ia/apoio/docs/`. O gold e as tools leem
  essa cópia. **Depois de alterar `regras/` ou `ingestao/`, ela precisa ser reenviada** (ver Comandos).

## Estrutura

- `regras/`: regras de negócio em Python (`avaliar_venda`). `comum.py`, `consorcio.py`,
  `capitalizacao.py`, registro em `registro.py`.
- `agentes/`: `agente.py` (laço do agente), `esquemas.py`, `llm.py` (provedores) e `tools/` (7 tools).
- `notebooks/`: 01 bronze, 02 silver, 03 gold, 04 gabarito de divergências, 05 chunks do manual.
- `ingestao/`: divide o PDF do manual em chunks. `docs/`: manual em PDF.
- `avaliacao/casos.json` (gerado por `scripts/gerar_casos.py`): **conjunto de casos de avaliação** do agente, com o
  resultado esperado segundo o manual. É a "prova": o agente em execução **não** o lê.
- `terraform/`: catálogo, schemas e volumes. `scripts/`: utilitários. `tests/`: pytest.

## Regras de negócio e manual

- Ordem de avaliação: `COM-02 → COM-01 → COM-03 →` regras do produto. A primeira que bloqueia define o motivo.
- **O manual (PDF v2.3) é a fonte da verdade.** O código diverge dele **de propósito** em 4 pontos
  (D1 a D4, tabela `apoio.gabarito_divergencias`). Eles são o gabarito do projeto: **não os corrija sem eu
  pedir.**
- As tabelas `gabarito_*` são a "prova": os agentes **não podem** ter acesso a elas.

## Convenções

- Toda regra nova: função com ID e docstring, entrada em `REGRAS` na ordem certa, **teste** e trecho no manual.
- Tools: **somente leitura**; SQL **parametrizado** (nunca concatenar valores no texto do SQL); nomes de
  tabela só via `agentes/tools/config.py`. O código das regras é lido com `ast`, **nunca importado nem
  executado** pelo agente.
- Testes de tool usam um `executor` falso (sem Databricks). Teste a **existência** de um parâmetro, não o
  valor que vai mudar quando as divergências forem corrigidas.
- Valide testes novos com **mutação** (quebre o código de propósito e confira que o teste falha).
- Terraform: sempre `plan -out=tfplan`, ler o plano e só então aplicar. Procure `-/+` e `forces replacement`.
- Cuidado com nomes de arquivo com `(1)` ou espaço (ex.: `__init__ (1).py`): o Python ignora.

## Comandos

```bash
pytest                                          # testes (na máquina ou no container)
docker compose run --rm dev                     # abre o container (PowerShell)

# dentro do container, na raiz do projeto
find regras ingestao -name __pycache__ -exec rm -rf {} +
databricks fs cp --recursive regras dbfs:/Volumes/vendas_ia/apoio/docs/regras --overwrite
databricks fs cp --recursive ingestao dbfs:/Volumes/vendas_ia/apoio/docs/ingestao --overwrite
python scripts/tools_ao_vivo.py                  # as 7 tools contra o workspace real (NÃO é teste)
python scripts/verificar_repositorio.py          # confere arquivos e versões da cópia local
python scripts/verificar_env.py                  # confere o .env SEM mostrar valores (use este, não leia o .env)
python scripts/listar_modelos.py                 # modelos que a chave do provedor pode usar (eles são descontinuados)
python scripts/gerar_casos.py                    # acha no banco um exemplo real de cada caso e grava avaliacao/casos.json
python scripts/testar_llm.py                    # testa só o modelo (3 etapas)
python scripts/perguntar.py "Por que a venda VD000084 não entrou na carteira?"
```

## `.env` (só os nomes; nunca os valores)

`DATABRICKS_HOST` (https://..., sem barra final nem `?o=`), `DATABRICKS_TOKEN` (sem aspas),
`DATABRICKS_WAREHOUSE_ID` (só o ID), `LLM_PROVIDER`, `LLM_MODEL`, `GROQ_API_KEY`.
Os scripts **carregam o `.env` sozinhos** (`agentes/ambiente.py`), no PowerShell ou no container; no
PowerShell é preciso `pip install -r requirements.txt` antes. Depois de editar o `.env`, **reabra o container**.
**Modelos de LLM mudam e são descontinuados** (o Groq desativou o `llama-3.3-70b-versatile` em 16/08/2026):
nunca fixe um nome de modelo de memória; confirme com `scripts/listar_modelos.py`.
Formato: `NOME=valor`, uma por linha, **sem espaço no início, sem aspas e sem linhas `NOME=` vazias**
(a última ocorrência vale e uma vazia anula as anteriores). Para diagnosticar: `python scripts/verificar_env.py`.
