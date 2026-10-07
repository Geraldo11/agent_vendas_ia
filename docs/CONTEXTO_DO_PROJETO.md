# Contexto do projeto: agentes de vendas fora da carteira (Databricks)

> **Atualizado em 07/10/2026.** Documento para dar contexto a um assistente (ou a uma pessoa) sobre
> **onde o projeto está** e **aonde queremos chegar**. Não contém segredos: tokens, chaves e endereços
> do workspace ficam só no `.env`.

---

## 1. Objetivo

Construir, como projeto de estudo, um sistema de **agentes de IA ligados a dados no Databricks** que
responde a dúvidas de vendedores de uma **empresa fictícia (Alfa Seguridade)** que vende **Consórcio**
e **Capitalização**.

**A pergunta típica:** *"Fiz esta venda e ela não apareceu na minha carteira. Por quê?"*

**Como o sistema deve responder:**
1. Achar a venda e ver o que o pipeline decidiu (entrou ou não, e por qual regra).
2. Ler o **código** que aplica a regra de negócio.
3. Ler o **manual em PDF** (fonte da verdade) sobre a mesma regra.
4. **Comparar código e manual.** Se divergirem, dizer isso e informar que o manual prevalece.
5. Responder citando o ID da regra e os valores (datas, prazos, tipos).

**Por que é interessante:** o código das regras está **desatualizado de propósito** em 4 pontos em
relação ao manual. O sistema precisa perceber que a venda foi excluída por uma regra que o manual já mudou.

---

## 2. Como quero ser ajudado

- Atuar como **professor paciente**: explicar **cada arquivo e cada passo**, e o **porquê** das decisões.
- Responder em **português do Brasil**.
- Entregar código **testado quando possível** e dizer com clareza **o que não foi testado**.
- Ajudar a **diagnosticar erros** do ambiente (Windows, PowerShell, Docker, Databricks) a partir de
  saídas coladas.
- Apontar erros do próprio assistente quando perceber (já aconteceu: contagens e previsões erradas).
- Nunca pedir que eu cole tokens ou chaves no chat.

---

## 3. Ambiente

| Item | Detalhe |
|---|---|
| Máquina | Windows, VS Code, PowerShell. Python 3.13 local |
| Container | Docker Desktop (**precisa estar ligado**). Imagem com Python 3.11, Terraform 1.9.8 e Databricks CLI |
| Databricks | Workspace na **AWS**, interface **Free Edition**, compute **serverless**, Unity Catalog |
| SQL Warehouse | *Serverless Starter Warehouse* (usado pelas tools para consultar) |
| Catálogo padrão do workspace | `workspace` (o projeto usa nomes completos `vendas_ia.schema.tabela`) |
| Versionamento | Git + GitHub |

**Variáveis do `.env`** (nunca versionar; o `.env.example` é só o modelo):

| Variável | Regra de formato |
|---|---|
| `DATABRICKS_HOST` | `https://<nome>.cloud.databricks.com`, **sem** barra no fim e **sem** `/?o=...` |
| `DATABRICKS_TOKEN` | Valor completo do token (começa com `dapi`), **sem aspas e sem espaços** |
| `DATABRICKS_WAREHOUSE_ID` | **Só o ID** (parte final do HTTP path), não o caminho `/sql/1.0/warehouses/...` |
| `LLM_PROVIDER` | `groq`, `databricks`, `ollama` ou `compat` |
| `LLM_MODEL` | Nome do modelo (ex.: `openai/gpt-oss-120b`). **Modelos mudam**: confirme com `scripts/listar_modelos.py` |
| `GROQ_API_KEY` | Chave do Groq (começa com `gsk_`), sem aspas |

O código **valida o `.env` antes de conectar** e explica o que está errado (host malformado, token com
aspas, ID de warehouse com caminho, valores de exemplo).

---

## 4. Dados: Unity Catalog `vendas_ia`

Arquitetura **medalhão** (bronze → silver → gold), mais um schema de apoio.

