"""Coleta de pendências (painel) e envio do resumo diário por e-mail."""
import os
import smtplib
import ssl
from datetime import date, datetime
from email.message import EmailMessage
from html import escape


def coletar_alertas(db, empresa_id=None):
    filtro = " AND e.empresa_id = :emp" if empresa_id else ""
    p = {"emp": empresa_id}

    def q(sql):
        return db.execute(sql.replace("{F}", filtro), p).fetchall()

    return {
        "atrasados": q("""SELECT r.*, e.numero, e.orgao FROM recebimentos r JOIN editais e ON e.id=r.edital_id
            WHERE r.valor_recebido + r.retencoes < r.valor_previsto - 0.004
            AND r.data_prevista < date('now','localtime') {F} ORDER BY r.data_prevista"""),
        "proximos": q("""SELECT r.*, e.numero, e.orgao FROM recebimentos r JOIN editais e ON e.id=r.edital_id
            WHERE r.valor_recebido + r.retencoes < r.valor_previsto - 0.004
            AND r.data_prevista BETWEEN date('now','localtime') AND date('now','localtime','+30 days') {F}
            ORDER BY r.data_prevista"""),
        "vencendo": q("""SELECT e.* FROM editais e WHERE COALESCE(e.vigencia_fim,'') != ''
            AND e.vigencia_fim BETWEEN date('now','localtime') AND date('now','localtime','+60 days')
            AND e.status NOT IN ('Encerrado','Cancelado') {F} ORDER BY e.vigencia_fim"""),
        "garantias": q("""SELECT ga.*, e.numero, e.orgao FROM garantias ga JOIN editais e ON e.id=ga.edital_id
            WHERE COALESCE(ga.data_devolucao,'') = '' AND COALESCE(ga.data_fim,'') != ''
            AND ga.data_fim <= date('now','localtime','+30 days')
            AND e.status != 'Cancelado' {F} ORDER BY ga.data_fim"""),
        "entregas": q("""SELECT em.*, e.numero AS edital_numero, e.orgao FROM empenhos em JOIN editais e ON e.id=em.edital_id
            WHERE COALESCE(em.data_entrega,'') = '' AND COALESCE(em.prazo_entrega,'') != ''
            AND em.prazo_entrega <= date('now','localtime','+7 days') {F} ORDER BY em.prazo_entrega"""),
    }


def _brl(v):
    s = f"{abs(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if (v or 0) < 0 else "R$ ") + s


def _d(v):
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return v or ""


def montar_html(al):
    hoje = date.today().isoformat()
    secoes = [
        ("Recebimentos atrasados", al["atrasados"],
         lambda r: f"{r['numero']} — {r['orgao']}: {r['descricao']} · previsto {_d(r['data_prevista'])} · "
                   f"falta <b>{_brl(r['valor_previsto'] - r['valor_recebido'] - r['retencoes'])}</b>"),
        ("Entregas de empenhos/OF vencidas ou em até 7 dias", al["entregas"],
         lambda r: f"{r['edital_numero']} — {r['orgao']}: {r['tipo'] or 'Empenho'} {r['numero']} · prazo "
                   f"<b>{_d(r['prazo_entrega'])}</b>{' (ATRASADO)' if r['prazo_entrega'] < hoje else ''}"),
        ("Garantias vencidas ou vencendo em 30 dias", al["garantias"],
         lambda r: f"{r['numero']} — {r['orgao']}: {r['tipo'] or ''} {r['descricao']} · {_brl(r['valor'])} · "
                   f"fim <b>{_d(r['data_fim'])}</b>"),
        ("Vigências terminando em 60 dias", al["vencendo"],
         lambda r: f"{r['numero']} — {r['orgao']} · vigência até <b>{_d(r['vigencia_fim'])}</b>"),
        ("A receber nos próximos 30 dias", al["proximos"],
         lambda r: f"{r['numero']} — {r['orgao']}: {r['descricao']} · {_d(r['data_prevista'])} · "
                   f"<b>{_brl(r['valor_previsto'] - r['valor_recebido'] - r['retencoes'])}</b>"),
    ]
    partes = [f"<h2 style='font-family:sans-serif'>Controle de Licitações — pendências de {_d(hoje)}</h2>"]
    for titulo, linhas, fmt in secoes:
        if not linhas:
            continue
        itens = "".join(f"<li>{fmt({k: (escape(v) if isinstance(v, str) else v) for k, v in dict(r).items()})}</li>"
                        for r in linhas)
        partes.append(f"<h3 style='font-family:sans-serif'>{titulo} ({len(linhas)})</h3>"
                      f"<ul style='font-family:sans-serif'>{itens}</ul>")
    return "".join(partes)


def enviar_alertas(db, forcar=False):
    """Envia o resumo. Sem `forcar`, só envia uma vez por dia, depois da hora configurada.
    Retorna a quantidade de pendências listadas."""
    cfg = {r["chave"]: r["valor"] for r in db.execute("SELECT * FROM config")}
    hoje = date.today().isoformat()
    if not forcar:
        if cfg.get("alerta_ativo") != "1" or cfg.get("alerta_ultimo_envio") == hoje:
            return 0
        if datetime.now().hour < int(cfg.get("alerta_hora") or 7):
            return 0
    host = cfg.get("smtp_host")
    destinatarios = [x.strip() for x in (cfg.get("alerta_destinatarios") or "").replace(";", ",").split(",") if x.strip()]
    if not host or not destinatarios:
        raise RuntimeError("Configure o servidor SMTP e os destinatários.")
    al = coletar_alertas(db)
    total = sum(len(v) for v in al.values())
    if total or forcar:
        msg = EmailMessage()
        msg["Subject"] = f"Licitações: {total} pendência(s) em {_d(hoje)}"
        msg["From"] = cfg.get("smtp_remetente") or cfg.get("smtp_usuario")
        msg["To"] = ", ".join(destinatarios)
        msg.set_content("Abra este e-mail em um leitor com suporte a HTML.")
        msg.add_alternative(montar_html(al) if total else "<p>Nenhuma pendência hoje.</p>", subtype="html")
        porta = int(cfg.get("smtp_porta") or 587)
        seguranca = cfg.get("smtp_seguranca") or "starttls"
        senha = os.environ.get("SMTP_SENHA") or cfg.get("smtp_senha")
        if seguranca == "ssl":
            servidor = smtplib.SMTP_SSL(host, porta, context=ssl.create_default_context(), timeout=30)
        else:
            servidor = smtplib.SMTP(host, porta, timeout=30)
            if seguranca == "starttls":
                servidor.starttls(context=ssl.create_default_context())
        with servidor:
            if cfg.get("smtp_usuario"):
                servidor.login(cfg["smtp_usuario"], senha or "")
            servidor.send_message(msg)
    db.execute("INSERT INTO config (chave, valor) VALUES ('alerta_ultimo_envio', ?) "
               "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (hoje,))
    db.commit()
    return total
