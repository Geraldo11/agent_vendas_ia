# Tarefa: front-end de chat para o agente de vendas

## 1. Papel e contexto

Você está no projeto `agentes-vendas-ia`. O `CLAUDE.md` já foi carregado: **siga-o** (português do Brasil,
professor paciente, plano antes de mudanças grandes, nunca ler o `.env`, não rodar `terraform apply`, `git push`
nem `databricks fs cp --overwrite` sem minha confirmação, não corrigir as divergências D1 a D4).

**Estado:** existe um agente que responde "por que a venda X não entrou na carteira?". Ele usa 7 tools sobre o
Databricks e um modelo aberto no Groq (`openai/gpt-oss-120b`). Hoje só funciona pela linha de comando
(`python scripts/perguntar.py "..."`). A suíte tem **223 testes** (221 passam e 2 são pulados sem o `databricks-sdk`).

## 2. Objetivo

Uma **interface de chat web local**. O usuário digita uma pergunta e vê, em tempo real, **o que o agente está
fazendo**, e depois a **resposta formatada** com as métricas (tempo e tokens).

Exemplo de pergunta: "Por que a venda VD000084 não entrou na carteira?"

## 3. Leia antes de planejar (nesta ordem)

1. `CLAUDE.md` e `docs/CONTEXTO_DO_PROJETO.md` (seções 7, 9 e 12)
2. `agentes/agente.py`: o laço, `ResultadoDoAgente`, `LimiteDeUsoAtingido`, `_chamar_modelo` e o parâmetro `dormir`
3. `agentes/llm.py`: `configuracao_do_llm`, `criar_cliente`, `explicar_erro_do_provedor`
4. `agentes/ambiente.py` (`carregar_env`) e `scripts/perguntar.py` (exemplo completo de uso do agente)
5. `agentes/tools/__init__.py` (a lista `TOOLS`), `tests/test_agente.py` (estilo de teste com modelo falso) e
   `scripts/verificar_repositorio.py`

**Não leia** o `.env` nem `avaliacao/casos.json` (é o gabarito do projeto).

## 4. Restrições do mundo real (definem o desenho; não são óbvias)

1. **Segredos.** O token do Databricks e a chave do Groq vivem no servidor (`.env`). O navegador nunca pode vê-los.
   Logo, **um HTML sozinho não resolve**: é preciso um backend.
2. **Latência.** Uma pergunta real levou **~38 s** (4 chamadas ao modelo e 3 consultas ao warehouse). A interface
   precisa **mostrar o progresso**, não uma tela de "carregando" muda.
3. **Limite do provedor.** Groq grátis: 8.000 tokens/min e ~200 mil/dia. Uma pergunta gasta ~6.300 tokens. Logo:
   **uma pergunta por vez**. O agente pode **dormir** (erro 429) por até ~90 s; a interface deve mostrar isso como
   "aguardando limite de uso do provedor", nunca como travamento.
4. **O agente é síncrono e bloqueante** e só devolve o resultado no fim. Para mostrar progresso é preciso
   **emitir eventos durante o laço**.
5. **Cada pergunta é independente** (o agente não tem memória entre perguntas). Diga isso na interface (versão 1).

## 5. Decisões já tomadas (não as reabra sem um bom motivo; se discordar, explique antes)

- **Backend:** Python, FastAPI e uvicorn, em uma pasta nova `chat/`. Para os testes, `httpx` (cliente de teste do
  Starlette). Adicione as dependências ao `requirements.txt`.
- **Streaming:** o navegador chama `POST /api/perguntar` com `fetch` e lê a resposta como fluxo (`ReadableStream`).
  O `EventSource` **não serve**, pois só suporta GET. Formato: SSE (`data: {json}\n\n`) ou NDJSON; escolha um e
  justifique.
- **Front-end:** **três arquivos estáticos** em `chat/static/` (`index.html`, `estilo.css`, `app.js`). Sem
  framework, sem build, sem CDN, sem fontes externas. Eles são separados de propósito: com o JavaScript em arquivo
  próprio é possível uma política de segurança (CSP) estrita, sem `unsafe-inline`.
- **Mesma origem:** o backend serve o front-end (sem CORS).
- **Rede:** escutar **somente em 127.0.0.1**.

## 6. Backend: requisitos

1. **Eventos no agente, com mudança mínima e retrocompatível.** Em `executar_agente`, acrescente um parâmetro
   opcional `ao_evento: Optional[Callable[[dict], None]] = None` (e, se for simples, `deve_parar() -> bool`
   verificado entre os passos). Nada pode mudar para quem não o usa. Eventos (campos mínimos):
   - `modelo_inicio` (número da chamada)
   - `tool_inicio` (tool, argumentos)
   - `tool_fim` (tool, segundos, erro: bool)
   - `espera` (segundos, motivo): emitido quando o tratamento do 429 vai dormir (use o wrapper de `dormir`)
   - `fim` (resposta e métricas: chamadas, tokens de entrada e saída, segundos no modelo, nas tools e em espera,
     `parou_por_limite`)
   - `erro` (mensagem **segura** em português e tipo: `limite_de_uso`, `provedor`, `configuracao` ou `interno`)
