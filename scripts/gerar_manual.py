"""Gera o manual de elegibilidade de produção (PDF).

Uso (na raiz do projeto):
    pip install reportlab
    python scripts/gerar_manual.py [caminho_de_saida.pdf]
"""
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

SAIDA = sys.argv[1] if len(sys.argv) > 1 else "docs/manual_elegibilidade_v2.3.pdf"
AZUL = colors.HexColor("#1F3A5F")
CINZA = colors.HexColor("#EEF1F5")
RODAPE = "Alfa Seguridade S.A. (empresa fictícia) - MAN-COM-004 - Versão 2.3 - Documento para fins de estudo"

# ---------------------------------------------------------------- estilos
CORPO = ParagraphStyle("Corpo", fontName="Helvetica", fontSize=10, leading=14,
                       alignment=TA_JUSTIFY, spaceAfter=6)
TITULO = ParagraphStyle("Título", fontName="Helvetica-Bold", fontSize=20, leading=25,
                        textColor=AZUL, spaceAfter=4)
SUBTITULO = ParagraphStyle("Subtitulo", fontName="Helvetica", fontSize=11, leading=15,
                           textColor=colors.HexColor("#555555"), spaceAfter=10)
H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=14, leading=18,
                    textColor=AZUL, spaceBefore=14, spaceAfter=6, keepWithNext=1)
H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11.5, leading=15,
                    textColor=AZUL, spaceBefore=10, spaceAfter=4, keepWithNext=1)
CORPO_KWN = ParagraphStyle("CorpoKWN", parent=CORPO, keepWithNext=1)
TAB = ParagraphStyle("Tab", fontName="Helvetica", fontSize=9, leading=12)
TABH = ParagraphStyle("TabH", fontName="Helvetica-Bold", fontSize=9, leading=12,
                      textColor=colors.white)
LISTA = ParagraphStyle("Lista", parent=CORPO, leftIndent=14, bulletIndent=2, spaceAfter=3)


def p(texto, estilo=CORPO):
    return Paragraph(texto, estilo)


def item(texto):
    return Paragraph(texto, LISTA, bulletText="-")