| Schema | Tabelas |
|---|---|
| **bronze** (6) | `vendedores_raw`, `vendas_raw`, `consorcio_cotas_raw`, `capitalizacao_titulos_raw`, `eventos_raw`, `carteira_raw` |
| **silver** (7) | `vendedor`, `venda`, `venda_consorcio`, `venda_capitalizacao`, `evento_venda`, `carteira`, `venda_status` |
| **gold** (4) | `avaliacao_venda`, `vendas_fora_carteira`, `carteira_vendedor`, `producao_vendedor` |
| **apoio** (3) | `gabarito_casos`, `gabarito_divergencias`, `manual_chunks` |

**Volumes:** `bronze.raw` (arquivos brutos) e `apoio.docs` (contém as pastas `regras/`, `ingestao/` e
`manuais/` com cópias do código e do PDF, que os agentes leem).

**Dados sintéticos** (semente 42): 60 vendedores (10 desligados em 2026), 5.000 vendas de jan a ago/2026,
~60% consórcio e ~40% capitalização. A bronze tem **sujeira controlada** (~1% de duplicatas, variação de
caixa no canal, datas como texto) que a silver limpa. Cerca de **10 a 11%** das vendas ficam fora da
carteira por **casos plantados**.

**`apoio.gabarito_casos`** guarda a resposta certa de cada venda (caso plantado e regra esperada). Serve
para validar o pipeline e **avaliar o agente**.

> **Atenção:** os agentes **não devem ter acesso** às tabelas `gabarito_*`. Elas são a "prova". Se o
> agente as lesse, a avaliação perderia o sentido.

---

## 5. Regras de negócio

**Ordem de avaliação** (a primeira regra que bloqueia define o motivo):
`COM-02 → COM-01 → COM-03 →` regras do produto.

| ID | Regra | Código atual | Manual v2.3 |
|---|---|---|---|
| COM-01 | Vendedor ativo na data da venda | No dia do desligamento já é inativo (`data_venda >= desligamento` bloqueia) | Ativo **até a data de desligamento, inclusive** |
| COM-02 | Canal digital sem vendedor fica fora | igual | igual |
| COM-03 | Cancelamento no prazo de arrependimento não conta | **7 dias** | **10 dias** |
| CONS-01 | Tipos de consórcio que geram produção | imóvel, auto | imóvel, auto e **moto** |
| CONS-02 | Só conta após o pagamento da 1ª parcela | igual | igual |
| CAP-01 | Modalidades de capitalização elegíveis | tradicional, incentivo | igual |
| CAP-02 | Pagamento único conta na hora; mensal após a 1ª mensalidade | igual | igual |
| CAP-03 | Cancelamento na carência não conta | **60 dias** | **90 dias** |

**Implementação:** módulo Python `regras/`, com interface única
`avaliar_venda(venda) -> Resultado(elegivel, regra_id, motivo)`. Um módulo por produto (`consorcio.py`,
`capitalizacao.py`), regras comuns em `comum.py`, registro `produto → módulo` em `registro.py`. Cada regra
é uma função que devolve `None` (não se aplica) ou um bloqueio.

---

## 6. Manual e divergências planejadas

**Manual:** PDF de 5 páginas (`docs/manual_elegibilidade_v2.3.pdf`), gerado por `scripts/gerar_manual.py`.
Uma regra por bloco (título com o ID, parâmetro, consequência e exemplo) e um histórico de versões.
Foi dividido em **14 chunks** (um por regra e um por seção) e gravado em `apoio.manual_chunks`.

**História por trás:** o código foi escrito segundo a **v2.0** do manual, que evoluiu até a **v2.3** sem o
código acompanhar.

| ID | Regra | Código | Manual | Vendas afetadas | Efeito |
|---|---|---|---|---|---|
| D1 | COM-03 | 7 dias | 10 dias | **3** | Venda entra, mas o manual a excluiria |
| D2 | CAP-03 | 60 dias | 90 dias | **42** | Venda entra, mas o manual a excluiria |
| D3 | CONS-01 | sem moto | com moto | **39** | Venda é excluída, mas o manual a aceitaria |
| D4 | COM-01 | inativo no dia do desligamento | ativo, inclusive | **0** (latente) | Só aparece lendo o código contra o manual |

O gabarito dessas divergências está em `apoio.gabarito_divergencias`.

