// Chat do agente de vendas.
//
// SEGURANÇA: o texto do modelo e os argumentos das tools NÃO são confiáveis. Todo conteúdo entra na
// página por textContent / createTextNode e elementos criados com createElement. Nenhum texto é
// interpretado como HTML em lugar nenhum deste arquivo. Links nunca são gerados a partir do Markdown.
"use strict";

(() => {
  const LIMITE_DE_CARACTERES = 1000;
  const TIPOS_TERMINAIS = new Set(["fim", "erro", "cancelado"]);

  // ------------------------------------------------------------------ elementos da página
  const $ = (id) => document.getElementById(id);
  const conversa = $("conversa");
  const vazio = $("vazio");
  const formulario = $("formulario");
  const campo = $("pergunta");
  const contador = $("contador");
  const botao = $("enviar");
  const status = $("status");

  let emAndamento = false;
  let parando = false;
  let ultimaPergunta = "";
  let controlador = null;          // AbortController da pergunta atual
  const botoesTentarDeNovo = [];

  // ------------------------------------------------------------------ utilidades
  function el(tag, classe, texto) {
    const e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined && texto !== null) e.textContent = String(texto);
    return e;
  }

  const numero = new Intl.NumberFormat("pt-BR");
  const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const segundos = (s) => `${decimal.format(Number(s) || 0)} s`;

  function pertoDoFim() {
    return conversa.scrollHeight - conversa.scrollTop - conversa.clientHeight < 160;
  }

  function rolarParaOFim(forcar) {
    if (forcar || pertoDoFim()) conversa.scrollTop = conversa.scrollHeight;
  }

  // ------------------------------------------------------------------ rótulos das tools
  function valor(argumentos, ...nomes) {
    if (!argumentos || typeof argumentos !== "object") return null;
    for (const nome of nomes) {
      const v = argumentos[nome];
      if (v !== undefined && v !== null && String(v).trim() !== "") {
        const texto = String(v).trim();
        return texto.length > 60 ? `${texto.slice(0, 60)}…` : texto;
      }
    }
    return null;
  }

  const ROTULOS = {
    get_venda: (a) => valor(a, "id_venda") && `Consultando a venda ${valor(a, "id_venda")}`,
    get_carteira_vendedor: (a) => valor(a, "id_vendedor") && `Consultando a carteira de ${valor(a, "id_vendedor")}`,
    get_producao: (a) => valor(a, "id_vendedor") && `Consultando a produção de ${valor(a, "id_vendedor")}`,
    listar_vendas_fora_carteira: (a) => valor(a, "id_vendedor") &&
      `Listando as vendas de ${valor(a, "id_vendedor")} que ficaram fora da carteira`,
    listar_regras_aplicadas: (a) => valor(a, "produto") && `Listando as regras aplicadas (${valor(a, "produto")})`,
    ler_codigo_regra: (a) => valor(a, "regra_id") && `Lendo o código da regra ${valor(a, "regra_id")}`,
    buscar_manual: (a) => valor(a, "regra_id", "consulta") &&
      `Consultando o manual (${valor(a, "regra_id", "consulta")})`,
  };

  function rotuloDaTool(tool, argumentos) {
    const nome = typeof tool === "string" ? tool : "?";
    const montar = Object.prototype.hasOwnProperty.call(ROTULOS, nome) ? ROTULOS[nome] : null;
    const rotulo = montar ? montar(argumentos) : null;
    return rotulo || `Executando a ferramenta ${nome}`;
  }

  // ------------------------------------------------------------------ Markdown mínimo e seguro
  // Suporta: parágrafos, quebras de linha, **negrito**, *itálico*, `código`, blocos ```, listas,
  // citações (>), títulos (#, mostrados como negrito) e tabelas simples. IDs de regra viram "chips".
  const RE_CHIP = /\b(?:COM|CONS|CAP)-\d{2}\b/g;
  const RE_INLINE = /`([^`\n]+)`|\*\*(\S(?:.*?\S)?)\*\*|__(\S(?:.*?\S)?)__|\*(\S(?:.*?\S)?)\*|(?<![\p{L}\p{N}_])_(\S(?:.*?\S)?)_(?![\p{L}\p{N}_])/gu;
  const RE_ITEM = /^\s*(?:[-*+]|\d{1,3}[.)])\s+/;
  const RE_CERCA = /^\s*```/;
  const RE_CITACAO = /^\s*>/;
  const RE_TITULO = /^\s{0,3}#{1,6}\s+/;
  const RE_LINHA_DE_TABELA = /^\s*\|.*\|\s*$/;
  const RE_SEPARADOR_DE_TABELA = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

  function adicionarTextoComChips(pai, texto) {
    let ultimo = 0;
    for (const m of texto.matchAll(RE_CHIP)) {
      if (m.index > ultimo) pai.appendChild(document.createTextNode(texto.slice(ultimo, m.index)));
      pai.appendChild(el("span", "chip", m[0]));
      ultimo = m.index + m[0].length;
    }
    if (ultimo < texto.length) pai.appendChild(document.createTextNode(texto.slice(ultimo)));
  }

  function renderizarInline(pai, texto) {
    const re = new RegExp(RE_INLINE.source, RE_INLINE.flags);
    let ultimo = 0;
    let m;
    while ((m = re.exec(texto)) !== null) {
      if (m.index > ultimo) adicionarTextoComChips(pai, texto.slice(ultimo, m.index));
      if (m[1] !== undefined) {
        pai.appendChild(el("code", null, m[1]));
      } else if (m[2] !== undefined || m[3] !== undefined) {
        const forte = el("strong");
        renderizarInline(forte, m[2] !== undefined ? m[2] : m[3]);
        pai.appendChild(forte);
      } else {
        const enfase = el("em");
        renderizarInline(enfase, m[4] !== undefined ? m[4] : m[5]);
        pai.appendChild(enfase);
      }
      ultimo = re.lastIndex;
    }
    if (ultimo < texto.length) adicionarTextoComChips(pai, texto.slice(ultimo));
  }

  function tipoDeLista(linha) {
    if (/^\s*[-*+]\s+/.test(linha)) return "ul";
    if (/^\s*\d{1,3}[.)]\s+/.test(linha)) return "ol";
    return null;
  }

  function inicioDeTabela(linhas, i) {
    return RE_LINHA_DE_TABELA.test(linhas[i]) && i + 1 < linhas.length && RE_SEPARADOR_DE_TABELA.test(linhas[i + 1]);
  }

  function inicioDeBloco(linhas, i) {
    const linha = linhas[i];
    return RE_CERCA.test(linha) || RE_CITACAO.test(linha) || tipoDeLista(linha) !== null ||
      RE_TITULO.test(linha) || inicioDeTabela(linhas, i);
  }

  function celulas(linha) {
    return linha.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  }

  function renderizarMarkdown(texto) {
    const fragmento = document.createDocumentFragment();
    const linhas = String(texto === undefined || texto === null ? "" : texto).replace(/\r\n?/g, "\n").split("\n");
    let i = 0;
    while (i < linhas.length) {
      const linha = linhas[i];

      if (!linha.trim()) { i += 1; continue; }

      if (RE_CERCA.test(linha)) {
        const codigo = [];
        i += 1;
        while (i < linhas.length && !RE_CERCA.test(linhas[i])) { codigo.push(linhas[i]); i += 1; }
        i += 1;                                         // pula a cerca de fechamento
        const pre = el("pre");
        pre.appendChild(el("code", null, codigo.join("\n")));
        fragmento.appendChild(pre);
        continue;
      }

      if (RE_CITACAO.test(linha)) {
        const citadas = [];
        while (i < linhas.length && RE_CITACAO.test(linhas[i])) {
          citadas.push(linhas[i].replace(/^\s*>\s?/, ""));
          i += 1;
        }
        const citacao = el("blockquote");
        citacao.appendChild(renderizarMarkdown(citadas.join("\n")));
        fragmento.appendChild(citacao);
        continue;
      }

      const lista = tipoDeLista(linha);
      if (lista) {
        const elementoDaLista = el(lista);
        while (i < linhas.length && tipoDeLista(linhas[i]) === lista) {
          const item = el("li");
          renderizarInline(item, linhas[i].replace(RE_ITEM, ""));
          elementoDaLista.appendChild(item);
          i += 1;
        }
        fragmento.appendChild(elementoDaLista);
        continue;
      }

      if (RE_TITULO.test(linha)) {
        const titulo = el("p");
        const forte = el("strong");
        renderizarInline(forte, linha.replace(RE_TITULO, ""));
        titulo.appendChild(forte);
        fragmento.appendChild(titulo);
        i += 1;
        continue;
      }

      if (inicioDeTabela(linhas, i)) {
        const tabela = el("table");
        const cabecalho = el("tr");
        for (const c of celulas(linha)) {
          const th = el("th");
          renderizarInline(th, c);
          cabecalho.appendChild(th);
        }
        const thead = el("thead");
        thead.appendChild(cabecalho);
        tabela.appendChild(thead);
        const tbody = el("tbody");
        i += 2;
        while (i < linhas.length && RE_LINHA_DE_TABELA.test(linhas[i])) {
          const tr = el("tr");
          for (const c of celulas(linhas[i])) {
            const td = el("td");
            renderizarInline(td, c);
            tr.appendChild(td);
          }
          tbody.appendChild(tr);
          i += 1;
        }
        tabela.appendChild(tbody);
        const rolavel = el("div", "tabela-rolavel");
        rolavel.appendChild(tabela);
        fragmento.appendChild(rolavel);
        continue;
      }

      // Parágrafo: linhas seguidas até uma linha vazia ou o início de outro bloco.
      const paragrafo = el("p");
      let primeira = true;
      do {
        if (!primeira) paragrafo.appendChild(el("br"));
        renderizarInline(paragrafo, linhas[i]);
        primeira = false;
        i += 1;
      } while (i < linhas.length && linhas[i].trim() && !inicioDeBloco(linhas, i));
      fragmento.appendChild(paragrafo);
    }
    return fragmento;
  }

  // ------------------------------------------------------------------ uma resposta do assistente
  const TITULOS_DE_ERRO = {
    limite_de_uso: "Limite de uso do provedor atingido",
    provedor: "O provedor do modelo teve um problema",
    configuracao: "Problema de configuração",
    tempo_esgotado: "A pergunta demorou demais",
    interno: "Erro interno",
    ocupado: "Já existe uma pergunta em andamento",
    validacao: "Pergunta não aceita",
    recusado: "Pedido recusado pelo servidor",
    rede: "Sem conexão com o servidor",
    conexao: "Conexão encerrada inesperadamente",
  };

  class Resposta {
    constructor() {
      this.bolha = el("article", "mensagem assistente");
      this.bolha.setAttribute("aria-busy", "true");
      this.painel = el("details", "etapas");
      this.painel.open = true;                      // aberto durante o processamento
      this.resumo = el("summary", null, "Como cheguei nisso");
      this.painel.appendChild(this.resumo);
      this.lista = el("ol", "lista-etapas");
      this.painel.appendChild(this.lista);
      this.corpo = el("div", "corpo");
      this.bolha.append(this.painel, this.corpo);
      this.pendentes = [];                           // etapas de modelo/espera ainda abertas
      this.tools = new Map();                        // indice -> etapa da tool
      this.relogio = null;
      this.etapas = 0;
      conversa.appendChild(this.bolha);
      rolarParaOFim(true);
    }

    novaEtapa(rotulo, classeExtra) {
      const item = el("li", `etapa andamento${classeExtra ? ` ${classeExtra}` : ""}`);
      const icone = el("span", "icone");
      icone.setAttribute("aria-hidden", "true");
      const texto = el("span", "texto", rotulo);
      const duracao = el("span", "duracao");
      const estado = el("span", "visualmente-oculto", "(em andamento)");
      item.append(icone, texto, duracao, estado);
      item.partes = { texto, duracao, estado };
      this.lista.appendChild(item);
      this.etapas += 1;
      rolarParaOFim();
      return item;
    }

    marcar(item, situacao) {
      const rotulos = { concluida: "(concluída)", "com-erro": "(com erro)", interrompida: "(interrompida)" };
      item.classList.remove("andamento");
      item.classList.add(situacao);
      item.partes.estado.textContent = rotulos[situacao] || "";
    }

    fecharPendentes(situacao) {
      this.pararRelogio();
      for (const item of this.pendentes) this.marcar(item, situacao);
      this.pendentes = [];
    }

    pararRelogio() {
      if (this.relogio !== null) { clearInterval(this.relogio); this.relogio = null; }
    }

    modelo(chamada) {
      this.fecharPendentes("concluida");
      const n = Number(chamada) || 1;
      const rotulo = n === 1 ? "Analisando a pergunta" : `Analisando os resultados (chamada ${n} ao modelo)`;
      this.pendentes.push(this.novaEtapa(rotulo));
    }

    toolInicio(evento) {
      this.fecharPendentes("concluida");
      this.tools.set(evento.indice, this.novaEtapa(rotuloDaTool(evento.tool, evento.argumentos)));
    }

    toolFim(evento) {
      const item = this.tools.get(evento.indice);
      if (!item) return;
      this.marcar(item, evento.erro ? "com-erro" : "concluida");
      item.partes.duracao.textContent = segundos(evento.segundos);
      if (evento.erro) item.partes.texto.textContent += " (a ferramenta devolveu um erro; o assistente foi avisado)";
    }

    espera(total) {
      // A espera acontece DENTRO da chamada ao modelo (ele tenta de novo depois): a etapa do modelo
      // continua aberta; só uma espera anterior, se houver, é encerrada.
      this.pararRelogio();
      this.pendentes = this.pendentes.filter((item) => {
        if (!item.classList.contains("espera")) return true;
        this.marcar(item, "concluida");
        return false;
      });
      const item = this.novaEtapa("", "espera");
      this.pendentes.push(item);
      let restante = Math.max(0, Math.ceil(Number(total) || 0));
      const atualizar = () => {
        item.partes.texto.textContent = restante > 0
          ? `Aguardando o limite de uso do provedor: ${restante} s`
          : "Aguardando o limite de uso do provedor: retomando…";
      };
      atualizar();
      this.relogio = setInterval(() => {
        restante = Math.max(0, restante - 1);
        atualizar();
        if (restante === 0) this.pararRelogio();
      }, 1000);
    }

    encerrarPainel() {
      this.bolha.setAttribute("aria-busy", "false");
      this.resumo.textContent = `Como cheguei nisso (${this.etapas} ${this.etapas === 1 ? "etapa" : "etapas"})`;
    }

    fim(evento) {
      this.fecharPendentes("concluida");
      this.corpo.appendChild(renderizarMarkdown(evento.resposta));
      const m = evento.metricas || {};
      const rodape = el("div", "metricas");
      rodape.append(
        el("span", null, `Tempo: modelo ${segundos(m.segundos_no_modelo)} · ferramentas ${segundos(m.segundos_nas_tools)}` +
          ` · espera ${segundos(m.segundos_em_espera)}`),
        el("span", null, `Tokens: ${numero.format(m.tokens_entrada || 0)} de entrada + ` +
          `${numero.format(m.tokens_saida || 0)} de saída (${numero.format(m.chamadas_ao_modelo || 0)} chamadas)`),
      );
      if (m.parou_por_limite) rodape.appendChild(el("span", null, "Parou no limite de passos do agente."));
      this.corpo.appendChild(rodape);
      this.painel.open = false;
      this.encerrarPainel();
    }

    erro(tipo, mensagem) {
      this.fecharPendentes("com-erro");
      const caixa = el("div", "caixa-erro");
      caixa.setAttribute("role", "alert");
      caixa.append(el("strong", null, TITULOS_DE_ERRO[tipo] || "Algo deu errado"),
        el("p", null, mensagem || "Tente de novo em instantes."));
      this.corpo.appendChild(caixa);
      this.corpo.appendChild(botaoTentarDeNovo("Tentar de novo"));
      this.encerrarPainel();
    }

    cancelado(mensagem) {
      this.fecharPendentes("interrompida");
      this.corpo.appendChild(el("p", "caixa-cancelada", mensagem || "Pergunta interrompida a seu pedido."));
      this.corpo.appendChild(botaoTentarDeNovo("Perguntar de novo"));
      this.encerrarPainel();
    }
  }

  function botaoTentarDeNovo(texto) {
    const b = el("button", "botao-secundario", texto);
    b.type = "button";
    b.disabled = emAndamento;
    b.addEventListener("click", () => { if (!emAndamento && ultimaPergunta) enviar(ultimaPergunta); });
    botoesTentarDeNovo.push(b);
    return b;
  }

  // ------------------------------------------------------------------ estado da interface
  function atualizarContador() {
    const n = campo.value.length;
    contador.textContent = `${n}/${LIMITE_DE_CARACTERES}`;
    contador.classList.toggle("perto-do-limite", n >= LIMITE_DE_CARACTERES * 0.9);
  }

  function definirAndamento(ativo) {
    emAndamento = ativo;
    parando = false;
    campo.disabled = ativo;
    botao.disabled = false;
    botao.textContent = ativo ? "Parar" : "Enviar";
    botao.classList.toggle("parar", ativo);
    botao.setAttribute("aria-label", ativo ? "Parar a pergunta em andamento" : "Enviar a pergunta");
    for (const b of botoesTentarDeNovo) b.disabled = ativo;
    if (!ativo) campo.focus();
  }

  // ------------------------------------------------------------------ leitura do fluxo NDJSON
  async function lerEventos(resposta, aoEvento) {
    const leitor = resposta.body.getReader();
    const decodificador = new TextDecoder();
    let buffer = "";
    const processar = (linha) => {
      if (!linha.trim()) return false;
      let evento;
      try { evento = JSON.parse(linha); } catch { return false; }
      if (!evento || typeof evento !== "object") return false;
      aoEvento(evento);
      return TIPOS_TERMINAIS.has(evento.evento);
    };
    for (;;) {
      const { value, done } = await leitor.read();
      if (done) break;
      buffer += decodificador.decode(value, { stream: true });
      let posicao;
      while ((posicao = buffer.indexOf("\n")) >= 0) {
        const linha = buffer.slice(0, posicao);
        buffer = buffer.slice(posicao + 1);
        if (processar(linha)) { leitor.cancel().catch(() => {}); return true; }
      }
    }
    buffer += decodificador.decode();
    return processar(buffer);
  }

  function tratarEvento(resposta, evento) {
    switch (evento.evento) {
      case "modelo_inicio": resposta.modelo(evento.chamada); break;
      case "tool_inicio": resposta.toolInicio(evento); break;
      case "tool_fim": resposta.toolFim(evento); break;
      case "espera": resposta.espera(evento.segundos); break;
      case "fim": resposta.fim(evento); break;
      case "erro": resposta.erro(evento.tipo, evento.mensagem); break;
      case "cancelado": resposta.cancelado(evento.mensagem); break;
      default: break;                                // evento desconhecido: ignorado
    }
    rolarParaOFim();
  }

  // ------------------------------------------------------------------ enviar e parar
  async function enviar(texto) {
    const pergunta = texto.trim();
    if (emAndamento || !pergunta) return;
    if (pergunta.length > LIMITE_DE_CARACTERES) return;
    ultimaPergunta = pergunta;
    vazio.hidden = true;

    conversa.appendChild(el("div", "mensagem usuario", pergunta));
    campo.value = "";
    atualizarContador();
    const resposta = new Resposta();
    definirAndamento(true);
    controlador = new AbortController();

    try {
      const http = await fetch("/api/perguntar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pergunta }),
        signal: controlador.signal,
      });
      if (!http.ok) {
        let tipo = "interno";
        let mensagem = `O servidor respondeu com erro (HTTP ${http.status}).`;
        try {
          const corpo = await http.json();
          if (corpo && corpo.erro) { tipo = corpo.erro.tipo || tipo; mensagem = corpo.erro.mensagem || mensagem; }
        } catch { /* corpo não é JSON: fica a mensagem genérica */ }
        resposta.erro(tipo, mensagem);
        return;
      }
      const terminou = await lerEventos(http, (evento) => tratarEvento(resposta, evento));
      if (!terminou) {
        resposta.erro("conexao", "A conexão com o servidor foi encerrada antes do fim da resposta. Tente de novo.");
      }
    } catch (erro) {
      if (erro && erro.name === "AbortError") {
        resposta.cancelado("Pergunta interrompida a seu pedido.");
      } else {
        resposta.erro("rede", "Não consegui falar com o servidor. Confira se ele ainda está rodando e tente de novo.");
      }
    } finally {
      controlador = null;
      definirAndamento(false);
      rolarParaOFim();
    }
  }

  async function parar() {
    if (!emAndamento || parando) return;
    parando = true;
    botao.disabled = true;
    botao.textContent = "Parando…";
    try {
      const http = await fetch("/api/parar", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      if (!http.ok) throw new Error(`HTTP ${http.status}`);
      // O servidor avisa o agente; o fluxo termina com 'cancelado' assim que a etapa atual acabar.
    } catch {
      if (controlador) controlador.abort();       // sem resposta do servidor: desistimos da conexão
    }
  }

  // ------------------------------------------------------------------ eventos da página
  formulario.addEventListener("submit", (e) => {
    e.preventDefault();
    if (emAndamento) parar(); else enviar(campo.value);
  });

  campo.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (!emAndamento) enviar(campo.value);
    }
  });

  campo.addEventListener("input", () => {
    atualizarContador();
    campo.style.height = "auto";                   // propriedade CSSOM: permitida pela CSP
    campo.style.height = `${Math.min(campo.scrollHeight + 2, window.innerHeight * 0.4)}px`;
  });

  for (const exemplo of document.querySelectorAll(".exemplo")) {
    exemplo.addEventListener("click", () => {
      if (emAndamento) return;
      const texto = exemplo.textContent.trim();
      campo.value = texto;
      atualizarContador();
      campo.focus();
      const inicio = texto.indexOf("_");             // seleciona o trecho "____" para o usuário completar
      if (inicio >= 0) {
        let fim = inicio;
        while (texto[fim] === "_") fim += 1;
        campo.setSelectionRange(inicio, fim);
      }
    });
  }

  async function verificarServidor() {
    try {
      const http = await fetch("/api/saude");
      const saude = await http.json();
      if (!http.ok || !saude.ok) throw new Error("servidor indisponível");
      const demonstracao = saude.modo === "demonstracao";
      $("faixa-demo").hidden = !demonstracao;
      $("exemplos-demo").hidden = !demonstracao;
      status.textContent = demonstracao ? "Modo demonstração (agente simulado)" : `${saude.provedor} · ${saude.modelo}`;
      status.classList.remove("problema");
      if (saude.ocupado) status.textContent += " · terminando uma pergunta anterior";
    } catch {
      status.textContent = "Servidor indisponível. Ele está rodando?";
      status.classList.add("problema");
    }
  }

  atualizarContador();
  verificarServidor();
  campo.focus();
})();