2. **Endpoints:**
   - `GET /`: o HTML
   - `GET /api/saude`: `{ok, provedor, modelo}`. **Nunca** devolve chaves nem valores do `.env`
   - `POST /api/perguntar` com `{"pergunta": "..."}`: devolve o fluxo de eventos
3. **Concorrência:** uma pergunta por vez (trava). Se estiver ocupado, responda **409** com mensagem clara.
4. **Validação:** pergunta de 1 a 1.000 caracteres (após `strip`); rejeitar vazia; **timeout total de 180 s** com
   evento `erro`.
5. **Reaproveite** `carregar_env`, `configuracao_do_llm`, `criar_cliente`, `TOOLS`, `explicar_erro_do_provedor` e
   `LimiteDeUsoAtingido`. A função que cria a aplicação deve receber o "executor do agente" por **injeção de
   dependência**, como as tools fazem com `executor=`, para os testes usarem um agente falso. O agente é síncrono:
   rode-o em uma thread e entregue os eventos por uma fila ao gerador do fluxo.
6. **Erros:** nunca devolver traceback, caminhos do servidor nem valores do `.env`. Mapeie as exceções para
   mensagens em português. O detalhe técnico vai só para o log do servidor (também sem segredos).
7. **Cliente desconectado:** pare de enviar. Documente o que acontece com a pergunta em andamento (limitação
   conhecida) ou, se for simples, cancele entre os passos.
8. **`scripts/servir_chat.py`:** sobe o servidor (padrão `127.0.0.1:8000`, ajustável por argumentos). **Antes de
   subir**, valida o `.env` (`validar_ambiente` e `configuracao_do_llm`) e falha cedo com mensagem clara.
9. **Docker:** serviço opcional no `docker-compose.yml`. Dentro do container o servidor precisa escutar em
   `0.0.0.0`, **mas a porta deve ser publicada só em `127.0.0.1`** (`"127.0.0.1:8000:8000"`). Lembre-me de que
   mudar o `requirements.txt` exige `docker compose build`.

## 7. Front-end: requisitos

- **Layout de chat:** bolhas do usuário e do assistente, rolagem automática, caixa de texto (Enter envia,
  Shift+Enter quebra linha), botão Enviar que vira **Parar** durante a pergunta, envio desabilitado enquanto
  houver pergunta em andamento, contador de caracteres (limite 1.000).
- **Painel "Como cheguei nisso"** em cada resposta: recolhível e **aberto durante o processamento**. Mostra as
  etapas em tempo real com ícone de estado (em andamento, concluída, erro), a duração de cada tool e, na espera
  por limite de uso, uma **contagem regressiva**. Use rótulos amigáveis, com o nome técnico como fallback:

  | Tool | Rótulo |
  |---|---|
  | `get_venda` | Consultando a venda {id_venda} |
  | `get_carteira_vendedor` | Consultando a carteira de {id_vendedor} |
  | `get_producao` | Consultando a produção de {id_vendedor} |
  | `listar_vendas_fora_carteira` | Listando as vendas de {id_vendedor} que ficaram fora da carteira |
  | `listar_regras_aplicadas` | Listando as regras aplicadas ({produto}) |
  | `ler_codigo_regra` | Lendo o código da regra {regra_id} |
  | `buscar_manual` | Consultando o manual ({regra_id ou consulta}) |

- **Resposta final:** renderização segura de um Markdown mínimo (negrito, itálico, código, listas, citações e
  quebras de linha). **Escape o HTML primeiro, depois formate.** Nunca use `innerHTML` com texto não escapado.
  **Não gere links** a partir de Markdown. Destaque os IDs de regra (`COM-01`, `CONS-02`, `CAP-03`...) como "chips".