**Cuidado com o chunk `historico`:** ele contém valores **antigos** (7 dias, 60 dias). A tool de manual o
**exclui por padrão** para o agente não citar um valor desatualizado.

---

## 7. Agente e tools

### As 7 tools (`agentes/tools/`)

| Tool | Para quê | Fonte |
|---|---|---|
| `get_venda(id_venda)` | Dados de uma venda e a avaliação do código | silver + gold |
| `get_carteira_vendedor(id_vendedor)` | Total e vendas recentes da carteira | gold |
| `get_producao(id_vendedor, mes)` | Produção por mês e produto | gold |
| `listar_vendas_fora_carteira(id_vendedor)` | Vendas excluídas e o motivo | gold |
| `listar_regras_aplicadas(produto)` | Regras que o código aplica, em ordem | código no volume |
| `ler_codigo_regra(regra_id)` | Código da regra e suas constantes | código no volume |
| `buscar_manual(consulta, regra_id)` | Trechos do manual | `apoio.manual_chunks` |

**Princípios das tools:** somente leitura; consultas **parametrizadas** (sem injeção de SQL); o código das
regras é **lido como texto (módulo `ast`), nunca executado**; aceitam um `executor` injetável para testar
sem o Databricks. A busca no manual é **lexical** (por palavras), suficiente para 14 chunks.

### O agente (`agentes/`)

- **`esquemas.py`:** gera a descrição JSON de cada tool a partir da própria função (nome, docstring, tipos).
- **`agente.py`:** laço em que o modelo **pede** tools e o **nosso código executa**. Proteções:
  só tools registradas, só argumentos declarados, erros devolvidos ao modelo como `{"erro": ...}`,
  resultados truncados em 8.000 caracteres, **limite de 8 passos**, **contagem de tokens** e **tratamento do
  erro 429** (espera o `retry-after`; se passar de 90 s, entende como limite diário e avisa).
- **`llm.py`:** provedores via API compatível com a da OpenAI: `groq`, `databricks`, `ollama`, `compat`.
  Trocar de provedor é só mudar o `.env`.
- **Prompt do sistema:** instrui a buscar a venda, ler o código da regra, ler o manual, **comparar** (manual
  prevalece), **nunca inventar dados**, citar IDs de regra e não usar o histórico do manual.

### Modelo: Groq (plano gratuito, modelos abertos)

Limites consultados na documentação do Groq (podem mudar; conferir em `console.groq.com/settings/limits`):

| Modelo | Req./min | Req./dia | Tokens/min | Tokens/dia |
|---|---|---|---|---|
| `openai/gpt-oss-120b` e `20b` | 30 | 1.000 | 8.000 | 200.000 |

> **O `llama-3.3-70b-versatile` e o `llama-3.1-8b-instant` foram DESCONTINUADOS em 16/08/2026** (página de
> deprecações do Groq; o erro aparece como `404 model_not_found`). Substitutos sugeridos lá:
> `openai/gpt-oss-120b` ou `qwen/qwen3.6-27b` (no lugar do Llama 70B) e `openai/gpt-oss-20b` (no lugar do 8B).
> Nunca presuma o nome de um modelo: rode `python scripts/listar_modelos.py`.

**Medido (1ª pergunta real):** 4 chamadas ao modelo, **6.292 tokens** (5.758 de entrada + 534 de saída). A
estimativa inicial (8 a 9,5 mil) estava cerca de 30% alta. Com 8.000 tokens por minuto, **uma pergunta cabe**,
mas duas seguidas encostam no limite (o tratamento do 429 espera); com ~200 mil por dia, são cerca de 30
perguntas por dia. Uma avaliação de 14 casos custa ~90 mil tokens. Limites da sua conta:
`console.groq.com/settings/limits`.

### Limitações conhecidas

- **`executar_sql` lê só o primeiro bloco do resultado** da API do warehouse. Para resultados grandes o restante
  seria ignorado em silêncio. As tools limitam as consultas (no máximo 200 linhas); consultas novas devem ser pequenas.
- **O modelo devolve caracteres Unicode especiais** (ex.: espaço fino U+202F em "17 + 25") e Markdown (`**42**`).
  Na avaliação automática, **normalize o texto** (NFKC, sem negrito) antes de comparar.