def tabela(linhas, larguras, cabecalho=True):
    dados = []
    for i, linha in enumerate(linhas):
        estilo = TABH if (cabecalho and i == 0) else TAB
        dados.append([Paragraph(str(c), estilo) for c in linha])
    t = Table(dados, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    estilos = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C0CC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if cabecalho:
        estilos.append(("BACKGROUND", (0, 0), (-1, 0), AZUL))
    t.setStyle(TableStyle(estilos))
    return t


def regra(id_, título, texto, parâmetro, exemplo=None):
    """Bloco de uma regra: título com ID, descricao, parâmetro e consequencia."""
    bloco = [p(f"{id_} - {título}", H2)]
    bloco += [p(t) for t in texto]
    linhas = [["Parâmetro", parâmetro],
              ["Se não atender", f"A venda não é elegível e o motivo registrado é {id_}."]]
    t = Table([[Paragraph(f"<b>{a}</b>", TAB), Paragraph(b, TAB)] for a, b in linhas],
              colWidths=[3.3 * cm, 13.2 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), CINZA),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C0CC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    bloco += [Spacer(1, 2), t]
    if exemplo:
        bloco += [Spacer(1, 4), p(f"<b>Exemplo.</b> {exemplo}")]
    return KeepTogether(bloco)


def rodape(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(2 * cm, 1.2 * cm, RODAPE)
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


# ---------------------------------------------------------------- conteudo
h = []

h += [p("Manual de Elegibilidade de Produção de Vendas", TITULO),
      p("Consórcio e Capitalização", SUBTITULO),
      tabela([
          ["Documento", "MAN-COM-004"],
          ["Versão", "2.3"],
          ["Vigência", "A partir de 01/01/2026"],
          ["Área responsável", "Gestão Comercial"],
          ["Aplicação", "Vendas de Consórcio e de Capitalização realizadas a partir de 01/01/2026"],
      ], [4 * cm, 12.5 * cm], cabecalho=False)]

h += [p("1. Objetivo e escopo", H1),
      p("Este manual define as regras que determinam se uma venda de Consórcio ou de Capitalização "
        "gera <b>produção</b> para o vendedor e entra na sua <b>carteira</b>. As regras valem para todos "
        "os canais de venda e para todos os vendedores."),
      p("<b>Este manual é a fonte oficial das regras.</b> Quando houver divergência entre este documento "
        "e qualquer sistema, rotina ou código, prevalece o que está escrito aqui.")]

h += [p("2. Conceitos", H1),
      tabela([
          ["Termo", "Definição"],
          ["Venda", "Contratação de uma cota de consórcio ou de um título de capitalização, registrada em nome de um cliente."],
          ["Produção", "Quantidade de vendas elegíveis de um vendedor, contadas no mês da data da venda."],
          ["Carteira", "Conjunto de vendas elegíveis atribuídas a um vendedor. A venda entra na carteira na data do primeiro pagamento."],
          ["Vendedor ativo", "Vendedor com vínculo iniciado em ou antes da data da venda e que ainda não foi desligado (ver COM-01)."],
          ["Canal", "Meio pelo qual a venda foi feita: agência, telefone ou digital."],
          ["Primeiro pagamento", "No consórcio, a 1ª parcela. Na capitalização, o pagamento único ou a 1ª mensalidade."],
          ["Prazo de arrependimento", "Período, em dias corridos a partir da data da venda, em que o cliente pode desistir da contratação."],
          ["Carência (capitalização)", "Período, em dias corridos a partir da data da venda, em que o cancelamento do título não gera produção."],
      ], [4.2 * cm, 12.3 * cm])]

h += [p("3. Ordem de avaliação", H1),
      p("Cada venda é avaliada pelas regras abaixo, nesta ordem. <b>A primeira regra que impedir a venda "
        "define o motivo registrado</b>; as seguintes não são avaliadas.", CORPO_KWN),
      tabela([
          ["Ordem", "Regra", "Grupo"],
          ["1", "COM-02 - Venda digital sem vendedor identificado", "Comum"],
          ["2", "COM-01 - Vendedor ativo na data da venda", "Comum"],
          ["3", "COM-03 - Cancelamento no prazo de arrependimento", "Comum"],
          ["4", "Regras do produto: CONS-01 e CONS-02 (Consórcio) ou CAP-01, CAP-02 e CAP-03 (Capitalização), nesta ordem", "Produto"],
      ], [2 * cm, 11.5 * cm, 3 * cm]),
      Spacer(1, 4),
      p("Uma venda que passa por todas as regras é <b>elegível</b>: conta na produção do vendedor e entra na sua carteira.")]

h += [p("4. Regras comuns a todos os produtos", H1)]
h += [regra("COM-01", "Vendedor ativo na data da venda",
            ["A venda só é elegível se o vendedor estava ativo na data em que ela foi realizada. "
             "O vendedor é considerado ativo desde a data de início do vínculo até a <b>data de desligamento, "
             "inclusive</b>. Uma venda feita no próprio dia do desligamento é elegível; a partir do dia seguinte, não.",
             "Venda sem vendedor identificado em canal que não seja o digital é tratada como inconsistência "
             "cadastral e também não é elegível, com o motivo COM-01."],
            "Vendedor ativo até a data de desligamento, inclusive.",
            "Vendedora desligada em 10/03/2026. Uma venda em 10/03/2026 é elegível (se as demais regras forem "
            "atendidas). Uma venda em 11/03/2026 não é elegível: motivo COM-01."),
      regra("COM-02", "Venda digital sem vendedor identificado",
            ["Vendas feitas pelo canal digital em que não há vendedor identificado não geram produção para "
             "nenhum vendedor e não entram em nenhuma carteira."],
            "Canal digital exige vendedor identificado.",
            "Contratação feita pelo aplicativo, sem código de vendedor informado: não é elegível, motivo COM-02."),
      regra("COM-03", "Cancelamento no prazo de arrependimento",
            ["Se o cliente cancelar a venda em até <b>10 (dez) dias corridos</b> contados da data da venda, "
             "a venda não conta, qualquer que seja o produto. O prazo adotado pela empresa é superior ao "
             "prazo legal mínimo de 7 dias.",
             "Cancelamentos feitos depois desse prazo não são tratados por esta regra; no caso da "
             "Capitalização, aplica-se também a regra CAP-03."],
            "Prazo de arrependimento: 10 dias corridos.",
            "Venda em 05/05/2026 é cancelada em 14/05/2026 (9 dias): não é elegível, motivo COM-03. "
            "Se o cancelamento ocorresse em 16/05/2026 (11 dias), esta regra não se aplicaria.")]

h += [p("5. Regras do Consórcio", H1)]
h += [regra("CONS-01", "Tipos de consórcio elegíveis",
            ["Geram produção os consórcios dos tipos <b>imóvel, auto e moto</b>. Consórcios do tipo "
             "<b>serviços</b> não geram produção."],
            "Tipos elegíveis: imóvel, auto e moto.",
            "Cota de consórcio de moto, paga e com vendedor ativo: elegível. Cota de consórcio de serviços: "
            "não é elegível, motivo CONS-01."),
      regra("CONS-02", "Pagamento da primeira parcela",
            ["A venda de consórcio só conta depois do pagamento da 1ª parcela. Até o pagamento, a venda "
             "permanece fora da carteira; a data do pagamento passa a ser a data de entrada na carteira."],
            "Exige pagamento da 1ª parcela.",
            "Cota de consórcio auto vendida em 02/06/2026 sem pagamento da 1ª parcela: não é elegível, "
            "motivo CONS-02, até que o pagamento seja confirmado.")]

h += [p("6. Regras da Capitalização", H1)]
h += [regra("CAP-01", "Modalidades elegíveis",
            ["Geram produção os títulos das modalidades <b>tradicional e incentivo</b>. Títulos das "
             "modalidades <b>popular e instrumento de garantia</b> não geram produção."],
            "Modalidades elegíveis: tradicional e incentivo.",
            "Título da modalidade popular, pago: não é elegível, motivo CAP-01."),
      regra("CAP-02", "Pagamento do título",
            ["No <b>pagamento único</b>, a venda conta a partir da confirmação do pagamento. No pagamento "
             "<b>mensal</b>, a venda só conta depois do pagamento da 1ª mensalidade. A data do primeiro "
             "pagamento é a data de entrada na carteira."],
            "Exige pagamento único confirmado ou 1ª mensalidade paga.",
            "Título tradicional com pagamento mensal e 1ª mensalidade em aberto: não é elegível, motivo CAP-02. "
            "Título com pagamento único confirmado 3 dias após a venda: elegível, entra na carteira na data do pagamento."),
      regra("CAP-03", "Cancelamento durante a carência",
            ["Se o título for cancelado em até <b>90 (noventa) dias corridos</b> contados da data da venda, "
             "a venda não conta. Cancelamentos nos primeiros 10 dias são tratados pela regra COM-03, "
             "que é avaliada antes."],
            "Carência: 90 dias corridos.",
            "Título de incentivo vendido em 01/04/2026 e cancelado em 15/06/2026 (75 dias): não é elegível, "
            "motivo CAP-03. Se fosse cancelado em 15/07/2026 (105 dias), a venda continuaria elegível.")]

h += [p("7. Quadro-resumo de parâmetros", H1),
      tabela([
          ["Parâmetro", "Valor", "Regra"],
          ["Vendedor ativo", "Até a data de desligamento, inclusive", "COM-01"],
          ["Canal digital", "Exige vendedor identificado", "COM-02"],
          ["Prazo de arrependimento", "10 dias corridos", "COM-03"],
          ["Tipos de consórcio elegíveis", "imóvel, auto, moto", "CONS-01"],
          ["Consórcio: pagamento exigido", "1ª parcela", "CONS-02"],
          ["Modalidades de capitalização elegíveis", "tradicional, incentivo", "CAP-01"],
          ["Capitalização: pagamento exigido", "Único confirmado ou 1ª mensalidade", "CAP-02"],
          ["Carência da capitalização", "90 dias corridos", "CAP-03"],
      ], [6.5 * cm, 7 * cm, 3 * cm])]

h += [p("8. Exemplo de precedência entre regras", H1),
      p("Um título de capitalização é cancelado 5 dias depois da venda. Como 5 dias está dentro do prazo de "
        "arrependimento (10 dias), a regra <b>COM-03</b> é a primeira a impedir a venda e é a registrada. "
        "A regra CAP-03 não chega a ser avaliada."),
      p("Um consórcio de serviços que também não teve a 1ª parcela paga é registrado com o motivo "
        "<b>CONS-01</b>, porque CONS-01 vem antes de CONS-02.")]

h += [p("9. Histórico de versões", H1),
      tabela([
          ["Versão", "Data", "Alteração"],
          ["2.0", "01/03/2025", "Primeira versão consolidada. Prazo de arrependimento de 7 dias, carência de 60 dias e consórcios elegíveis: imóvel e auto."],
          ["2.1", "15/09/2025", "Esclarecimento da regra COM-01: o vendedor é considerado ativo até a data de desligamento, inclusive."],
          ["2.2", "01/11/2025", "Inclusão do consórcio de moto entre os tipos elegíveis (CONS-01)."],
          ["2.3", "01/01/2026", "Ampliação do prazo de arrependimento para 10 dias corridos (COM-03) e da carência da capitalização para 90 dias corridos (CAP-03)."],
      ], [2 * cm, 2.6 * cm, 11.9 * cm])]

doc = SimpleDocTemplate(SAIDA, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                        topMargin=2 * cm, bottomMargin=2 * cm,
                        title="Manual de Elegibilidade de Produção de Vendas - v2.3",
                        author="Gestão Comercial (documento fictício)")
doc.build(h, onFirstPage=rodape, onLaterPages=rodape)
print("PDF gerado em", SAIDA)
