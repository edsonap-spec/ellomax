"""Exportação para Excel (openpyxl) e PDF (reportlab)."""
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FMT_BRL = '"R$" #,##0.00;[Red]-"R$" #,##0.00'
FMT_NUM = '#,##0.##'
FMT_PCT = '0.0"%"'


def _dt(v):
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return v or None


def _brl(v):
    s = f"{abs(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if (v or 0) < -0.004 else "R$ ") + s


def _num(v):
    v = v or 0
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _d(v):
    d = _dt(v)
    return d.strftime("%d/%m/%Y") if isinstance(d, date) else (d or "")


# ---------------------------------------------------------------- Excel

def _aba(wb, titulo, cabecalho, linhas, formatos=None, primeira=False):
    ws = wb.active if primeira else wb.create_sheet()
    ws.title = titulo[:31]
    ws.append(cabecalho)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0E4D64")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for li in linhas:
        ws.append(list(li))
    formatos = formatos or {}
    for idx, nome in enumerate(cabecalho, start=1):
        letra = get_column_letter(idx)
        fmt = formatos.get(nome)
        largura = max([len(str(nome))] + [len(str(li[idx - 1])) for li in linhas if li[idx - 1] is not None] or [10])
        ws.column_dimensions[letra].width = min(max(largura + 2, 10), 60)
        for row in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
            for c in row:
                if fmt:
                    c.number_format = fmt
                elif isinstance(c.value, date):
                    c.number_format = "DD/MM/YYYY"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def _salvar(wb):
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def xlsx_editais(linhas):
    wb = Workbook()
    cab = ["Empresa", "Edital", "Processo", "Contrato", "Órgão", "Modalidade", "Objeto", "Situação",
           "Vigência início", "Vigência fim", "Contratado", "Empenhado", "Entregue", "Recebido + retido",
           "A receber", "Em atraso", "Gastos", "Impostos estimados", "Lucro projetado", "Margem %"]
    dados = [(e["empresa"], e["numero"], e["processo"], e["numero_contrato"], e["orgao"], e["modalidade"], e["objeto"],
              e["status"], _dt(e["vigencia_inicio"]), _dt(e["vigencia_fim"]), r["contratado"], r["empenhado"], r["entregue"],
              r["liquidado"], r["a_receber"], r["atrasado"], r["gastos"], r["impostos_estimados"], r["lucro_projetado"],
              r["margem_projetada"]) for e, r in linhas]
    moeda = {k: FMT_BRL for k in cab[10:19]}
    moeda["Margem %"] = FMT_PCT
    _aba(wb, "Editais", cab, dados, moeda, primeira=True)
    return _salvar(wb)