- **A busca no manual é lexical** (por palavras): acerta a regra pedida pelo ID, mas pode empatar em perguntas vagas.
- **Nomes de modelo envelhecem:** até a sugestão de substituto da página de deprecações do Groq (qwen3.6) já tinha
  sido superada na lista real da chave (qwen3.8). Sempre confirme com `scripts/listar_modelos.py`.

---

## 8. Estrutura do repositório

```
agentes-vendas-ia/
├── agentes/
│   ├── agente.py          laço do agente, tokens, tratamento de 429
│   ├── ambiente.py        lê o .env e diagnostica problemas de formato (sem mostrar valores)
│   ├── casos.py           casos de avaliação (um exemplo real por situação, com o esperado pelo manual)
│   ├── esquemas.py        função Python -> descrição JSON da tool
│   ├── llm.py             provedores de modelo (groq, databricks, ollama, compat)
│   └── tools/             config, db, dados, regras_codigo, manual
├── avaliacao/             casos.json (gerado por scripts/gerar_casos.py)
├── docs/                  manual_elegibilidade_v2.3.pdf
├── ingestao/              manual_chunks.py (PDF -> chunks)
├── notebooks/             01_setup_e_bronze, 02_silver, 03_gold,
│                          04_gabarito_divergencias, 05_manual_chunks
├── regras/                base, comum, consorcio, capitalizacao, registro
├── scripts/               gerar_manual, tools_ao_vivo, testar_llm, perguntar, listar_modelos,
│                          gerar_casos, verificar_env, verificar_repositorio, diagnosticar_token
├── terraform/             catalogo, schemas e volumes (versions, variables, main, outputs)
├── tests/                 test_regras, test_manual_chunks, test_tools,
│                          test_db_ambiente, test_agente, test_env, test_provedor,
│                          test_casos
├── Dockerfile, docker-compose.yml, requirements.txt, pytest.ini
└── .env.example, .gitignore, README.md, README_regras.md
```

---

## 9. Estado atual

> **Atenção:** esta seção descreve o que foi **entregue**, não necessariamente o que está na sua máquina.
> Rode `python scripts/verificar_repositorio.py` para conferir se a cópia local tem os arquivos e versões certos.

### Pronto e validado contra o workspace real
- Terraform aplicado: catálogo (criado na UI e **importado**), schemas e volumes.
- Notebooks 01 a 05 executados (bronze, silver, gold, gabarito de divergências, chunks do manual).
- Regras em Python com testes; manual em PDF; chunker do manual.
- As **7 tools** executadas contra o workspace real (`scripts/tools_ao_vivo.py`, sem erros).
- **O agente funciona com um modelo real** (Groq, `openai/gpt-oss-120b`). O passo `[2/3]` de `testar_llm.py`
  confirmou que o modelo pede tools. Na primeira pergunta ("Por que a venda VD000084 não entrou na carteira?") ele
  escolheu sozinho `get_venda`, `ler_codigo_regra` e `buscar_manual`, e concluiu corretamente que a exclusão
  (consórcio de **serviços**) vale no código **e** no manual. **Medido:** 6.292 tokens em 4 chamadas, 38,6 s no total.
- **Atenção:** essa venda é um caso de **controle** (código e manual concordam). O agente ainda **não foi testado**
  nos casos de divergência D1 a D4, que são os que provam o projeto.

### Pronto no código, ainda não executado contra o workspace real
- `agentes/casos.py` e `scripts/gerar_casos.py` (conjunto de 14 casos de avaliação: 4 divergências e 10 controles).
- Medição de tempo (modelo, tools e esperas) no agente e no `perguntar.py`.
- Todo o SQL novo foi validado só na **sintaxe** (parser do dialeto Databricks), não nos resultados.

### Testes automatizados
- **223 testes** (221 passam e 2 são pulados quando o SDK do Databricks não está instalado, como no Windows local).
  Distribuição: regras 35, chunks 9, tools 33, ambiente/db 37, agente 41, `.env` 20, provedor 15, casos 33.
- Validados com **mutação** (quebrar o código de propósito e ver o teste falhar). Isso já revelou furos reais nos
  próprios testes e nas minhas recomendações.