- **Rodapé da resposta:** tempo (modelo, tools e espera) e tokens (entrada e saída).
- **Estado vazio:** exemplos clicáveis **estáticos** (por exemplo, "Por que a venda VD______ não entrou na
  carteira?", que o usuário completa). Não leia `avaliacao/casos.json`.
- **Aviso fixo:** "Cada pergunta é independente: o assistente não lembra das anteriores."
- **Erros:** mensagens amigáveis e botão **"Tentar de novo"** (reenvia a última pergunta).
- **Acessibilidade e celular:** funciona a partir de 360 px; foco visível; contraste adequado;
  `aria-live="polite"` na área de mensagens; tema claro e escuro por `prefers-color-scheme`. Textos em português
  do Brasil.

## 8. Segurança (obrigatório)

1. **XSS.** O texto do modelo é **não confiável**. Payloads que devem aparecer como texto, sem executar:
   `<img src=x onerror=alert(1)>`, `<script>alert(1)</script>`, `[x](javascript:alert(1))`, `**<b>**`.
2. **Cabeçalhos em todas as respostas:** `Content-Security-Policy: default-src 'none'; script-src 'self';
   style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none';
   frame-ancestors 'none'`, além de `X-Content-Type-Options: nosniff` e `Referrer-Policy: no-referrer`.
   **Consequência para o código:** com `style-src 'self'` não use atributos `style="..."` no HTML nem
   `setAttribute('style', ...)`; use classes CSS (e, se precisar, a propriedade `element.style.x`, que é permitida).
3. **Proteção contra páginas de terceiros chamando o servidor local** (outro site no meu navegador disparando
   perguntas e gastando meus tokens): `POST /api/perguntar` exige `Content-Type: application/json`, **rejeita**
   requisições cujo `Origin` (quando presente) não seja o do próprio servidor e **valida o cabeçalho `Host`**
   (`127.0.0.1` ou `localhost` com a porta configurada).
4. **Segredos:** nenhuma rota devolve variáveis de ambiente, o `.env`, traceback ou caminhos do servidor.
5. **Sem autenticação nesta versão** (uso local). Documente em `chat/README.md` que expor o servidor em rede
   exigiria autenticação.

## 9. Testes (obrigatório)

- **Mantenha a suíte atual verde** (223; 221 e 2 puladas sem o SDK).
- **Eventos do agente:** ordem, conteúdo e não regressão (sem `ao_evento` tudo se comporta como antes).
- **API com agente falso:** fluxo de eventos na ordem; validação (vazia, longa demais, JSON inválido); **409** com
  pergunta em andamento; timeout; mapeamento de erros **sem vazamento** (inclua um teste de que a mensagem de erro
  nunca contém o valor de `GROQ_API_KEY`); cabeçalhos de segurança; `Origin` e `Host` inválidos rejeitados;
  `/api/saude` sem segredos.
- **Mutação:** valide pelo menos **três proteções críticas** quebrando o código de propósito e confirmando que o
  teste falha (por exemplo, a trava de uma pergunta por vez, o filtro de `Origin` e o vazamento de segredo).
- **Front-end:** se houver Node instalado, teste a função de renderização com os payloads de XSS. Se não houver,
  escreva um **checklist manual** em `chat/README.md`.
- **Atualize** `scripts/verificar_repositorio.py` (arquivos novos e marcadores), a contagem de testes no
  `CLAUDE.md` e no `docs/CONTEXTO_DO_PROJETO.md`.

## 10. Etapas (faça commits pequenos em uma branch `frontend-chat`; **não faça push**)

- **Etapa 0: plano.** Liste os arquivos que criará e alterará, as dependências novas, os riscos e qualquer
  discordância com as decisões da seção 5. **PARE e espere meu OK.**
- **Etapa 1:** eventos no agente, com testes.
- **Etapa 2:** backend e API, com testes. **PARE** para eu revisar e rodar.
- **Etapa 3:** front-end estático.
- **Etapa 4:** integração: `scripts/servir_chat.py`, Docker e `chat/README.md`.
- **Etapa 5: verificação final.** Rode `pytest` e `python scripts/verificar_repositorio.py`. Depois conduza um
  roteiro manual comigo: subir o servidor, perguntar um caso de controle e um de divergência, e observar uma espera
  por limite de uso. Se você não conseguir rodar comandos, peça que eu os rode e cole a saída.

## 11. Fora de escopo

Login e autenticação, banco de dados ou histórico persistente, multiusuário, deploy em nuvem, upload de arquivos,
voz, **memória entre perguntas** (possível depois, com histórico curto), reescrever o agente, mudar regras de
negócio, corrigir D1 a D4.

## 12. Critérios de aceite

1. `python scripts/servir_chat.py` sobe o servidor e `http://127.0.0.1:8000` mostra o chat.
2. Uma pergunta real exibe as etapas **em tempo real** e depois a resposta formatada, com tempo e tokens.
3. Uma espera por limite de uso aparece como contagem regressiva, não como travamento.
4. Os payloads de XSS da seção 8 aparecem como texto e **não executam**.
5. Uma segunda pergunta enviada durante a primeira é recusada com mensagem clara (409).
6. Nenhuma resposta, log ou arquivo expõe segredos. O `.env` não foi lido por você.
7. `pytest` verde, com testes novos; `verificar_repositorio.py` aprovado; documentação atualizada.
8. Eu consigo explicar com minhas palavras o que cada arquivo novo faz, porque você me ensinou.

## 13. Como me explicar o trabalho

Como diz o `CLAUDE.md`: explique **cada arquivo** criado ou alterado e o **porquê** das decisões, com exemplos.
Ao fim de cada etapa, diga **o que foi testado e o que não foi**. Se perceber um erro seu anterior, diga na hora.