def xlsx_edital(d):
    e, r = d["e"], d["r"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    campos = [("Empresa", e["empresa"]), ("Órgão", e["orgao"]), ("CNPJ do órgão", e["cnpj_orgao"]), ("UASG", e["uasg"]),
              ("Nº do edital", e["numero"]), ("Processo", e["processo"]), ("Modalidade", e["modalidade"]),
              ("Contrato / ata", e["numero_contrato"]), ("Situação", e["status"]), ("Objeto", e["objeto"]),
              ("Abertura", _dt(e["data_abertura"])), ("Homologação", _dt(e["data_homologacao"])),
              ("Vigência início", _dt(e["vigencia_inicio"])), ("Vigência fim", _dt(e["vigencia_fim"])),
              ("Prazo de entrega", e["prazo_entrega"]), ("Local de entrega", e["local_entrega"]),
              ("Contato no órgão", e["contato_orgao"]), ("Responsável", e["responsavel"]), (None, None),
              ("Valor contratado", r["contratado"]), ("  dos itens", r["contratado_itens"]), ("  aditivos", r["aditivos"]),
              ("Empenhado", r["empenhado"]), ("Entregue", r["entregue"]), ("Recebido (líquido)", r["recebido"]),
              ("Retenções", r["retencoes"]), ("Saldo a receber", r["a_receber"]), ("Em atraso", r["atrasado"]),
              ("Gastos lançados", r["gastos"]), ("Custo estimado dos itens", r["custo_estimado"]),
              ("Impostos estimados", r["impostos_estimados"]), ("Lucro projetado", r["lucro_projetado"])]
    for rot, val in campos:
        ws.append([rot, val])
        if isinstance(val, float):
            ws.cell(ws.max_row, 2).number_format = FMT_BRL
        elif isinstance(val, date):
            ws.cell(ws.max_row, 2).number_format = "DD/MM/YYYY"
    ws.append(["Margem projetada", r["margem_projetada"]])
    ws.cell(ws.max_row, 2).number_format = FMT_PCT
    for c in ws["A"]:
        c.font = Font(bold=True)
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 80

    _aba(wb, "Itens", ["Lote", "Item", "Descrição", "Marca", "Unidade", "Quantidade", "Valor unitário", "Total",
                       "Empenhado", "Entregue", "Saldo", "Custo unitário"],
         [(i["lote"], i["numero_item"], i["descricao"], i["marca"], i["unidade"], i["quantidade"], i["valor_unitario"],
           i["quantidade"] * i["valor_unitario"], i["empenhado"], i["qtd_entregue"], i["quantidade"] - i["qtd_entregue"],
           i["custo_unitario"]) for i in d["itens"]],
         {"Valor unitário": FMT_BRL, "Total": FMT_BRL, "Custo unitário": FMT_BRL, "Quantidade": FMT_NUM,
          "Empenhado": FMT_NUM, "Entregue": FMT_NUM, "Saldo": FMT_NUM})
    _aba(wb, "Empenhos e OF", ["Tipo", "Número", "Emissão", "Prazo de entrega", "Entregue em", "Valor", "Itens", "Observações"],
         [(m["tipo"], m["numero"], _dt(m["data_emissao"]), _dt(m["prazo_entrega"]), _dt(m["data_entrega"]),
           m["valor_itens"] or m["valor"],
           "; ".join(f"item {li['numero_item'] or '-'}: {_num(li['quantidade'])}" for li in d["linhas_emp"].get(m["id"], [])),
           m["observacoes"]) for m in d["empenhos"]], {"Valor": FMT_BRL})
    _aba(wb, "Recebimentos", ["Descrição", "Empenho/OF", "NF", "Previsto em", "Valor previsto", "Recebido em",
                              "Valor recebido", "Retenções", "Diferença", "Observações"],
         [(x["descricao"], x["empenho"], x["nota_fiscal"], _dt(x["data_prevista"]), x["valor_previsto"],
           _dt(x["data_recebimento"]), x["valor_recebido"], x["retencoes"],
           x["valor_previsto"] - x["valor_recebido"] - x["retencoes"], x["observacoes"]) for x in d["receb"]],
         {"Valor previsto": FMT_BRL, "Valor recebido": FMT_BRL, "Retenções": FMT_BRL, "Diferença": FMT_BRL})
    _aba(wb, "Gastos", ["Data", "Categoria", "Descrição", "Fornecedor", "Documento", "Valor"],
         [(_dt(x["data"]), x["categoria"], x["descricao"], x["fornecedor"], x["documento"], x["valor"]) for x in d["gastos"]],
         {"Valor": FMT_BRL})
    _aba(wb, "Aditivos", ["Número", "Tipo", "Assinatura", "Descrição", "Nova vigência", "Valor", "Percentual"],
         [(x["numero"], x["tipo"], _dt(x["data_assinatura"]), x["descricao"], _dt(x["nova_vigencia_fim"]), x["valor"],
           x["percentual"]) for x in d["aditivos"]], {"Valor": FMT_BRL, "Percentual": FMT_PCT})
    _aba(wb, "Garantias", ["Modalidade", "Descrição", "%", "Valor", "Apólice", "Seguradora/banco", "Início", "Fim",
                           "Devolvida em"],
         [(x["tipo"], x["descricao"], x["percentual"], x["valor"], x["apolice"], x["seguradora"], _dt(x["data_inicio"]),
           _dt(x["data_fim"]), _dt(x["data_devolucao"])) for x in d["garantias"]], {"Valor": FMT_BRL, "%": FMT_PCT})
    _aba(wb, "Ativos alocados", ["Ativo", "Código", "Quantidade", "Unidade", "Local", "Saída", "Retorno previsto", "Devolvido em"],
         [(x["ativo_nome"], x["codigo"], x["quantidade"], x["unidade"], x["local"], _dt(x["data_saida"]),
           _dt(x["data_prevista_retorno"]), _dt(x["data_retorno"])) for x in d["alocacoes"]], {"Quantidade": FMT_NUM})
    return _salvar(wb)


def xlsx_ativos(ativos):
    wb = Workbook()
    _aba(wb, "Estoque de ativos", ["Ativo", "Código", "Categoria", "Empresa", "Unidade", "Total", "Alocado", "Manutenção",
                                   "Disponível", "Valor unitário", "Situação"],
         [(a["nome"], a["codigo"], a["categoria"], a["empresa"], a["unidade"], a["quantidade_total"], a["alocado"],
           a["qtd_manutencao"], a["disponivel"], a["valor_unitario"], "Ativo" if a["ativo"] else "Inativo") for a in ativos],
         {"Total": FMT_NUM, "Alocado": FMT_NUM, "Manutenção": FMT_NUM, "Disponível": FMT_NUM, "Valor unitário": FMT_BRL},
         primeira=True)
    return _salvar(wb)


# ---------------------------------------------------------------- PDF

def pdf_edital(d):
    e, r = d["e"], d["r"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Edital {e['numero']}", author=e["empresa"] or "")
    est = getSampleStyleSheet()
    peq = est["BodyText"].clone("peq", fontSize=8, leading=10)
    h2 = est["Heading2"].clone("h2", spaceBefore=10, spaceAfter=4)

    def esc(t):
        return str(t if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

    def P(marcacao):
        return Paragraph(marcacao, peq)

    def tabela(cab, linhas, larguras=None, total=None, direita=()):
        dados = [[P(f"<b>{esc(c)}</b>") for c in cab]] + [[P(esc(c)) for c in li] for li in linhas]
        if total:
            dados.append([P(f"<b>{esc(c)}</b>") for c in total])
        t = Table(dados, colWidths=larguras, repeatRows=1)
        estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E3EEF1")),
                  ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
                  ("VALIGN", (0, 0), (-1, -1), "TOP")]
        for col in direita:
            estilo.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
        if total:
            estilo.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F2F2F2")))
        t.setStyle(TableStyle(estilo))
        return t

    hist = [Paragraph(esc(f"Edital {e['numero']} — {e['orgao']}"), est["Title"]),
            P(esc(f"{e['empresa'] or ''} · Situação: {e['status']} · Emitido em {date.today():%d/%m/%Y}")),
            Spacer(1, 6)]
    info = [("Modalidade", e["modalidade"]), ("Processo", e["processo"]), ("Contrato / ata", e["numero_contrato"]),
            ("CNPJ do órgão", e["cnpj_orgao"]), ("UASG", e["uasg"]), ("Homologação", _d(e["data_homologacao"])),
            ("Vigência", f"{_d(e['vigencia_inicio'])} a {_d(e['vigencia_fim'])}"), ("Prazo de entrega", e["prazo_entrega"]),
            ("Local de entrega", e["local_entrega"]), ("Contato", e["contato_orgao"]), ("Responsável", e["responsavel"]),
            ("Abertura", _d(e["data_abertura"]))]
    linhas_info = []
    for i in range(0, len(info), 3):
        li = []
        for rot, val in info[i:i + 3]:
            li += [f"<b>{esc(rot)}</b>", esc(val or "—")]
        linhas_info.append(li)
    t = Table([[P(c) for c in li] for li in linhas_info], colWidths=[28 * mm, 62 * mm] * 3)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD"))]))
    hist += [t, Spacer(1, 4), P(f"<b>Objeto:</b> {esc(e['objeto'])}")]

    hist.append(Paragraph("Resumo financeiro", h2))
    resumo = [("Contratado", r["contratado"]), ("Empenhado", r["empenhado"]), ("Entregue", r["entregue"]),
              ("Recebido + retido", r["liquidado"]), ("Saldo a receber", r["a_receber"]), ("Em atraso", r["atrasado"]),
              ("Gastos", r["gastos"]), ("Impostos estimados", r["impostos_estimados"]),
              ("Lucro projetado", r["lucro_projetado"])]
    hist.append(tabela([x[0] for x in resumo] + ["Margem"], [[_brl(x[1]) for x in resumo] + [f"{r['margem_projetada']:.1f}%"]],
                       direita=range(10)))

    if d["itens"]:
        hist.append(Paragraph("Itens vencidos", h2))
        hist.append(tabela(["Lote", "Item", "Descrição", "Marca", "Un.", "Qtd.", "Vlr. unit.", "Total", "Empenhado", "Entregue", "Saldo"],
                           [(i["lote"], i["numero_item"], i["descricao"], i["marca"], i["unidade"], _num(i["quantidade"]),
                             _brl(i["valor_unitario"]), _brl(i["quantidade"] * i["valor_unitario"]), _num(i["empenhado"]),
                             _num(i["qtd_entregue"]), _num(i["quantidade"] - i["qtd_entregue"])) for i in d["itens"]],
                           [12 * mm, 12 * mm, 80 * mm, 30 * mm, 12 * mm, 18 * mm, 24 * mm, 26 * mm, 20 * mm, 20 * mm, 18 * mm],
                           total=["", "", "Total", "", "", "", "", _brl(r["contratado_itens"]), "", "", ""],
                           direita=range(5, 11)))
    if d["empenhos"]:
        hist.append(Paragraph("Pedidos de compra, empenhos e ordens de fornecimento", h2))
        hist.append(tabela(["Tipo", "Número", "Emissão", "Prazo", "Entregue em", "Valor", "Km", "Frete"],
                           [(m["tipo"], m["numero"], _d(m["data_emissao"]), _d(m["prazo_entrega"]), _d(m["data_entrega"]),
                             _brl(m["valor_itens"] or m["valor"]), _num(m["distancia_km"]) if m["distancia_km"] else "",
                             _brl((m["distancia_km"] or 0) * (m["valor_km"] if m["valor_km"] is not None else 3))
                             if m["distancia_km"] else "") for m in d["empenhos"]], direita=(5, 6, 7)))
    if d["receb"]:
        hist.append(Paragraph("Recebimentos", h2))
        hist.append(tabela(["Descrição", "Empenho/OF", "NF", "Previsto em", "Valor previsto", "Recebido em", "Valor recebido",
                            "Retenções", "Diferença"],
                           [(x["descricao"], x["empenho"], x["nota_fiscal"], _d(x["data_prevista"]), _brl(x["valor_previsto"]),
                             _d(x["data_recebimento"]), _brl(x["valor_recebido"]), _brl(x["retencoes"]),
                             _brl(x["valor_previsto"] - x["valor_recebido"] - x["retencoes"])) for x in d["receb"]],
                           total=["Total", "", "", "", _brl(r["previsto"]), "", _brl(r["recebido"]), _brl(r["retencoes"]),
                                  _brl(r["previsto"] - r["liquidado"])],
                           direita=(4, 6, 7, 8)))
    if d["gastos"]:
        hist.append(Paragraph("Gastos", h2))
        hist.append(tabela(["Data", "Categoria", "Descrição", "Fornecedor", "Documento", "Valor"],
                           [(_d(x["data"]), x["categoria"], x["descricao"], x["fornecedor"], x["documento"], _brl(x["valor"]))
                            for x in d["gastos"]], total=["Total", "", "", "", "", _brl(r["gastos"])], direita=(5,)))
    if d["aditivos"]:
        hist.append(Paragraph("Termos aditivos", h2))
        hist.append(tabela(["Nº", "Tipo", "Assinatura", "Descrição", "Nova vigência", "Valor", "%"],
                           [(x["numero"], x["tipo"], _d(x["data_assinatura"]), x["descricao"], _d(x["nova_vigencia_fim"]),
                             _brl(x["valor"]), _num(x["percentual"]) if x["percentual"] is not None else "")
                            for x in d["aditivos"]], direita=(5, 6)))
    if d["garantias"]:
        hist.append(Paragraph("Garantias contratuais", h2))
        hist.append(tabela(["Modalidade", "Descrição", "Valor", "Apólice", "Seguradora/banco", "Vigência", "Devolvida em"],
                           [(x["tipo"], x["descricao"], _brl(x["valor"]), x["apolice"], x["seguradora"],
                             f"{_d(x['data_inicio'])} a {_d(x['data_fim'])}", _d(x["data_devolucao"])) for x in d["garantias"]],
                           direita=(2,)))
    if d["alocacoes"]:
        hist.append(Paragraph("Ativos alocados", h2))
        hist.append(tabela(["Ativo", "Quantidade", "Local", "Saída", "Retorno previsto", "Devolvido em"],
                           [(x["ativo_nome"], f"{_num(x['quantidade'])} {x['unidade'] or ''}", x["local"], _d(x["data_saida"]),
                             _d(x["data_prevista_retorno"]), _d(x["data_retorno"])) for x in d["alocacoes"]], direita=(1,)))
    doc.build(hist)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------- ordens de serviço

COR_TINTA = colors.HexColor("#14212B")
COR_MARCA = colors.HexColor("#0E4D64")
COR_SINAL = colors.HexColor("#F2A007")
COR_LINHA = colors.HexColor("#C9CED3")
COR_SUAVE = colors.HexColor("#F3F5F6")
COR_OK = colors.HexColor("#1F7A4D")
COR_NC = colors.HexColor("#B42318")
COR_MUDO = colors.HexColor("#5B6770")


def _esc(t):
    return str(t if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _marca(tipo):
    """Desenha um visto (ok), um X (nc) ou um traço (na) em vetor, sem depender de fontes de símbolos."""
    from reportlab.platypus import Flowable

    class Marca(Flowable):
        def wrap(self, *_):
            return 10, 10

        def draw(self):
            c = self.canv
            c.setLineWidth(1.6)
            c.setLineCap(1)
            if tipo == "ok":
                c.setStrokeColor(COR_OK)
                p = c.beginPath()
                p.moveTo(1, 5)
                p.lineTo(4, 2)
                p.lineTo(9.5, 8.5)
                c.drawPath(p, stroke=1, fill=0)
            elif tipo == "nc":
                c.setStrokeColor(COR_NC)
                c.line(1.5, 1.5, 8.5, 8.5)
                c.line(1.5, 8.5, 8.5, 1.5)
            elif tipo == "na":
                c.setStrokeColor(COR_MUDO)
                c.line(2, 5, 8, 5)
    return Marca()


def _estilos():
    from reportlab.lib.styles import ParagraphStyle
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=8.5, leading=11, textColor=COR_TINTA)
    return {
        "base": base,
        "peq": base.clone("peq", fontSize=7.5, leading=9.5),
        "mudo": base.clone("mudo", fontSize=7, leading=9, textColor=COR_MUDO),
        "rot": base.clone("rot", fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=COR_MUDO),
        "sec": base.clone("sec", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white),
        "grupo": base.clone("grupo", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=COR_MARCA),
        "cen": base.clone("cen", alignment=1),
        "dir": base.clone("dir", alignment=2),
    }


def _secao(titulo, est, largura):
    t = Table([[Paragraph(_esc(titulo).upper(), est["sec"])]], colWidths=[largura])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), COR_MARCA), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _campos(pares, est, largura, colunas=3):
    """Grade de campos rótulo/valor no estilo formulário."""
    linhas, atual = [], []
    for rot, val in pares:
        atual.append([Paragraph(_esc(rot).upper(), est["rot"]), Paragraph(_esc(val or "—"), est["base"])])
        if len(atual) == colunas:
            linhas.append(atual)
            atual = []
    if atual:
        while len(atual) < colunas:
            atual.append(["", ""])
        linhas.append(atual)
    dados = [[c for c in li] for li in linhas]
    t = Table(dados, colWidths=[largura / colunas] * colunas)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, COR_LINHA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _img_assinatura(data_url, largura, altura):
    import base64
    from reportlab.platypus import Image
    if not data_url or "," not in data_url:
        return Spacer(largura, altura)
    try:
        bruto = base64.b64decode(data_url.split(",", 1)[1])
        img = Image(BytesIO(bruto))
        fator = min(largura / img.imageWidth, altura / img.imageHeight)
        img.drawWidth, img.drawHeight = img.imageWidth * fator, img.imageHeight * fator
        return img
    except Exception:
        return Spacer(largura, altura)


