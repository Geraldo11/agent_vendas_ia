# Chat do agente de vendas

Interface web **local** para perguntar ao agente por que uma venda não entrou na carteira. Mostra, em
tempo real, o que o agente está fazendo e depois a resposta formatada, com tempo e tokens.

## Como subir

Na raiz do projeto (PowerShell; antes, uma vez: `pip install -r requirements.txt`):

```powershell
python scripts/servir_chat.py                  # agente real: Groq + Databricks (lê o .env)
python scripts/servir_chat.py --agente-falso   # demonstração: sem chaves, sem tokens, sem Databricks
```

Abra **http://127.0.0.1:8000**. Opções: `--porta 8080`, `--timeout 60` (segundos por pergunta) e
`--passos 10` (máximo de passos do agente). Ctrl+C para parar.

Antes de subir no modo real, o script confere o `.env` (Databricks e modelo). Se algo estiver errado,
ele **não sobe** e explica o problema. Para conferir o `.env` sem mostrar valores, use
`python scripts/verificar_env.py`.

### No Docker (opcional)

```powershell
docker compose build                 # obrigatório depois de mudar o requirements.txt
docker compose up chat               # agente real
docker compose run --rm --service-ports chat python scripts/servir_chat.py --host 0.0.0.0 --aceitar-rede --agente-falso
```

Dentro do container o servidor escuta em `0.0.0.0` (senão o Docker não consegue entregar as conexões),
mas a porta é publicada **só em 127.0.0.1** (`"127.0.0.1:8000:8000"`). Se mudar a porta, ela precisa ser
a mesma dos dois lados (`--porta` e `ports`), porque o servidor confere o cabeçalho `Host`.

## Como funciona

```
navegador ──POST /api/perguntar──► servidor (FastAPI) ──thread──► agente (executar_agente)
          ◄── uma linha JSON por evento ──  fila  ◄── ao_evento(...) ──┘
```

| Arquivo | Papel |
|---|---|
| `app.py` | Rotas, trava de uma pergunta por vez, thread do agente, fila e fluxo de eventos (NDJSON) |
| `erros.py` | Transforma exceções em mensagens seguras em português; tira segredos das mensagens e do log |
| `seguranca.py` | CSP e cabeçalhos em toda resposta; confere `Host` e `Origin` |
| `demo.py` | Modo demonstração: o agente **real** com modelo e tools falsos (cenários abaixo) |
| `static/index.html`, `estilo.css`, `app.js` | A interface, sem framework, sem build e sem nada externo |

**Rotas:** `GET /` (a página), `GET /api/saude` (`{ok, modo, provedor, modelo, ocupado}`, sem segredos),
`POST /api/perguntar` (`{"pergunta": "..."}` → fluxo de eventos) e `POST /api/parar` (botão Parar).

**Eventos** (um JSON por linha): `modelo_inicio`, `tool_inicio`, `tool_fim`, `espera` e, no fim,
**exatamente um** destes: `fim` (resposta e métricas), `erro` (`tipo` + `mensagem`) ou `cancelado`.
Os tipos de erro são `limite_de_uso`, `provedor`, `configuracao`, `tempo_esgotado` e `interno`.

**Por que NDJSON e não SSE:** o navegador lê com `fetch` (o `EventSource` só faz GET). Lendo com `fetch`,
o SSE não traz vantagem, e uma linha JSON por evento é mais simples de ler dos dois lados.

## Limitações conhecidas (versão 1)

- **Uma pergunta por vez.** O plano gratuito do Groq tem limite por minuto; uma segunda pergunta durante
  a primeira recebe 409.
- **Sem memória.** Cada pergunta é independente (a interface avisa).
- **Parar e timeout agem entre etapas.** Uma chamada ao modelo ou uma consulta ao warehouse que já está em
  andamento vai até o fim; só então o agente para. A espera por limite de uso (429) é interrompida na hora.
  Enquanto a etapa atual não termina, o servidor continua "ocupado" (409), de propósito: assim nunca há
  duas perguntas gastando tokens ao mesmo tempo.
- **Se o navegador fechar no meio,** o servidor pede ao agente para parar (no mesmo ritmo acima).

## Segurança

- **Sem autenticação.** Serve só para uso local, em `127.0.0.1`. **Expor o servidor na rede exigiria
  autenticação** (e HTTPS): qualquer pessoa que o alcançasse gastaria os seus tokens e leria os seus
  dados. Por isso `servir_chat.py` recusa `--host` diferente de 127.0.0.1 sem `--aceitar-rede`, uma flag
  feita para o container.