### Ainda não feito
- **Rodar o agente nos casos D1 a D4** e nos controles, e observar o comportamento.
- **Avaliação automática** (rodar todos os casos e pontuar), ajuste do prompt conforme o que a avaliação mostrar.
- Especialistas e orquestrador, auditor automático, busca semântica, Terraform de jobs e permissões, CI, aplicação
  Docker dos agentes.

---

## 10. Aonde queremos chegar

### Arquitetura alvo

```
Vendedor ── pergunta ──► Orquestrador (identifica venda/produto e roteia)
                              ├── Agente de Dados      get_venda, get_carteira_vendedor,
                              │                        get_producao, listar_vendas_fora_carteira
                              ├── Agente de Regras     listar_regras_aplicadas, ler_codigo_regra
                              │   (por produto: consórcio / capitalização)
                              ├── Agente de Manual     buscar_manual (RAG)
                              └── Agente Auditor       cruza dados x código x manual e acha divergências
```

**Princípio:** agentes **compartilhados por capacidade** (dados, manual) e **especializados por produto só
nas regras**. Adicionar um produto novo = um módulo de regras + um manual + uma extensão na silver + um
agente de regras, sem mexer no resto.

### Roteiro

| Fase | O que | Critério de pronto |
|---|---|---|
| **A** (concluída) | Validar o agente único com Groq e medir tokens reais | Feito: `gpt-oss-120b` pede tools; 6.292 tokens por pergunta |
| **B (agora)** | **Conjunto de avaliação** com gabarito: perguntas por caso plantado, por divergência (D1 a D4) e controles sem divergência | Métricas: acerto da regra, **detecção da divergência**, ausência de alucinação, tokens e tempo |
| **C** | Otimizar custo: descrições de tools mais curtas; possível **tool composta** (cadeia venda → código → manual em uma chamada) | Menos tokens por pergunta sem perder acerto |
| **D** | **Dividir em especialistas + orquestrador** (LangGraph) com rastreio (MLflow) | Mesmas métricas da fase B, com ganho de precisão |
| **E** | **Auditor** automático: corrigir D1 a D4 no código, reexecutar o gold e medir o efeito | Divergências encontradas e corrigidas; carteira recalculada |
| **F** | Plataforma: Terraform para **jobs** e **permissões** (agentes só leitura, sem acesso a `gabarito_*`), **CI** (`terraform plan` + `pytest`), aplicação dos agentes em Docker (API ou interface) | Deploy reproduzível |
| **G** (opcional) | Busca semântica (Vector Search, se disponível) e um terceiro produto para provar a extensibilidade | — |

---

## 11. Decisões tomadas e por quê

- **Regras em Python, não em SQL:** testáveis em milissegundos, legíveis pelos agentes, interface única
  entre produtos.
- **Código lido por `ast`, não importado:** o agente vê exatamente o que está no volume sem executar nada.
- **Chunks por regra, não por tamanho:** a busca devolve a regra exata, sem misturar outras.
- **Manual é a fonte da verdade:** em divergência, o manual prevalece.
- **Agente único antes de multiagente:** ver o ciclo funcionar sozinho antes de adicionar coordenação.
- **API compatível com a da OpenAI:** o provedor do modelo vira configuração.
- **Modelo aberto via Groq:** gratuito, mas com limites por minuto e por dia (ver seção 7).
- **Terraform só para a estrutura; tabelas nascem dos notebooks.**
- **`prevent_destroy` e `force_destroy = false`** no Terraform para proteger o catálogo.

---

## 12. Armadilhas já encontradas

- **Nomes de arquivo com `(1)` ou espaço** (`__init__ (1).py`, `__init__ .py`): o Python ignora e a pasta
  vira pacote vazio (`unknown location`). Conferir os nomes caractere por caractere.
- **Docker Desktop desligado:** erro `dockerDesktopLinuxEngine`. Abrir o Docker Desktop e esperar
  *Engine running*.
- **Comandos do container no PowerShell:** `find` e `databricks` só existem dentro do container.
- **Criar catálogo pela API (Terraform) falha** com *Default Storage*: criar na UI ou por SQL e
  `terraform import`. Usar `ignore_changes = [storage_root, properties]`.