def _cabecalho_rodape(titulo_dir, empresa, codigo=None):
    def desenhar(canv, doc):
        larg, alt = doc.pagesize
        canv.saveState()
        canv.setFillColor(COR_MARCA)
        canv.rect(0, alt - 6 * mm, larg, 6 * mm, stroke=0, fill=1)
        canv.setFillColor(COR_SINAL)
        canv.rect(0, alt - 7.2 * mm, 38 * mm, 1.2 * mm, stroke=0, fill=1)
        canv.setFont("Helvetica", 7)
        canv.setFillColor(COR_MUDO)
        canv.drawString(doc.leftMargin, 8 * mm, f"{empresa or ''} · {titulo_dir}")
        direita = f"Página {doc.page}"
        if codigo:
            direita = f"Código de verificação {codigo} · " + direita
        canv.drawRightString(larg - doc.rightMargin, 8 * mm, direita)
        canv.restoreState()
    return desenhar


def pdf_os(d):
    """Ordem de serviço / termo de entrega para assinatura do cliente (A4 retrato)."""
    from reportlab.platypus import Image, KeepTogether
    o = d["o"]
    est = _estilos()
    buf = BytesIO()
    margem = 14 * mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margem, rightMargin=margem, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=f"OS {o['numero']}", author=o["empresa"] or "")
    W = A4[0] - 2 * margem
    hist = []

    # cabeçalho: empresa à esquerda, número da OS à direita
    grande = est["base"].clone("grande", fontName="Helvetica-Bold", fontSize=13, leading=16)
    numero = est["dir"].clone("numero", fontName="Helvetica-Bold", fontSize=19, leading=23)
    emp = [Paragraph(_esc(o["empresa"] or ""), grande), Paragraph(f"CNPJ {_esc(o['empresa_cnpj'] or '—')}", est["mudo"])]
    num_os = [Paragraph("ORDEM DE SERVIÇO", est["rot"].clone("rotd", alignment=2)), Paragraph(f"Nº {_esc(o['numero'])}", numero),
              Paragraph(f"{_esc(o['tipo'])} · <b>{_esc(o['status'])}</b>", est["dir"])]
    t = Table([[emp, num_os]], colWidths=[W * 0.58, W * 0.42])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LINEBELOW", (0, 0), (-1, 0), 1.5, COR_TINTA),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    hist += [t, Spacer(1, 8)]

    hist += [_secao("Contratante", est, W), _campos([
        ("Órgão / cliente", o["orgao"]), ("CNPJ", o["cnpj_orgao"]), ("Solicitante", o["solicitante"]),
        ("Edital", o["edital_numero"]), ("Contrato / ata", o["numero_contrato"]),
        ("Empenho / OF", f"{o['empenho_tipo'] or ''} {o['empenho_numero']}".strip() if o["empenho_numero"] else None),
    ], est, W), Spacer(1, 6)]

    prog = " ".join(x for x in (_d(o["data_programada"]), o["hora_programada"] or "") if x)
    execu = _d(o["data_execucao"])
    if o["hora_inicio"] or o["hora_fim"]:
        execu += f" · {o['hora_inicio'] or '--:--'} às {o['hora_fim'] or '--:--'}"
    hist += [_secao("Execução", est, W), _campos([
        ("Local do serviço", o["local"]), ("Programada para", prog), ("Executada em", execu),
        ("Equipe / técnico", o["equipe"]), ("Veículo / placa", o["veiculo"]), ("Tipo de serviço", o["tipo"]),
    ], est, W)]
    if o["descricao"]:
        hist += [Table([[Paragraph("<b>SERVIÇO SOLICITADO</b>", est["rot"])], [Paragraph(_esc(o["descricao"]), est["base"])]],
                       colWidths=[W], style=[("BOX", (0, 0), (-1, -1), 0.5, COR_LINHA)])]
    hist.append(Spacer(1, 6))

    # equipamentos
    hist.append(_secao("Equipamentos e serviços", est, W))
    if d["itens"]:
        dados = [[Paragraph(f"<b>{c}</b>", est["peq"]) for c in ("Descrição", "Identificação / patrimônio", "Qtd.", "Un.")]]
        for it in d["itens"]:
            dados.append([Paragraph(_esc(it["descricao"]), est["base"]), Paragraph(_esc(it["identificacao"] or "—"), est["peq"]),
                          Paragraph(_num(it["quantidade"]), est["dir"]), Paragraph(_esc(it["unidade"] or ""), est["peq"])])
        dados.append([Paragraph("<b>Total de unidades</b>", est["peq"]), "",
                      Paragraph(f"<b>{_num(sum(i['quantidade'] for i in d['itens']))}</b>", est["dir"]), ""])
        t = Table(dados, colWidths=[W * 0.46, W * 0.34, W * 0.1, W * 0.1], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), COR_SUAVE), ("GRID", (0, 0), (-1, -1), 0.5, COR_LINHA),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, -1), (-1, -1), COR_SUAVE)]))
        hist.append(t)
    else:
        hist.append(Paragraph("Nenhum equipamento listado.", est["mudo"]))
    hist.append(Spacer(1, 6))

    # checklist
    if d["checklist"]:
        hist.append(_secao("Checklist de entrega e conferência", est, W))
        dados = [[Paragraph(f"<b>{c}</b>", est["peq"] if i in (0, 4) else est["cen"]) for i, c in
                  enumerate(("Item verificado", "C", "NC", "N/A", "Observação"))]]
        estilo = [("BACKGROUND", (0, 0), (-1, 0), COR_SUAVE), ("GRID", (0, 0), (-1, -1), 0.5, COR_LINHA),
                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (3, -1), "CENTER")]
        for grupo, linhas in d["grupos"]:
            if grupo:
                dados.append([Paragraph(_esc(grupo).upper(), est["grupo"]), "", "", "", ""])
                estilo += [("SPAN", (0, len(dados) - 1), (-1, len(dados) - 1)),
                           ("BACKGROUND", (0, len(dados) - 1), (-1, len(dados) - 1), colors.HexColor("#EAF1F3"))]
            for c in linhas:
                r = c["resultado"]
                dados.append([Paragraph(_esc(c["descricao"]), est["base"]),
                              _marca("ok") if r == "ok" else "", _marca("nc") if r == "nc" else "",
                              _marca("na") if r == "na" else "", Paragraph(_esc(c["observacao"] or ""), est["peq"])])
                if r == "nc":
                    estilo.append(("BACKGROUND", (0, len(dados) - 1), (-1, len(dados) - 1), colors.HexColor("#FDF0EE")))
        t = Table(dados, colWidths=[W * 0.52, W * 0.06, W * 0.06, W * 0.06, W * 0.30], repeatRows=1)
        t.setStyle(TableStyle(estilo))
        tot = len(d["checklist"])
        ok = sum(1 for c in d["checklist"] if c["resultado"] == "ok")
        nc = sum(1 for c in d["checklist"] if c["resultado"] == "nc")
        nap = sum(1 for c in d["checklist"] if c["resultado"] == "na")
        hist += [t, Spacer(1, 2), Paragraph(f"C = conforme · NC = não conforme · N/A = não se aplica. "
                                            f"Resultado: <b>{ok}</b> conforme(s), <b>{nc}</b> não conforme(s), "
                                            f"<b>{nap}</b> não se aplica(m), <b>{tot - ok - nc - nap}</b> sem resposta.",
                                            est["mudo"]), Spacer(1, 6)]

    if o["ocorrencias"]:
        hist += [_secao("Ocorrências e observações", est, W),
                 Table([[Paragraph(_esc(o["ocorrencias"]), est["base"])]], colWidths=[W],
                       style=[("BOX", (0, 0), (-1, -1), 0.5, COR_LINHA), ("TOPPADDING", (0, 0), (-1, -1), 5),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]), Spacer(1, 6)]

    # termo e assinaturas (mantidos juntos na mesma página)
    termo = ("Declaro que os equipamentos e serviços descritos nesta ordem de serviço foram entregues/executados no local "
             "indicado e conferidos conforme o checklist acima, ressalvadas as ocorrências registradas.")
    larg_ass = W / 2 - 6
    ass_cli = _img_assinatura(o["assinatura_cliente"], larg_ass - 10, 22 * mm)
    ass_tec = _img_assinatura(o["assinatura_tecnico"], larg_ass - 10, 22 * mm)

    def bloco(img, titulo, linhas):
        conteudo = [[img], [Paragraph(f"<b>{_esc(titulo)}</b>", est["cen"])]] + [[Paragraph(_esc(x), est["mudo"])] for x in linhas if x]
        tb = Table(conteudo, colWidths=[larg_ass], rowHeights=[24 * mm] + [None] * (len(conteudo) - 1))
        tb.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), 0.8, COR_TINTA), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                ("VALIGN", (0, 0), (0, 0), "BOTTOM")]))
        return tb

    rec = [o["recebedor_nome"] or "Nome:", ("Doc.: " + o["recebedor_documento"]) if o["recebedor_documento"] else "Documento:",
           o["recebedor_cargo"] or ""]
    tec = [o["tecnico_nome"] or (o["equipe"] or "Nome:"), o["empresa"] or ""]
    ass = Table([[bloco(ass_cli, "Recebido pelo contratante", rec), bloco(ass_tec, "Responsável técnico", tec)]],
                colWidths=[W / 2, W / 2])
    ass.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    quando = (f"Assinado eletronicamente em {_d(o['assinado_em'])} às {o['assinado_em'][11:16]}"
              if o["assinado_em"] else "Local e data: ______________________________, ____/____/________")
    hist.append(KeepTogether([_secao("Termo de recebimento", est, W), Spacer(1, 4), Paragraph(termo, est["base"]),
                              Spacer(1, 4), Paragraph(quando, est["mudo"]), Spacer(1, 6), ass]))

    # fotos (2 por linha)
    fotos = [(c, leg) for c, leg in d.get("fotos_caminhos", []) if c and __import__("os").path.exists(c)]
    if fotos:
        hist += [Spacer(1, 10), _secao("Registro fotográfico", est, W), Spacer(1, 4)]
        celulas, linha = [], []
        larg_f = W / 2 - 8
        for i, (cam, leg) in enumerate(fotos, start=1):
            img = Image(cam)
            fator = min(larg_f / img.imageWidth, 62 * mm / img.imageHeight)
            img.drawWidth, img.drawHeight = img.imageWidth * fator, img.imageHeight * fator
            linha.append([img, Paragraph(f"Foto {i}" + (f" — {_esc(leg)}" if leg else ""), est["mudo"])])
            if len(linha) == 2:
                celulas.append(linha)
                linha = []
        if linha:
            linha.append("")
            celulas.append(linha)
        t = Table(celulas, colWidths=[W / 2, W / 2])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        hist.append(t)

    desenho = _cabecalho_rodape(f"OS {o['numero']} · emitida em {date.today():%d/%m/%Y}", o["empresa"], d.get("codigo"))
    doc.build(hist, onFirstPage=desenho, onLaterPages=desenho)
    buf.seek(0)
    return buf