- **Outras páginas abertas no navegador** não conseguem usar o chat. O servidor recusa `Origin` de outro
  site, exige `Content-Type: application/json` (o que força uma checagem prévia do CORS, que recusamos) e
  confere o `Host`, o que barra o ataque de *DNS rebinding*.
- **O texto do modelo não é confiável.** O `app.js` monta a resposta só com `createElement` e
  `textContent`; nada é interpretado como HTML, e não gera links. A CSP (`script-src 'self'`) impede scripts
  e estilos inline.
- **Segredos:** nenhuma rota devolve o `.env`. As mensagens de erro e o log passam por um filtro que troca
  por `***` os valores de variáveis terminadas em `KEY`, `TOKEN` ou `SECRET`.

## Modo demonstração: cenários

Clique nos cenários que aparecem na tela inicial, ou comece a pergunta com a marca:

| Marca | O que simula |
|---|---|
| `[demo:normal]` (ou sem marca) | Consulta a venda, lê o código e o manual e responde com tabela e chips |
| `[demo:espera]` | O "provedor" pede 8 s de espera (429): contagem regressiva |
| `[demo:lento]` | Consultas de ~4 s: para testar o **Parar** (ou o `--timeout 10`) |
| `[demo:limite]` | Limite diário esgotado: erro `limite_de_uso` |
| `[demo:configuracao]` | Chave recusada (HTTP 401): erro `configuracao` |
| `[demo:provedor]` | Provedor fora do ar (HTTP 503): erro `provedor` |
| `[demo:interno]` | Falha inesperada: erro `interno` (o detalhe vai só para o log) |
| `[demo:xss]` | Argumentos e resposta com conteúdo malicioso, que devem aparecer como texto |

## Checklist manual do front-end

Não há Node nesta máquina, então a renderização não roda no `pytest`. Os testes automáticos varrem o
texto do `app.js` e do `index.html` em busca de APIs perigosas e de conteúdo inline. Para o resto, suba
`python scripts/servir_chat.py --agente-falso` e confira:

1. [ ] **XSS** (`[demo:xss]`): aparecem como **texto**, e nada executa (nenhum alerta):
   `<img src=x onerror=alert(1)>`, `<script>alert(1)</script>`, `[x](javascript:alert(1))` (sem link
   clicável) e `**<b>**` (a palavra `<b>` em negrito). As etapas também mostram o payload como texto.
2. [ ] **Tempo real** (`[demo:normal]`): as etapas aparecem uma a uma, com ícone girando e depois ✓, e a
   duração de cada consulta; o painel "Como cheguei nisso" fica aberto e se recolhe no fim.
3. [ ] **Espera** (`[demo:espera]`): a contagem regressiva de 9 s anda de 1 em 1 segundo e a pergunta continua.
4. [ ] **Parar** (`[demo:lento]`): o botão vira "Parar" (vermelho), depois "Parando…"; termina com
   "Pergunta interrompida" e o botão "Perguntar de novo".
5. [ ] **409:** com uma pergunta lenta em andamento, abra outra aba e pergunte: aparece "Já existe uma
   pergunta em andamento".
6. [ ] **Erros** (`[demo:limite]`, `configuracao`, `provedor`, `interno`): título e mensagem amigáveis,
   sem traceback nem caminhos, e "Tentar de novo" reenvia a mesma pergunta.
7. [ ] **Teclado:** Enter envia; Shift+Enter quebra linha; Tab percorre tudo com o foco visível.
8. [ ] **Contador:** chega a 1000/1000 e não deixa digitar mais (fica destacado perto do limite).
9. [ ] **Celular:** com a janela em 360 px de largura (F12, modo dispositivo), nada fica cortado e as
   tabelas rolam na horizontal.
10. [ ] **Tema escuro:** com o Windows em modo escuro, a página fica escura e legível.
11. [ ] **Faixa:** "MODO DEMONSTRAÇÃO" aparece no topo só com `--agente-falso`.
12. [ ] **Console (F12):** nenhum erro de CSP ("Refused to...").

Já conferido com o Edge *headless* (automatizado, fora do pytest): os itens 1 e 2, a formatação
(tabela, citação, código, chips), a exibição de um erro e a execução do `app.js` sob a CSP real.