- **`terraform apply` sem `plan`** quase destruiu o catálogo (`-/+ forces replacement`). Sempre
  `terraform plan -out=tfplan` e ler antes de aplicar.
- **`.env`:** reabrir o container depois de editar; host sem `//` a menos ou a mais; token sem aspas;
  ID do warehouse sem o caminho; **nunca** copiar o `.env.example` por cima do `.env`.
- **O Python não lê o `.env` sozinho.** No container o Docker Compose o injeta; no PowerShell, não. Por isso
  os scripts chamam `carregar_env()` (e o PowerShell precisa de `pip install -r requirements.txt`).
- **Linhas `NOME=` vazias no fim do `.env` anulam as anteriores** (vale a última). O `.env.example` antigo
  tinha duas assim; foi corrigido. Linha sem `=` ou com espaço no início também dá problema.
  Diagnóstico seguro (não mostra valores): `python scripts/verificar_env.py`.
- **Cópia do código no volume:** as tools e o gold leem `regras/` e `ingestao/` do volume `apoio.docs`.
  **Depois de alterar o código, reenviar**, senão o Databricks usa a versão antiga.
- **Free Edition:** sem endpoints com GPU; uso não comercial; modelos pay-per-token do Databricks podem
  não funcionar (não confirmado no meu workspace).
- **Modelo descontinuado (`404 model_not_found`):** os provedores aposentam modelos. Já aconteceu com o
  `llama-3.3-70b-versatile` no Groq (16/08/2026). Use `scripts/listar_modelos.py`; os scripts agora explicam o
  erro e listam os modelos disponíveis. Quando eu (o assistente) sugerir um modelo, **a recomendação pode estar
  desatualizada**: confirme na lista da sua chave.
- **Token vazado:** revogar na hora (Settings, Developer, Access tokens) e gerar outro.

---

## 13. Próximos passos imediatos

1. Aplicar o último pacote de atualização e **restaurar o `.env.example`** (está faltando na máquina local). Rodar
   `python scripts/verificar_repositorio.py` e `pytest` (esperado: 223 passed, ou 221 + 2 skipped sem o SDK).
2. Rodar `python scripts/gerar_casos.py`: grava `avaliacao/casos.json` com um exemplo real de cada caso e imprime
   o comando de pergunta pronto para cada um.
3. Perguntar ao agente os casos **D3 (moto)**, **D1**, **D2** e **D4**, e observar:
   - ele chama `buscar_manual` para a regra? Aponta a divergência com o manual?
   - em D1 e D2 a venda **entrou** na carteira: ele verifica se **deveria** ter entrado ou só diz que entrou?
     (o prompt atual foca em explicar exclusões; esta é uma hipótese a testar)
   - tokens, tempo e esperas (a linha `Tempo:` do `perguntar.py`).
4. Com o comportamento real em mãos, montar a **avaliação automática** (fase B) e ajustar o prompt.

---

## 14. Comandos úteis

```bash
# Abrir o container (PowerShell, na raiz do projeto; Docker Desktop ligado)
docker compose run --rm dev

# Testes
pytest                                  # esperado: 223 passed (ou 221 + 2 skipped sem o SDK)

# Terraform (dentro do container, em terraform/)
terraform plan -out=tfplan
terraform apply tfplan

# Enviar código e manual ao volume (dentro do container, na raiz)
find regras ingestao -name __pycache__ -exec rm -rf {} +
databricks fs cp --recursive regras dbfs:/Volumes/vendas_ia/apoio/docs/regras --overwrite
databricks fs cp --recursive ingestao dbfs:/Volumes/vendas_ia/apoio/docs/ingestao --overwrite
databricks fs cp docs/manual_elegibilidade_v2.3.pdf dbfs:/Volumes/vendas_ia/apoio/docs/manuais/ --overwrite

# Diagnóstico e uso
python scripts/tools_ao_vivo.py          # 7 tools contra o workspace real
python scripts/testar_llm.py            # testa o modelo sozinho (3 etapas)
python scripts/perguntar.py "Por que a venda VD000084 não entrou na carteira?"
```