def _filtros_texto(f):
    partes = []
    if f.get("de") or f.get("ate"):
        partes.append(f"Período: {_d(f.get('de')) or 'início'} a {_d(f.get('ate')) or 'hoje'}")
    for k, rot in (("tipo", "Tipo"), ("status", "Situação"), ("q", "Busca")):
        if f.get(k):
            partes.append(f"{rot}: {f[k]}")
    return " · ".join(partes) or "Todas as ordens de serviço"


def pdf_relatorio_os(lista, itens, filtros, edital=None):
    """Relatório consolidado das OS (para medição / prestação de contas ao contratante)."""
    est = _estilos()
    buf = BytesIO()
    margem = 12 * mm
    pag = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=pag, leftMargin=margem, rightMargin=margem, topMargin=14 * mm,
                            bottomMargin=15 * mm, title="Relatório de ordens de serviço")
    W = pag[0] - 2 * margem
    empresa = lista[0]["empresa"] if lista else ""
    titulo = "Relatório de ordens de serviço"
    sub = _filtros_texto(filtros)
    if edital:
        sub = f"Edital {edital['numero']} — {edital['orgao']}" + (f" · Contrato {edital['numero_contrato']}"
                                                                   if edital["numero_contrato"] else "") + " · " + sub
    hist = [Paragraph(_esc(titulo), est["base"].clone("tit", fontName="Helvetica-Bold", fontSize=15, leading=19)), Spacer(1, 3),
            Paragraph(_esc(sub), est["mudo"]), Spacer(1, 8)]

    # resumo por tipo e situação
    por_tipo = {}
    for o in lista:
        t = por_tipo.setdefault(o["tipo"], {"qtd": 0, "conc": 0, "un": 0, "nc": 0})
        t["qtd"] += 1
        t["conc"] += 1 if o["status"] == "Concluída" else 0
        t["un"] += o["qtd_itens"] or 0
        t["nc"] += o["ck_nc"] or 0
    dados = [[Paragraph(f"<b>{c}</b>", est["peq"] if i == 0 else est["dir"]) for i, c in
              enumerate(("Tipo de serviço", "OS", "Concluídas", "Unidades atendidas", "Não conformidades"))]]
    for tipo, v in sorted(por_tipo.items()):
        dados.append([Paragraph(_esc(tipo), est["base"]), Paragraph(str(v["qtd"]), est["dir"]),
                      Paragraph(str(v["conc"]), est["dir"]), Paragraph(_num(v["un"]), est["dir"]),
                      Paragraph(str(v["nc"]), est["dir"])])
    dados.append([Paragraph("<b>Total</b>", est["base"])] + [Paragraph(f"<b>{x}</b>", est["dir"]) for x in (
        len(lista), sum(v["conc"] for v in por_tipo.values()), _num(sum(v["un"] for v in por_tipo.values())),
        sum(v["nc"] for v in por_tipo.values()))])
    t = Table(dados, colWidths=[W * 0.4, W * 0.12, W * 0.12, W * 0.18, W * 0.18])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), COR_SUAVE), ("BACKGROUND", (0, -1), (-1, -1), COR_SUAVE),
                           ("GRID", (0, 0), (-1, -1), 0.5, COR_LINHA)]))
    hist += [_secao("Resumo", est, W), t, Spacer(1, 10), _secao("Ordens de serviço", est, W)]

    cab = ("OS", "Data", "Tipo", "Edital / órgão", "Local", "Equipamentos", "Checklist", "Recebido por", "Situação")
    larg = [0.07, 0.08, 0.11, 0.15, 0.15, 0.17, 0.08, 0.11, 0.08]
    dados = [[Paragraph(f"<b>{c}</b>", est["peq"]) for c in cab]]
    for o in lista:
        eq = "; ".join(f"{_num(i['quantidade'])} {i['descricao']}" + (f" ({i['identificacao']})" if i["identificacao"] else "")
                       for i in itens.get(o["id"], [])) or "—"
        if o["ck_total"]:
            ckt = f"{o['ck_ok']}/{o['ck_total']} C" + (f"<br/><font color='#B42318'><b>{o['ck_nc']} NC</b></font>" if o["ck_nc"] else "")
        else:
            ckt = "—"
        dados.append([Paragraph(f"<b>{_esc(o['numero'])}</b>", est["peq"]),
                      Paragraph(_d(o["data_execucao"] or o["data_programada"]), est["peq"]),
                      Paragraph(_esc(o["tipo"]), est["peq"]),
                      Paragraph(f"{_esc(o['edital_numero'])}<br/><font color='#5B6770'>{_esc(o['orgao'])}</font>", est["peq"]),
                      Paragraph(_esc(o["local"] or ""), est["peq"]), Paragraph(_esc(eq), est["peq"]),
                      Paragraph(ckt, est["peq"]),
                      Paragraph(_esc(o["recebedor_nome"] or "") + (f"<br/><font color='#5B6770'>{_d(o['assinado_em'])}</font>"
                                                                  if o["assinado_em"] else ""), est["peq"]),
                      Paragraph(_esc(o["status"]), est["peq"])])
    if len(dados) == 1:
        dados.append([Paragraph("Nenhuma ordem de serviço no filtro escolhido.", est["mudo"])] + [""] * (len(cab) - 1))
    t = Table(dados, colWidths=[W * x for x in larg], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), COR_SUAVE), ("GRID", (0, 0), (-1, -1), 0.5, COR_LINHA),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    hist.append(t)
    hist += [Spacer(1, 26), Table([["", ""], [Paragraph("Responsável pela contratada", est["cen"]),
                                              Paragraph("Fiscal do contrato (contratante)", est["cen"])]],
                                  colWidths=[W / 2 - 20, W / 2 - 20], rowHeights=[16 * mm, None], hAlign="CENTER",
                                  style=[("LINEABOVE", (0, 1), (0, 1), 0.8, COR_TINTA),
                                         ("LINEABOVE", (1, 1), (1, 1), 0.8, COR_TINTA),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 18), ("RIGHTPADDING", (0, 0), (-1, -1), 18)])]
    desenho = _cabecalho_rodape(f"{titulo} · emitido em {date.today():%d/%m/%Y}", empresa)
    doc.build(hist, onFirstPage=desenho, onLaterPages=desenho)
    buf.seek(0)
    return buf


def xlsx_pedidos(linhas):
    wb = Workbook()
    _aba(wb, "Pedidos de compra", ["Pedido", "Tipo", "Edital", "Órgão", "Solicitante", "Emissão", "Prazo", "Entregue em",
                                   "Situação", "Dias de atraso", "Quantidade", "Valor", "Local de entrega", "Distância (km)",
                                   "R$ por km", "Frete"],
         [(d["numero"], d["tipo"], d["edital_numero"], d["orgao"], d["solicitante"], _dt(d["data_emissao"]),
           _dt(d["prazo_entrega"]), _dt(d["data_entrega"]), d["prazo_rotulo"], d["dias_atraso"] or None, d["qtd_total"],
           d["valor_total"], d["local_entrega"], d["distancia_km"], d["valor_km"], d["frete"]) for d in linhas],
         {"Quantidade": FMT_NUM, "Valor": FMT_BRL, "Distância (km)": FMT_NUM, "R$ por km": FMT_BRL, "Frete": FMT_BRL},
         primeira=True)
    return _salvar(wb)


def xlsx_contas(linhas, T):
    wb = Workbook()
    _aba(wb, T["titulo"], ["Vencimento", "Descrição", "Parcela", T["pessoa_curta"], "Categoria", "Documento",
                           "Contrato", "Empresa", "Valor", "Em aberto", "Situação", T["data_q"], T["valor_q"],
                           "Forma de pagamento", "Código de barras / PIX", "Observações"],
         [(_dt(d["vencimento"]), d["descricao"], f"{d['parcela']}/{d['total_parcelas']}" if d["total_parcelas"] else None,
           d["fornecedor"], d["categoria"], d["documento"], d["edital_numero"], d["empresa"], d["valor"], d["valor_aberto"],
           d["rotulo"], _dt(d["data_pagamento"]), d["valor_pago"], d["forma_pagamento"], d["codigo_barras"],
           d["observacoes"]) for d in linhas],
         {"Vencimento": "DD/MM/YYYY", T["data_q"]: "DD/MM/YYYY", "Valor": FMT_BRL, "Em aberto": FMT_BRL,
          T["valor_q"]: FMT_BRL}, primeira=True)
    return _salvar(wb)


def xlsx_os(lista):
    wb = Workbook()
    _aba(wb, "Ordens de serviço", ["OS", "Tipo", "Situação", "Edital", "Órgão", "Empenho/OF", "Programada", "Executada",
                                   "Início", "Fim", "Local", "Equipe", "Veículo", "Unidades", "Checklist itens",
                                   "Conformes", "Não conformes", "Recebido por", "Documento", "Assinado em", "Fotos"],
         [(o["numero"], o["tipo"], o["status"], o["edital_numero"], o["orgao"], o["empenho_numero"],
           _dt(o["data_programada"]), _dt(o["data_execucao"]), o["hora_inicio"], o["hora_fim"], o["local"], o["equipe"],
           o["veiculo"], o["qtd_itens"], o["ck_total"], o["ck_ok"], o["ck_nc"], o["recebedor_nome"],
           o["recebedor_documento"], o["assinado_em"], o["qtd_fotos"]) for o in lista],
         {"Programada": "DD/MM/YYYY", "Executada": "DD/MM/YYYY", "Unidades": FMT_NUM}, primeira=True)
    return _salvar(wb)
