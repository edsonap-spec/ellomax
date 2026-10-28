"""Sistema de Controle de Licitações Ganhas.

Executar:  pip install -r requirements.txt  &&  python app.py
Acesso inicial: admin@local / admin123 (troque no primeiro acesso).
Enviar alertas por e-mail manualmente (ex.: agendador do Windows / cron):  python app.py enviar-alertas
"""
import os
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import alertas
import relatorios

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("LICITACOES_DB", os.path.join(BASE_DIR, "licitacoes.db"))
UPLOAD_DIR = os.environ.get("LICITACOES_UPLOADS", os.path.join(BASE_DIR, "uploads"))
EXTENSOES_ANEXO = {"pdf", "doc", "docx", "xls", "xlsx", "odt", "ods", "csv", "txt", "xml",
                   "jpg", "jpeg", "png", "zip", "rar", "7z", "eml", "msg"}


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE_DIR, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app = Flask(__name__)
app.config["SECRET_KEY"] = _secret_key()
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

PERFIS = {
    "admin": "Administrador",
    "operador": "Operador",
    "leitura": "Somente leitura",
}

MODALIDADES = ["Pregão Eletrônico", "Pregão Presencial", "Concorrência", "Concorrência Eletrônica",
               "Dispensa", "Dispensa Eletrônica", "Inexigibilidade", "Leilão", "Diálogo Competitivo",
               "Tomada de Preços", "Convite", "Ata de Registro de Preços (adesão)", "Outra"]
STATUS_EDITAL = ["Homologado", "Contrato assinado", "Em execução", "Suspenso", "Encerrado", "Cancelado"]
CATEGORIA_IMPOSTOS = "Impostos"
CATEGORIAS_GASTO = ["Mercadoria / insumo", "Frete / logística", CATEGORIA_IMPOSTOS, "Taxas e emolumentos",
                    "Garantia contratual", "Mão de obra", "Viagem / deslocamento", "Comissão",
                    "Outros"]
TIPOS_EMPENHO = ["Nota de empenho", "Ordem de fornecimento", "Autorização de fornecimento",
                 "Ordem de serviço", "Pedido / requisição"]
TIPOS_GARANTIA = ["Caução em dinheiro", "Seguro-garantia", "Fiança bancária", "Títulos da dívida pública"]
TIPOS_ADITIVO = ["Prorrogação de prazo", "Acréscimo de valor", "Supressão de valor", "Reajuste",
                 "Reequilíbrio econômico-financeiro", "Alteração de cláusula", "Outro"]
CATEGORIAS_ANEXO = ["Edital", "Proposta", "Ata / homologação", "Contrato", "Empenho / OF", "Nota fiscal",
                    "Garantia", "Aditivo", "Comprovante de entrega", "Comprovante de pagamento", "Outro"]

# ---------------------------------------------------------------- banco

SCHEMA = """
CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social TEXT NOT NULL,
    nome_fantasia TEXT,
    cnpj TEXT,
    aliquota_impostos REAL NOT NULL DEFAULT 0,
    observacoes TEXT,
    ativo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    perfil TEXT NOT NULL DEFAULT 'leitura',
    ativo INTEGER NOT NULL DEFAULT 1,
    trocar_senha INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS editais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orgao TEXT NOT NULL,
    cnpj_orgao TEXT,
    uasg TEXT,
    numero TEXT NOT NULL,
    processo TEXT,
    modalidade TEXT,
    objeto TEXT NOT NULL,
    data_abertura TEXT,
    data_homologacao TEXT,
    numero_contrato TEXT,
    vigencia_inicio TEXT,
    vigencia_fim TEXT,
    prazo_entrega TEXT,
    local_entrega TEXT,
    status TEXT NOT NULL DEFAULT 'Homologado',
    contato_orgao TEXT,
    responsavel TEXT,
    link_edital TEXT,
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    lote TEXT,
    numero_item TEXT,
    descricao TEXT NOT NULL,
    marca TEXT,
    unidade TEXT,
    quantidade REAL NOT NULL DEFAULT 0,
    valor_unitario REAL NOT NULL DEFAULT 0,
    custo_unitario REAL,
    qtd_entregue REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS gastos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    categoria TEXT,
    descricao TEXT NOT NULL,
    fornecedor TEXT,
    documento TEXT,
    valor REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recebimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    descricao TEXT NOT NULL,
    empenho TEXT,
    nota_fiscal TEXT,
    data_prevista TEXT,
    valor_previsto REAL NOT NULL DEFAULT 0,
    data_recebimento TEXT,
    valor_recebido REAL NOT NULL DEFAULT 0,
    observacoes TEXT
);
CREATE TABLE IF NOT EXISTS empenhos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    tipo TEXT,
    numero TEXT NOT NULL,
    data_emissao TEXT,
    prazo_entrega TEXT,
    data_entrega TEXT,
    valor REAL NOT NULL DEFAULT 0,
    observacoes TEXT
);
CREATE TABLE IF NOT EXISTS empenho_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empenho_id INTEGER NOT NULL REFERENCES empenhos(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES itens(id) ON DELETE CASCADE,
    quantidade REAL NOT NULL DEFAULT 0,
    UNIQUE (empenho_id, item_id)
);
CREATE TABLE IF NOT EXISTS garantias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    tipo TEXT,
    descricao TEXT NOT NULL,
    percentual REAL,
    valor REAL NOT NULL DEFAULT 0,
    apolice TEXT,
    seguradora TEXT,
    data_inicio TEXT,
    data_fim TEXT,
    data_devolucao TEXT,
    observacoes TEXT
);
CREATE TABLE IF NOT EXISTS aditivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    numero TEXT,
    tipo TEXT,
    descricao TEXT NOT NULL,
    data_assinatura TEXT,
    nova_vigencia_fim TEXT,
    percentual REAL,
    valor REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS anexos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    categoria TEXT,
    descricao TEXT,
    nome_original TEXT NOT NULL,
    arquivo TEXT NOT NULL,
    tamanho INTEGER,
    enviado_por TEXT,
    enviado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ativos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER REFERENCES empresas(id),
    nome TEXT NOT NULL,
    codigo TEXT,
    categoria TEXT,
    unidade TEXT,
    quantidade_total REAL NOT NULL DEFAULT 0,
    qtd_manutencao REAL NOT NULL DEFAULT 0,
    valor_unitario REAL,
    observacoes TEXT,
    ativo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS alocacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ativo_id INTEGER NOT NULL REFERENCES ativos(id) ON DELETE CASCADE,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    quantidade REAL NOT NULL,
    data_saida TEXT,
    data_prevista_retorno TEXT,
    data_retorno TEXT,
    local TEXT,
    observacoes TEXT
);
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER,
    usuario_nome TEXT,
    acao TEXT NOT NULL,
    entidade TEXT NOT NULL,
    entidade_id INTEGER,
    detalhe TEXT,
    em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db():
    if "db" not in g:
        g.db = conectar()
    return g.db


def conectar():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _add_col(db, tabela, coluna, decl):
    if coluna not in [r[1] for r in db.execute(f"PRAGMA table_info({tabela})")]:
        db.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {decl}")


def init_db():
    db = conectar()
    db.executescript(SCHEMA)
    # migrações da versão 1
    _add_col(db, "usuarios", "empresa_id", "INTEGER REFERENCES empresas(id)")
    _add_col(db, "editais", "empresa_id", "INTEGER REFERENCES empresas(id)")
    _add_col(db, "editais", "aliquota_impostos", "REAL")
    _add_col(db, "recebimentos", "retencoes", "REAL NOT NULL DEFAULT 0")
    if not db.execute("SELECT 1 FROM empresas LIMIT 1").fetchone():
        db.execute("INSERT INTO empresas (razao_social) VALUES ('Minha Empresa')")
    primeira = db.execute("SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()[0]
    db.execute("UPDATE editais SET empresa_id=? WHERE empresa_id IS NULL", (primeira,))
    if not db.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
        senha = os.environ.get("ADMIN_PASSWORD", "admin123")
        db.execute(
            "INSERT INTO usuarios (nome, email, senha_hash, perfil, trocar_senha) VALUES (?,?,?,?,1)",
            ("Administrador", "admin@local", generate_password_hash(senha), "admin"))
        print(f"Usuário inicial criado: admin@local / {senha}")
    db.commit()
    db.close()


def audit(acao, entidade, entidade_id=None, detalhe=None):
    u = g.get("user")
    get_db().execute(
        "INSERT INTO auditoria (usuario_id, usuario_nome, acao, entidade, entidade_id, detalhe) VALUES (?,?,?,?,?,?)",
        (u["id"] if u else None, u["nome"] if u else None, acao, entidade, entidade_id, detalhe))


def get_config(db=None):
    db = db or get_db()
    return {r["chave"]: r["valor"] for r in db.execute("SELECT * FROM config")}


def set_config(db, **valores):
    for k, v in valores.items():
        db.execute("INSERT INTO config (chave, valor) VALUES (?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                   (k, v))


# ---------------------------------------------------------------- formatação

def parse_num(valor):
    """Aceita '1.234,56', '1234.56' ou '1234'."""
    s = (valor or "").strip().replace("R$", "").replace("%", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"número inválido ({valor})")


@app.template_filter("brl")
def brl(v):
    v = v or 0
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < -0.004 else "R$ ") + s


@app.template_filter("num")
def num(v):
    v = v or 0
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@app.template_filter("data")
def fmt_data(v):
    if not v:
        return ""
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return v


@app.template_filter("pct")
def pct(v):
    return f"{(v or 0):.1f}%".replace(".", ",")


@app.template_filter("tamanho")
def tamanho(v):
    v = v or 0
    for un in ("B", "KB", "MB"):
        if v < 1024:
            return f"{v:.0f} {un}"
        v /= 1024
    return f"{v:.1f} GB"


# ---------------------------------------------------------------- autenticação e empresa

@app.before_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        u = get_db().execute("SELECT * FROM usuarios WHERE id=? AND ativo=1", (uid,)).fetchone()
        if u:
            g.user = u
        else:
            session.clear()
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST" and request.form.get("_csrf") != session["csrf"]:
        abort(400, "Token CSRF inválido. Recarregue a página.")
    if (g.user and g.user["trocar_senha"] and request.endpoint not in ("minha_senha", "logout", "static")):
        flash("Por segurança, defina uma nova senha antes de continuar.", "warning")
        return redirect(url_for("minha_senha"))


def empresa_atual():
    """Empresa usada para filtrar as telas (None = todas)."""
    if g.user is None:
        return None
    if g.user["empresa_id"]:
        return g.user["empresa_id"]
    return session.get("empresa_id") or None


def empresas_permitidas():
    db = get_db()
    if g.user and g.user["empresa_id"]:
        return db.execute("SELECT * FROM empresas WHERE id=?", (g.user["empresa_id"],)).fetchall()
    return db.execute("SELECT * FROM empresas WHERE ativo=1 ORDER BY razao_social").fetchall()


@app.context_processor
def inject():
    ctx = {"PERFIS": PERFIS, "csrf_token": session.get("csrf", ""), "pode_editar": pode_editar,
           "hoje": date.today().isoformat()}
    if g.get("user"):
        emp = empresa_atual()
        ctx["empresas_menu"] = empresas_permitidas()
        ctx["empresa_sel"] = emp
        ctx["empresa_restrita"] = bool(g.user["empresa_id"])
    return ctx


def pode_editar():
    return g.user is not None and g.user["perfil"] in ("admin", "operador")


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper


def perfil_required(*perfis):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapper(*a, **kw):
            if g.user["perfil"] not in perfis:
                abort(403)
            return f(*a, **kw)
        return wrapper
    return deco


editor_required = perfil_required("admin", "operador")
admin_required = perfil_required("admin")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = get_db().execute("SELECT * FROM usuarios WHERE lower(email)=? AND ativo=1", (email,)).fetchone()
        if u and check_password_hash(u["senha_hash"], request.form.get("senha", "")):
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            session["csrf"] = secrets.token_hex(16)
            g.user = u
            audit("login", "usuario", u["id"])
            get_db().commit()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("E-mail ou senha inválidos.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/empresa/<int:emp_id>")
@login_required
def trocar_empresa(emp_id):
    if not g.user["empresa_id"]:
        session["empresa_id"] = emp_id or None
    nxt = request.args.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))


@app.route("/minha-senha", methods=["GET", "POST"])
@login_required
def minha_senha():
    if request.method == "POST":
        atual, nova, conf = (request.form.get(k, "") for k in ("atual", "nova", "confirma"))
        if not check_password_hash(g.user["senha_hash"], atual):
            flash("Senha atual incorreta.", "danger")
        elif len(nova) < 8:
            flash("A nova senha deve ter pelo menos 8 caracteres.", "danger")
        elif nova != conf:
            flash("A confirmação não confere.", "danger")
        else:
            db = get_db()
            db.execute("UPDATE usuarios SET senha_hash=?, trocar_senha=0 WHERE id=?",
                       (generate_password_hash(nova), g.user["id"]))
            audit("trocou senha", "usuario", g.user["id"])
            db.commit()
            flash("Senha alterada.", "success")
            return redirect(url_for("dashboard"))
    return render_template("senha.html")


# ---------------------------------------------------------------- cálculos

def resumo_edital(eid, db=None):
    db = db or get_db()
    r = db.execute("""
        SELECT
          (SELECT COALESCE(SUM(quantidade*valor_unitario),0) FROM itens WHERE edital_id=:e) AS contratado_itens,
          (SELECT COALESCE(SUM(valor),0) FROM aditivos WHERE edital_id=:e) AS aditivos,
          (SELECT COALESCE(SUM(qtd_entregue*valor_unitario),0) FROM itens WHERE edital_id=:e) AS entregue,
          (SELECT COALESCE(SUM(quantidade*custo_unitario),0) FROM itens WHERE edital_id=:e) AS custo_estimado,
          (SELECT COALESCE(SUM(ei.quantidade*i.valor_unitario),0) FROM empenho_itens ei
             JOIN itens i ON i.id=ei.item_id WHERE i.edital_id=:e) AS empenhado_itens,
          (SELECT COALESCE(SUM(valor),0) FROM empenhos em WHERE edital_id=:e
             AND NOT EXISTS (SELECT 1 FROM empenho_itens ei WHERE ei.empenho_id=em.id)) AS empenhado_avulso,
          (SELECT COALESCE(SUM(valor),0) FROM gastos WHERE edital_id=:e) AS gastos,
          (SELECT COALESCE(SUM(valor),0) FROM gastos WHERE edital_id=:e AND categoria=:imp) AS gastos_impostos,
          (SELECT COALESCE(SUM(valor_previsto),0) FROM recebimentos WHERE edital_id=:e) AS previsto,
          (SELECT COALESCE(SUM(valor_recebido),0) FROM recebimentos WHERE edital_id=:e) AS recebido,
          (SELECT COALESCE(SUM(retencoes),0) FROM recebimentos WHERE edital_id=:e) AS retencoes,
          (SELECT COALESCE(SUM(valor_previsto - valor_recebido - retencoes),0) FROM recebimentos
             WHERE edital_id=:e AND valor_recebido + retencoes < valor_previsto - 0.004
             AND data_prevista < date('now','localtime')) AS atrasado,
          (SELECT COALESCE(ed.aliquota_impostos, emp.aliquota_impostos, 0) FROM editais ed
             LEFT JOIN empresas emp ON emp.id=ed.empresa_id WHERE ed.id=:e) AS aliquota
    """, {"e": eid, "imp": CATEGORIA_IMPOSTOS}).fetchone()
    d = dict(r)
    d["contratado"] = d["contratado_itens"] + d["aditivos"]
    d["empenhado"] = d["empenhado_itens"] + d["empenhado_avulso"]
    d["liquidado"] = d["recebido"] + d["retencoes"]
    d["a_receber"] = d["contratado"] - d["liquidado"]
    d["impostos_estimados"] = d["contratado"] * (d["aliquota"] or 0) / 100
    gastos_outros = d["gastos"] - d["gastos_impostos"]
    # projeção: usa o maior entre o que já foi lançado e o estimado, separando custo e impostos
    d["custo_previsto"] = max(gastos_outros, d["custo_estimado"]) + max(d["gastos_impostos"], d["impostos_estimados"])
    d["lucro_atual"] = d["recebido"] - d["gastos"]
    d["lucro_projetado"] = d["contratado"] - d["custo_previsto"]
    base = d["contratado"] or 0
    d["margem_projetada"] = (d["lucro_projetado"] / base * 100) if base else 0
    d["pct_entregue"] = (d["entregue"] / base * 100) if base else 0
    d["pct_recebido"] = (d["liquidado"] / base * 100) if base else 0
    d["pct_empenhado"] = (d["empenhado"] / base * 100) if base else 0
    return d


# ---------------------------------------------------------------- painel

@app.route("/")
@login_required
def dashboard():
    db = get_db()
    emp = empresa_atual()
    sql, args = "SELECT * FROM editais WHERE status != 'Cancelado'", []
    if emp:
        sql += " AND empresa_id=?"
        args.append(emp)
    editais = db.execute(sql + " ORDER BY id DESC", args).fetchall()
    chaves = ("contratado", "empenhado", "liquidado", "a_receber", "atrasado", "gastos", "lucro_projetado")
    tot = {k: 0 for k in chaves}
    linhas = []
    for e in editais:
        r = resumo_edital(e["id"])
        linhas.append((e, r))
        if e["status"] != "Encerrado":
            for k in tot:
                tot[k] += r[k]
    return render_template("dashboard.html", linhas=linhas, tot=tot, al=alertas.coletar_alertas(db, emp))


# ---------------------------------------------------------------- definições de formulários
# (nome, rótulo, tipo, obrigatório, opções, largura bootstrap)

NULOS = {"custo_unitario", "aliquota_impostos", "percentual"}  # numéricos que aceitam vazio


def campos_edital():
    emps = [(e["id"], e["razao_social"]) for e in empresas_permitidas()]
    return [
        ("empresa_id", "Empresa participante", "select_id", True, emps, 6),
        ("status", "Situação", "select", True, STATUS_EDITAL, 3),
        ("modalidade", "Modalidade", "select", False, MODALIDADES, 3),
        ("orgao", "Órgão / Entidade", "text", True, None, 6),
        ("cnpj_orgao", "CNPJ do órgão", "text", False, None, 3),
        ("uasg", "UASG / Código", "text", False, None, 3),
        ("numero", "Nº do edital", "text", True, None, 3),
        ("processo", "Nº do processo", "text", False, None, 3),
        ("numero_contrato", "Nº do contrato / ata", "text", False, None, 3),
        ("responsavel", "Responsável interno", "text", False, None, 3),
        ("objeto", "Objeto", "textarea", True, None, 12),
        ("data_abertura", "Data da sessão/abertura", "date", False, None, 3),
        ("data_homologacao", "Data da homologação", "date", False, None, 3),
        ("vigencia_inicio", "Vigência - início", "date", False, None, 3),
        ("vigencia_fim", "Vigência - fim", "date", False, None, 3),
        ("prazo_entrega", "Prazo de entrega", "text", False, None, 3),
        ("local_entrega", "Local de entrega", "text", False, None, 3),
        ("aliquota_impostos", "Alíquota de impostos (%) — vazio = da empresa", "number", False, None, 6),
        ("contato_orgao", "Contato no órgão (nome, tel., e-mail)", "text", False, None, 6),
        ("link_edital", "Link do edital / portal", "text", False, None, 6),
        ("observacoes", "Observações", "textarea", False, None, 12),
    ]


CAMPOS_ITEM = [
    ("lote", "Lote", "text", False, None, 2),
    ("numero_item", "Item", "text", False, None, 2),
    ("unidade", "Unidade", "text", False, None, 2),
    ("marca", "Marca / modelo", "text", False, None, 6),
    ("descricao", "Descrição", "textarea", True, None, 12),
    ("quantidade", "Quantidade", "number", True, None, 3),
    ("valor_unitario", "Valor unitário vencido (R$)", "money", True, None, 3),
    ("custo_unitario", "Custo unitário estimado (R$)", "money", False, None, 3),
    ("qtd_entregue", "Quantidade já entregue", "number", False, None, 3),
]

CAMPOS_GASTO = [
    ("data", "Data", "date", True, None, 3),
    ("categoria", "Categoria", "select", False, CATEGORIAS_GASTO, 3),
    ("valor", "Valor (R$)", "money", True, None, 3),
    ("documento", "Documento (NF, recibo)", "text", False, None, 3),
    ("descricao", "Descrição", "text", True, None, 8),
    ("fornecedor", "Fornecedor", "text", False, None, 4),
]

CAMPOS_RECEB = [
    ("descricao", "Descrição / parcela", "text", True, None, 6),
    ("empenho", "Nota de empenho / OF", "text", False, None, 3),
    ("nota_fiscal", "Nota fiscal", "text", False, None, 3),
    ("data_prevista", "Data prevista", "date", False, None, 3),
    ("valor_previsto", "Valor previsto / da NF (R$)", "money", True, None, 3),
    ("data_recebimento", "Data do recebimento", "date", False, None, 3),
    ("valor_recebido", "Valor recebido líquido (R$)", "money", False, None, 3),
    ("retencoes", "Retenções na fonte (IR, INSS, ISS...) (R$)", "money", False, None, 4),
    ("observacoes", "Observações", "text", False, None, 8),
]

CAMPOS_GARANTIA = [
    ("tipo", "Modalidade", "select", True, TIPOS_GARANTIA, 4),
    ("descricao", "Descrição", "text", True, None, 8),
    ("percentual", "% do contrato", "number", False, None, 2),
    ("valor", "Valor (R$)", "money", True, None, 3),
    ("apolice", "Nº apólice / documento", "text", False, None, 3),
    ("seguradora", "Seguradora / banco", "text", False, None, 4),
    ("data_inicio", "Início da vigência", "date", False, None, 3),
    ("data_fim", "Fim da vigência", "date", False, None, 3),
    ("data_devolucao", "Data da devolução / liberação", "date", False, None, 3),
    ("observacoes", "Observações", "text", False, None, 12),
]

CAMPOS_ADITIVO = [
    ("numero", "Nº do termo aditivo", "text", False, None, 3),
    ("tipo", "Tipo", "select", True, TIPOS_ADITIVO, 5),
    ("data_assinatura", "Data de assinatura", "date", False, None, 4),
    ("descricao", "Descrição", "textarea", True, None, 12),
    ("nova_vigencia_fim", "Nova data fim da vigência", "date", False, None, 4),
    ("valor", "Variação de valor (R$, negativo = supressão)", "money", False, None, 4),
    ("percentual", "Percentual (%)", "number", False, None, 4),
]
CAMPO_APLICAR_REAJUSTE = ("aplicar_itens", "Aplicar o percentual aos valores unitários de todos os itens (reajuste)",
                          "check", False, None, 12)

CAMPOS_EMPRESA = [
    ("razao_social", "Razão social", "text", True, None, 6),
    ("nome_fantasia", "Nome fantasia", "text", False, None, 3),
    ("cnpj", "CNPJ", "text", False, None, 3),
    ("aliquota_impostos", "Alíquota média de impostos sobre faturamento (%)", "number", False, None, 6),
    ("ativo", "Empresa ativa", "check", False, None, 6),
    ("observacoes", "Observações", "textarea", False, None, 12),
]

ENTIDADES = {
    "itens": ("Item vencido", CAMPOS_ITEM, "itens"),
    "gastos": ("Gasto", CAMPOS_GASTO, "gastos"),
    "recebimentos": ("Recebimento", CAMPOS_RECEB, "recebimentos"),
    "garantias": ("Garantia contratual", CAMPOS_GARANTIA, "garantias"),
    "aditivos": ("Termo aditivo", CAMPOS_ADITIVO, "aditivos"),
}


def ler_form(campos):
    dados, erros = {}, []
    for nome, rotulo, tipo, obrig, opcoes, _ in campos:
        bruto = request.form.get(nome, "").strip()
        if tipo in ("number", "money"):
            try:
                v = parse_num(bruto)
            except ValueError as e:
                erros.append(f"{rotulo}: {e}")
                v = None
            if v is None and nome not in NULOS:
                v = None if obrig else 0
        elif tipo == "check":
            v = 1 if request.form.get(nome) else 0
        elif tipo == "select_id":
            v = int(bruto) if bruto.isdigit() else None
            if v is not None and v not in [o[0] for o in opcoes]:
                erros.append(f"{rotulo}: opção inválida.")
        else:
            v = bruto or None
        if obrig and v in (None, ""):
            erros.append(f"{rotulo} é obrigatório.")
        dados[nome] = v
    return dados, erros


def valores_form(campos, row):
    valores = dict(row) if row else {}
    for nome, _, t, *_ in campos:
        if t in ("money", "number") and valores.get(nome) is not None:
            valores[nome] = num(valores[nome]) if t == "number" else f"{valores[nome]:.2f}".replace(".", ",")
    return valores


def get_edital(eid):
    """Busca o edital respeitando a empresa do usuário."""
    e = get_db().execute("SELECT * FROM editais WHERE id=?", (eid,)).fetchone()
    if not e or (g.user["empresa_id"] and e["empresa_id"] != g.user["empresa_id"]):
        abort(404)
    return e


# ---------------------------------------------------------------- editais

def consultar_editais():
    q = request.args.get("q", "").strip()
    st = request.args.get("status", "")
    sql, args = "SELECT e.*, emp.razao_social AS empresa FROM editais e LEFT JOIN empresas emp ON emp.id=e.empresa_id WHERE 1=1", []
    if q:
        sql += " AND (e.orgao LIKE ? OR e.numero LIKE ? OR e.objeto LIKE ? OR e.processo LIKE ? OR e.numero_contrato LIKE ?)"
        args += [f"%{q}%"] * 5
    if st:
        sql += " AND e.status=?"
        args.append(st)
    emp = empresa_atual()
    if emp:
        sql += " AND e.empresa_id=?"
        args.append(emp)
    sql += " ORDER BY e.id DESC"
    return q, st, [(e, resumo_edital(e["id"])) for e in get_db().execute(sql, args).fetchall()]


@app.route("/editais")
@login_required
def editais():
    q, st, linhas = consultar_editais()
    return render_template("editais.html", linhas=linhas, q=q, st=st, STATUS=STATUS_EDITAL)


@app.route("/editais/exportar.xlsx")
@login_required
def editais_xlsx():
    _, _, linhas = consultar_editais()
    return send_file(relatorios.xlsx_editais(linhas), as_attachment=True,
                     download_name=f"editais_{date.today():%Y%m%d}.xlsx")


@app.route("/editais/novo", methods=["GET", "POST"])
@editor_required
def edital_novo():
    return edital_form(None)


@app.route("/editais/<int:eid>/editar", methods=["GET", "POST"])
@editor_required
def edital_editar(eid):
    return edital_form(eid)


def edital_form(eid):
    db = get_db()
    atual = get_edital(eid) if eid else None
    campos = campos_edital()
    voltar = url_for("edital_ver", eid=eid) if eid else url_for("editais")
    if request.method == "POST":
        dados, erros = ler_form(campos)
        if erros:
            for e in erros:
                flash(e, "danger")
            return render_template("form.html", titulo="Edital", campos=campos, valores=request.form, voltar=voltar)
        cols = list(dados)
        if eid:
            db.execute(f"UPDATE editais SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                       [dados[c] for c in cols] + [eid])
            audit("editou", "edital", eid, dados["numero"])
        else:
            cur = db.execute(f"INSERT INTO editais ({', '.join(cols)}, criado_por) VALUES ({', '.join('?' * len(cols))}, ?)",
                             [dados[c] for c in cols] + [g.user["id"]])
            eid = cur.lastrowid
            audit("criou", "edital", eid, dados["numero"])
        db.commit()
        flash("Edital salvo.", "success")
        return redirect(url_for("edital_ver", eid=eid))
    valores = valores_form(campos, atual) if atual else {"status": "Homologado", "empresa_id": empresa_atual() or (campos[0][4][0][0] if campos[0][4] else None)}
    return render_template("form.html", titulo="Edital", campos=campos, valores=valores, voltar=voltar)


def carregar_edital(eid):
    db = get_db()
    e = db.execute("""SELECT e.*, emp.razao_social AS empresa, emp.cnpj AS empresa_cnpj
                      FROM editais e LEFT JOIN empresas emp ON emp.id=e.empresa_id WHERE e.id=?""", (eid,)).fetchone()
    itens = db.execute("""SELECT i.*, COALESCE((SELECT SUM(ei.quantidade) FROM empenho_itens ei WHERE ei.item_id=i.id),0) AS empenhado
                          FROM itens i WHERE edital_id=? ORDER BY lote, CAST(numero_item AS INTEGER), id""", (eid,)).fetchall()
    empenhos = db.execute("""SELECT em.*, COALESCE((SELECT SUM(ei.quantidade*i.valor_unitario) FROM empenho_itens ei
                               JOIN itens i ON i.id=ei.item_id WHERE ei.empenho_id=em.id), 0) AS valor_itens
                             FROM empenhos em WHERE edital_id=? ORDER BY data_emissao, id""", (eid,)).fetchall()
    linhas_emp = {}
    for li in db.execute("""SELECT ei.*, i.numero_item, i.lote, i.descricao, i.unidade, i.valor_unitario FROM empenho_itens ei
                            JOIN itens i ON i.id=ei.item_id JOIN empenhos em ON em.id=ei.empenho_id
                            WHERE em.edital_id=? ORDER BY i.lote, CAST(i.numero_item AS INTEGER)""", (eid,)):
        linhas_emp.setdefault(li["empenho_id"], []).append(li)
    return {
        "e": e,
        "itens": itens,
        "empenhos": empenhos,
        "linhas_emp": linhas_emp,
        "gastos": db.execute("SELECT * FROM gastos WHERE edital_id=? ORDER BY data DESC, id DESC", (eid,)).fetchall(),
        "receb": db.execute("SELECT * FROM recebimentos WHERE edital_id=? ORDER BY data_prevista, id", (eid,)).fetchall(),
        "garantias": db.execute("SELECT * FROM garantias WHERE edital_id=? ORDER BY data_inicio, id", (eid,)).fetchall(),
        "aditivos": db.execute("SELECT * FROM aditivos WHERE edital_id=? ORDER BY data_assinatura, id", (eid,)).fetchall(),
        "anexos": db.execute("SELECT * FROM anexos WHERE edital_id=? ORDER BY enviado_em DESC", (eid,)).fetchall(),
        "alocacoes": db.execute("""SELECT al.*, a.nome AS ativo_nome, a.codigo, a.unidade FROM alocacoes al
                                   JOIN ativos a ON a.id=al.ativo_id WHERE al.edital_id=?
                                   ORDER BY al.data_retorno IS NOT NULL, al.data_saida DESC, al.id DESC""", (eid,)).fetchall(),
        "gastos_cat": db.execute("""SELECT COALESCE(categoria,'Sem categoria') AS categoria, SUM(valor) AS total
                                    FROM gastos WHERE edital_id=? GROUP BY 1 ORDER BY 2 DESC""", (eid,)).fetchall(),
        "r": resumo_edital(eid),
    }


@app.route("/editais/<int:eid>")
@login_required
def edital_ver(eid):
    get_edital(eid)
    return render_template("edital.html", CATEGORIAS_ANEXO=CATEGORIAS_ANEXO, **carregar_edital(eid))


@app.route("/editais/<int:eid>/ficha.pdf")
@login_required
def edital_pdf(eid):
    e = get_edital(eid)
    nome = secure_filename(f"edital_{e['numero']}") or "edital"
    return send_file(relatorios.pdf_edital(carregar_edital(eid)), as_attachment=True, download_name=f"{nome}.pdf",
                     mimetype="application/pdf")


@app.route("/editais/<int:eid>/planilha.xlsx")
@login_required
def edital_xlsx(eid):
    e = get_edital(eid)
    nome = secure_filename(f"edital_{e['numero']}") or "edital"
    return send_file(relatorios.xlsx_edital(carregar_edital(eid)), as_attachment=True, download_name=f"{nome}.xlsx")


@app.route("/editais/<int:eid>/excluir", methods=["POST"])
@admin_required
def edital_excluir(eid):
    db = get_db()
    e = get_edital(eid)
    db.execute("DELETE FROM editais WHERE id=?", (eid,))
    audit("excluiu", "edital", eid, e["numero"])
    db.commit()
    shutil.rmtree(os.path.join(UPLOAD_DIR, str(eid)), ignore_errors=True)
    flash("Edital excluído.", "success")
    return redirect(url_for("editais"))


# ---------------------------------------------------------------- itens / gastos / recebimentos / garantias / aditivos

@app.route("/editais/<int:eid>/<tipo>/novo", methods=["GET", "POST"])
@editor_required
def filho_novo(eid, tipo):
    return filho_form(eid, tipo, None)


@app.route("/editais/<int:eid>/<tipo>/<int:fid>/editar", methods=["GET", "POST"])
@editor_required
def filho_editar(eid, tipo, fid):
    return filho_form(eid, tipo, fid)


def filho_form(eid, tipo, fid):
    if tipo not in ENTIDADES:
        abort(404)
    rotulo, campos, tabela = ENTIDADES[tipo]
    if tipo == "aditivos" and not fid:
        campos = campos + [CAMPO_APLICAR_REAJUSTE]
    db = get_db()
    e = get_edital(eid)
    atual = None
    if fid:
        atual = db.execute(f"SELECT * FROM {tabela} WHERE id=? AND edital_id=?", (fid, eid)).fetchone() or abort(404)
    voltar = url_for("edital_ver", eid=eid) + "#" + tipo
    titulo = f"{rotulo} — Edital {e['numero']}"
    if request.method == "POST":
        dados, erros = ler_form(campos)
        aplicar = dados.pop("aplicar_itens", 0)
        if aplicar and not dados.get("percentual"):
            erros.append("Informe o percentual para aplicar o reajuste aos itens.")
        if erros:
            for x in erros:
                flash(x, "danger")
            return render_template("form.html", titulo=titulo, campos=campos, valores=request.form, voltar=voltar)
        cols = list(dados)
        if fid:
            db.execute(f"UPDATE {tabela} SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                       [dados[c] for c in cols] + [fid])
            audit("editou", tabela, fid, f"edital {e['numero']}: {dados.get('descricao')}")
        else:
            cur = db.execute(f"INSERT INTO {tabela} (edital_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                             [eid] + [dados[c] for c in cols])
            fid_novo = cur.lastrowid
            audit("criou", tabela, fid_novo, f"edital {e['numero']}: {dados.get('descricao')}")
            if aplicar:
                fator = 1 + dados["percentual"] / 100
                db.execute("UPDATE itens SET valor_unitario = ROUND(valor_unitario * ?, 4) WHERE edital_id=?", (fator, eid))
                audit("reajustou itens", "edital", eid, f"{num(dados['percentual'])}% (aditivo #{fid_novo})")
                flash(f"Valores unitários dos itens reajustados em {num(dados['percentual'])}%.", "info")
        if tipo == "aditivos" and dados.get("nova_vigencia_fim") and (dados["nova_vigencia_fim"] > (e["vigencia_fim"] or "")):
            db.execute("UPDATE editais SET vigencia_fim=? WHERE id=?", (dados["nova_vigencia_fim"], eid))
            audit("prorrogou vigência", "edital", eid, f"{e['vigencia_fim'] or '—'} → {dados['nova_vigencia_fim']}")
            flash(f"Vigência do edital atualizada para {fmt_data(dados['nova_vigencia_fim'])}.", "info")
        db.commit()
        flash(f"{rotulo} salvo.", "success")
        if request.form.get("_outro"):
            return redirect(url_for("filho_novo", eid=eid, tipo=tipo))
        return redirect(voltar)
    valores = valores_form(campos, atual)
    if not atual and tipo == "gastos":
        valores["data"] = date.today().isoformat()
    if not atual and tipo == "garantias":
        valores["percentual"] = "5"
    return render_template("form.html", titulo=titulo, campos=campos, valores=valores, voltar=voltar,
                           permitir_outro=not fid)


@app.route("/editais/<int:eid>/<tipo>/<int:fid>/excluir", methods=["POST"])
@editor_required
def filho_excluir(eid, tipo, fid):
    if tipo not in ENTIDADES:
        abort(404)
    get_edital(eid)
    tabela = ENTIDADES[tipo][2]
    db = get_db()
    row = db.execute(f"SELECT * FROM {tabela} WHERE id=? AND edital_id=?", (fid, eid)).fetchone() or abort(404)
    db.execute(f"DELETE FROM {tabela} WHERE id=?", (fid,))
    audit("excluiu", tabela, fid, f"edital {eid}: {row['descricao']}")
    db.commit()
    flash("Registro excluído.", "success")
    return redirect(url_for("edital_ver", eid=eid) + "#" + tipo)


@app.route("/editais/<int:eid>/recebimentos/<int:fid>/baixar", methods=["POST"])
@editor_required
def receb_baixar(eid, fid):
    """Atalho: marca a parcela como recebida integralmente hoje (descontando retenções)."""
    get_edital(eid)
    db = get_db()
    r = db.execute("SELECT * FROM recebimentos WHERE id=? AND edital_id=?", (fid, eid)).fetchone() or abort(404)
    db.execute("""UPDATE recebimentos SET valor_recebido=valor_previsto - retencoes,
                  data_recebimento=date('now','localtime') WHERE id=?""", (fid,))
    audit("baixou", "recebimentos", fid, f"edital {eid}: {r['descricao']}")
    db.commit()
    flash("Recebimento registrado.", "success")
    return redirect(url_for("edital_ver", eid=eid) + "#recebimentos")


# ---------------------------------------------------------------- empenhos / ordens de fornecimento

def _movimentar_entregue(db, empenho_id, sinal):
    """Soma (sinal=1) ou estorna (sinal=-1) as quantidades do empenho na quantidade entregue dos itens."""
    db.execute("""UPDATE itens SET qtd_entregue = MAX(0, qtd_entregue + ? * (SELECT quantidade FROM empenho_itens ei
                  WHERE ei.item_id=itens.id AND ei.empenho_id=?))
                  WHERE id IN (SELECT item_id FROM empenho_itens WHERE empenho_id=?)""", (sinal, empenho_id, empenho_id))


@app.route("/editais/<int:eid>/empenhos/novo", methods=["GET", "POST"])
@editor_required
def empenho_novo(eid):
    return empenho_form(eid, None)


@app.route("/editais/<int:eid>/empenhos/<int:fid>/editar", methods=["GET", "POST"])
@editor_required
def empenho_editar(eid, fid):
    return empenho_form(eid, fid)


def empenho_form(eid, fid):
    db = get_db()
    e = get_edital(eid)
    atual = None
    qtd_atual = {}
    if fid:
        atual = db.execute("SELECT * FROM empenhos WHERE id=? AND edital_id=?", (fid, eid)).fetchone() or abort(404)
        qtd_atual = {r["item_id"]: r["quantidade"] for r in db.execute("SELECT * FROM empenho_itens WHERE empenho_id=?", (fid,))}
    itens = db.execute("""SELECT i.*, COALESCE((SELECT SUM(ei.quantidade) FROM empenho_itens ei
                            WHERE ei.item_id=i.id AND ei.empenho_id != ?),0) AS empenhado_outros
                          FROM itens i WHERE edital_id=? ORDER BY lote, CAST(numero_item AS INTEGER), id""", (fid or 0, eid)).fetchall()
    voltar = url_for("edital_ver", eid=eid) + "#empenhos"
    form = request.form if request.method == "POST" else None
    if request.method == "POST":
        erros = []
        numero = form.get("numero", "").strip()
        if not numero:
            erros.append("Informe o número do empenho / OF.")
        try:
            valor_manual = parse_num(form.get("valor")) or 0
        except ValueError as x:
            erros.append(f"Valor: {x}")
            valor_manual = 0
        qtds = {}
        for i in itens:
            try:
                q = parse_num(form.get(f"qtd_{i['id']}")) or 0
            except ValueError:
                erros.append(f"Quantidade inválida no item {i['numero_item'] or i['descricao'][:30]}.")
                continue
            if q < 0:
                erros.append("Quantidades não podem ser negativas.")
            elif q > 0:
                saldo = i["quantidade"] - i["empenhado_outros"]
                if q > saldo + 1e-9:
                    erros.append(f"Item {i['numero_item'] or ''} {i['descricao'][:40]}: quantidade {num(q)} maior que o saldo a empenhar ({num(saldo)}).")
                qtds[i["id"]] = q
        if erros:
            for x in erros:
                flash(x, "danger")
        else:
            dados = {
                "tipo": form.get("tipo") if form.get("tipo") in TIPOS_EMPENHO else None,
                "numero": numero,
                "data_emissao": form.get("data_emissao") or None,
                "prazo_entrega": form.get("prazo_entrega") or None,
                "data_entrega": form.get("data_entrega") or None,
                "valor": valor_manual,
                "observacoes": form.get("observacoes", "").strip() or None,
            }
            cols = list(dados)
            if fid:
                if atual["data_entrega"]:
                    _movimentar_entregue(db, fid, -1)
                db.execute(f"UPDATE empenhos SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [dados[c] for c in cols] + [fid])
                db.execute("DELETE FROM empenho_itens WHERE empenho_id=?", (fid,))
                audit("editou", "empenhos", fid, f"edital {e['numero']}: {numero}")
            else:
                fid = db.execute(f"INSERT INTO empenhos (edital_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                                 [eid] + [dados[c] for c in cols]).lastrowid
                audit("criou", "empenhos", fid, f"edital {e['numero']}: {numero}")
            db.executemany("INSERT INTO empenho_itens (empenho_id, item_id, quantidade) VALUES (?,?,?)",
                           [(fid, k, v) for k, v in qtds.items()])
            if dados["data_entrega"]:
                _movimentar_entregue(db, fid, 1)
            db.commit()
            flash("Empenho / OF salvo." + (" Quantidades entregues atualizadas nos itens." if dados["data_entrega"] else ""), "success")
            return redirect(voltar)
    valores = dict(atual) if atual else {"tipo": TIPOS_EMPENHO[0], "data_emissao": date.today().isoformat()}
    if atual and atual["valor"]:
        valores["valor"] = f"{atual['valor']:.2f}".replace(".", ",")
    if form:
        valores = form
    return render_template("empenho_form.html", e=e, itens=itens, valores=valores, qtd_atual=qtd_atual,
                           form=form, voltar=voltar, TIPOS=TIPOS_EMPENHO, novo=not atual)


@app.route("/editais/<int:eid>/empenhos/<int:fid>/excluir", methods=["POST"])
@editor_required
def empenho_excluir(eid, fid):
    get_edital(eid)
    db = get_db()
    row = db.execute("SELECT * FROM empenhos WHERE id=? AND edital_id=?", (fid, eid)).fetchone() or abort(404)
    if row["data_entrega"]:
        _movimentar_entregue(db, fid, -1)
    db.execute("DELETE FROM empenhos WHERE id=?", (fid,))
    audit("excluiu", "empenhos", fid, f"edital {eid}: {row['numero']}")
    db.commit()
    flash("Empenho / OF excluído." + (" Quantidades entregues estornadas." if row["data_entrega"] else ""), "success")
    return redirect(url_for("edital_ver", eid=eid) + "#empenhos")


@app.route("/editais/<int:eid>/empenhos/<int:fid>/entregue", methods=["POST"])
@editor_required
def empenho_entregue(eid, fid):
    get_edital(eid)
    db = get_db()
    row = db.execute("SELECT * FROM empenhos WHERE id=? AND edital_id=?", (fid, eid)).fetchone() or abort(404)
    if not row["data_entrega"]:
        db.execute("UPDATE empenhos SET data_entrega=date('now','localtime') WHERE id=?", (fid,))
        _movimentar_entregue(db, fid, 1)
        audit("marcou entregue", "empenhos", fid, f"edital {eid}: {row['numero']}")
        db.commit()
        flash("Entrega registrada e quantidades atualizadas nos itens.", "success")
    return redirect(url_for("edital_ver", eid=eid) + "#empenhos")


# ---------------------------------------------------------------- anexos

@app.route("/editais/<int:eid>/anexos", methods=["POST"])
@editor_required
def anexo_enviar(eid):
    e = get_edital(eid)
    arquivos = [f for f in request.files.getlist("arquivos") if f and f.filename]
    if not arquivos:
        flash("Selecione ao menos um arquivo.", "danger")
        return redirect(url_for("edital_ver", eid=eid) + "#anexos")
    pasta = os.path.join(UPLOAD_DIR, str(eid))
    os.makedirs(pasta, exist_ok=True)
    db = get_db()
    categoria = request.form.get("categoria") if request.form.get("categoria") in CATEGORIAS_ANEXO else None
    descricao = request.form.get("descricao", "").strip() or None
    enviados = 0
    for f in arquivos:
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in EXTENSOES_ANEXO:
            flash(f"Tipo de arquivo não permitido: {f.filename}", "danger")
            continue
        nome_disco = f"{uuid.uuid4().hex}.{ext}"
        caminho = os.path.join(pasta, nome_disco)
        f.save(caminho)
        cur = db.execute("""INSERT INTO anexos (edital_id, categoria, descricao, nome_original, arquivo, tamanho, enviado_por)
                            VALUES (?,?,?,?,?,?,?)""",
                         (eid, categoria, descricao, f.filename, nome_disco, os.path.getsize(caminho), g.user["nome"]))
        audit("anexou", "anexos", cur.lastrowid, f"edital {e['numero']}: {f.filename}")
        enviados += 1
    db.commit()
    if enviados:
        flash(f"{enviados} arquivo(s) anexado(s).", "success")
    return redirect(url_for("edital_ver", eid=eid) + "#anexos")


@app.route("/editais/<int:eid>/anexos/<int:aid>")
@login_required
def anexo_baixar(eid, aid):
    get_edital(eid)
    a = get_db().execute("SELECT * FROM anexos WHERE id=? AND edital_id=?", (aid, eid)).fetchone() or abort(404)
    return send_from_directory(os.path.join(UPLOAD_DIR, str(eid)), a["arquivo"], as_attachment=True,
                               download_name=a["nome_original"])


@app.route("/editais/<int:eid>/anexos/<int:aid>/excluir", methods=["POST"])
@editor_required
def anexo_excluir(eid, aid):
    get_edital(eid)
    db = get_db()
    a = db.execute("SELECT * FROM anexos WHERE id=? AND edital_id=?", (aid, eid)).fetchone() or abort(404)
    db.execute("DELETE FROM anexos WHERE id=?", (aid,))
    audit("excluiu", "anexos", aid, f"edital {eid}: {a['nome_original']}")
    db.commit()
    try:
        os.remove(os.path.join(UPLOAD_DIR, str(eid), a["arquivo"]))
    except OSError:
        pass
    flash("Anexo excluído.", "success")
    return redirect(url_for("edital_ver", eid=eid) + "#anexos")


@app.errorhandler(413)
def muito_grande(_e):
    flash("Arquivo muito grande (limite de 25 MB por envio).", "danger")
    return redirect(request.referrer or url_for("dashboard"))


# ---------------------------------------------------------------- estoque de ativos

CAMPOS_ATIVO_BASE = [
    ("nome", "Nome do ativo", "text", True, None, 6),
    ("codigo", "Código / patrimônio", "text", False, None, 3),
    ("categoria", "Categoria", "text", False, None, 3),
    ("unidade", "Unidade", "text", False, None, 2),
    ("quantidade_total", "Quantidade total em estoque (próprio)", "number", True, None, 4),
    ("qtd_manutencao", "Em manutenção / indisponível", "number", False, None, 3),
    ("valor_unitario", "Valor unitário (R$)", "money", False, None, 3),
    ("ativo", "Ativo em uso", "check", False, None, 3),
    ("observacoes", "Observações", "textarea", False, None, 9),
]

SQL_ESTOQUE = """SELECT a.*, emp.razao_social AS empresa,
    COALESCE((SELECT SUM(quantidade) FROM alocacoes al WHERE al.ativo_id=a.id AND COALESCE(al.data_retorno,'')=''),0) AS alocado
    FROM ativos a LEFT JOIN empresas emp ON emp.id=a.empresa_id"""


def campos_ativo():
    emps = [(e["id"], e["razao_social"]) for e in empresas_permitidas()]
    return [("empresa_id", "Empresa proprietária", "select_id", True, emps, 6)] + CAMPOS_ATIVO_BASE


def estoque(ativo_id=None, somente_ativos=False):
    sql, args = SQL_ESTOQUE + " WHERE 1=1", []
    if ativo_id:
        sql += " AND a.id=?"
        args.append(ativo_id)
    emp = g.user["empresa_id"] if ativo_id else empresa_atual()
    if emp:
        sql += " AND a.empresa_id=?"
        args.append(emp)
    if somente_ativos:
        sql += " AND a.ativo=1"
    linhas = []
    for a in get_db().execute(sql + " ORDER BY a.ativo DESC, a.categoria, a.nome", args).fetchall():
        d = dict(a)
        d["disponivel"] = d["quantidade_total"] - d["alocado"] - d["qtd_manutencao"]
        linhas.append(d)
    return linhas


def get_ativo(ativo_id):
    lista = estoque(ativo_id)
    if not lista:
        abort(404)
    return lista[0]


@app.route("/ativos")
@login_required
def ativos():
    return render_template("ativos.html", ativos=estoque())


@app.route("/ativos/exportar.xlsx")
@login_required
def ativos_xlsx():
    return send_file(relatorios.xlsx_ativos(estoque()), as_attachment=True,
                     download_name=f"estoque_ativos_{date.today():%Y%m%d}.xlsx")


@app.route("/ativos/novo", methods=["GET", "POST"])
@editor_required
def ativo_novo():
    return ativo_form(None)


@app.route("/ativos/<int:ativo_id>/editar", methods=["GET", "POST"])
@editor_required
def ativo_editar(ativo_id):
    return ativo_form(ativo_id)


def ativo_form(ativo_id):
    db = get_db()
    atual = get_ativo(ativo_id) if ativo_id else None
    campos = campos_ativo()
    voltar = url_for("ativo_ver", ativo_id=ativo_id) if ativo_id else url_for("ativos")
    if request.method == "POST":
        dados, erros = ler_form(campos)
        if atual and dados["quantidade_total"] is not None and \
                dados["quantidade_total"] < atual["alocado"] + (dados["qtd_manutencao"] or 0) - 1e-9:
            erros.append(f"A quantidade total não pode ficar menor que o alocado em contratos ({num(atual['alocado'])}) "
                         "mais o que está em manutenção.")
        if erros:
            for x in erros:
                flash(x, "danger")
            return render_template("form.html", titulo="Ativo", campos=campos, valores=request.form, voltar=voltar)
        cols = list(dados)
        if ativo_id:
            db.execute(f"UPDATE ativos SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [dados[c] for c in cols] + [ativo_id])
            audit("editou", "ativo", ativo_id, f"{dados['nome']} (total {num(dados['quantidade_total'])})")
        else:
            ativo_id = db.execute(f"INSERT INTO ativos ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                  [dados[c] for c in cols]).lastrowid
            audit("criou", "ativo", ativo_id, f"{dados['nome']} (total {num(dados['quantidade_total'])})")
        db.commit()
        flash("Ativo salvo.", "success")
        return redirect(url_for("ativo_ver", ativo_id=ativo_id))
    if atual:
        valores = valores_form(campos, atual)
    else:
        valores = {"ativo": 1, "empresa_id": empresa_atual() or (campos[0][4][0][0] if campos[0][4] else None)}
    return render_template("form.html", titulo="Ativo", campos=campos, valores=valores, voltar=voltar)


@app.route("/ativos/<int:ativo_id>")
@login_required
def ativo_ver(ativo_id):
    a = get_ativo(ativo_id)
    alocs = get_db().execute("""SELECT al.*, e.numero, e.orgao FROM alocacoes al JOIN editais e ON e.id=al.edital_id
                                WHERE al.ativo_id=? ORDER BY al.data_retorno IS NOT NULL, al.data_saida DESC, al.id DESC""",
                             (ativo_id,)).fetchall()
    return render_template("ativo.html", a=a, alocs=alocs)


@app.route("/ativos/<int:ativo_id>/excluir", methods=["POST"])
@admin_required
def ativo_excluir(ativo_id):
    a = get_ativo(ativo_id)
    db = get_db()
    db.execute("DELETE FROM ativos WHERE id=?", (ativo_id,))
    audit("excluiu", "ativo", ativo_id, a["nome"])
    db.commit()
    flash("Ativo excluído.", "success")
    return redirect(url_for("ativos"))


def editais_para_alocar():
    sql, args = "SELECT id, numero, orgao FROM editais WHERE status NOT IN ('Encerrado','Cancelado')", []
    emp = empresa_atual()
    if emp:
        sql += " AND empresa_id=?"
        args.append(emp)
    return get_db().execute(sql + " ORDER BY id DESC", args).fetchall()


@app.route("/alocacoes/nova", methods=["GET", "POST"])
@editor_required
def alocacao_nova():
    return alocacao_form(None)


@app.route("/alocacoes/<int:aid>/editar", methods=["GET", "POST"])
@editor_required
def alocacao_editar(aid):
    return alocacao_form(aid)


def _get_alocacao(aid):
    db = get_db()
    al = db.execute("SELECT * FROM alocacoes WHERE id=?", (aid,)).fetchone() or abort(404)
    get_ativo(al["ativo_id"])
    get_edital(al["edital_id"])
    return al


def alocacao_form(aid):
    db = get_db()
    atual = _get_alocacao(aid) if aid else None
    lista_ativos = estoque(somente_ativos=True)
    lista_editais = editais_para_alocar()
    if atual:  # garante que o edital/ativo atuais aparecem mesmo se encerrados/inativos
        if atual["edital_id"] not in [x["id"] for x in lista_editais]:
            lista_editais = list(lista_editais) + [get_edital(atual["edital_id"])]
        if atual["ativo_id"] not in [x["id"] for x in lista_ativos]:
            lista_ativos.append(get_ativo(atual["ativo_id"]))
    voltar = request.values.get("voltar", "")
    if not voltar.startswith("/") or voltar.startswith("//"):
        voltar = url_for("ativos")
    if request.method == "POST":
        f = request.form
        erros = []
        ativo_id = int(f.get("ativo_id")) if (f.get("ativo_id") or "").isdigit() else None
        edital_id = int(f.get("edital_id")) if (f.get("edital_id") or "").isdigit() else None
        ativo = next((x for x in lista_ativos if x["id"] == ativo_id), None)
        if not ativo:
            erros.append("Escolha o ativo.")
        if edital_id not in [x["id"] for x in lista_editais]:
            erros.append("Escolha o contrato / edital.")
        try:
            qtd = parse_num(f.get("quantidade")) or 0
        except ValueError:
            qtd = 0
        if qtd <= 0:
            erros.append("Informe uma quantidade maior que zero.")
        elif ativo:
            # o que esta alocação já ocupava volta para o disponível ao editar
            livre = ativo["disponivel"]
            if atual and atual["ativo_id"] == ativo_id and not atual["data_retorno"]:
                livre += atual["quantidade"]
            if not f.get("data_retorno") and qtd > livre + 1e-9:
                erros.append(f"Estoque insuficiente de {ativo['nome']}: disponível {num(livre)}.")
        if erros:
            for x in erros:
                flash(x, "danger")
        else:
            dados = {"ativo_id": ativo_id, "edital_id": edital_id, "quantidade": qtd,
                     "data_saida": f.get("data_saida") or None, "data_prevista_retorno": f.get("data_prevista_retorno") or None,
                     "data_retorno": f.get("data_retorno") or None, "local": f.get("local", "").strip() or None,
                     "observacoes": f.get("observacoes", "").strip() or None}
            cols = list(dados)
            if aid:
                db.execute(f"UPDATE alocacoes SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [dados[c] for c in cols] + [aid])
                audit("editou", "alocacoes", aid, f"{ativo['nome']}: {num(qtd)} → edital {edital_id}")
            else:
                aid = db.execute(f"INSERT INTO alocacoes ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                 [dados[c] for c in cols]).lastrowid
                audit("alocou", "alocacoes", aid, f"{ativo['nome']}: {num(qtd)} → edital {edital_id}")
            db.commit()
            flash("Alocação salva.", "success")
            return redirect(voltar)
    if request.method == "POST":
        valores = request.form
    elif atual:
        valores = dict(atual)
        valores["quantidade"] = num(atual["quantidade"])
    else:
        valores = {"ativo_id": request.args.get("ativo_id", ""), "edital_id": request.args.get("edital_id", ""),
                   "data_saida": date.today().isoformat()}
    return render_template("alocacao_form.html", valores=valores, ativos=lista_ativos, editais=lista_editais,
                           voltar=voltar, novo=not atual)


@app.route("/alocacoes/<int:aid>/devolver", methods=["POST"])
@editor_required
def alocacao_devolver(aid):
    """Devolve ao estoque toda a quantidade ou parte dela (a parte devolvida vira um registro encerrado)."""
    al = _get_alocacao(aid)
    db = get_db()
    voltar = request.form.get("voltar", "")
    if not voltar.startswith("/") or voltar.startswith("//"):
        voltar = url_for("ativo_ver", ativo_id=al["ativo_id"])
    if al["data_retorno"]:
        return redirect(voltar)
    try:
        qtd = parse_num(request.form.get("quantidade")) or al["quantidade"]
    except ValueError:
        qtd = 0
    if qtd <= 0 or qtd > al["quantidade"] + 1e-9:
        flash(f"Quantidade de devolução inválida (alocado: {num(al['quantidade'])}).", "danger")
        return redirect(voltar)
    data_ret = request.form.get("data_retorno") or date.today().isoformat()
    if qtd >= al["quantidade"] - 1e-9:
        db.execute("UPDATE alocacoes SET data_retorno=? WHERE id=?", (data_ret, aid))
    else:
        db.execute("UPDATE alocacoes SET quantidade=quantidade-? WHERE id=?", (qtd, aid))
        db.execute("""INSERT INTO alocacoes (ativo_id, edital_id, quantidade, data_saida, data_prevista_retorno, data_retorno, local, observacoes)
                      VALUES (?,?,?,?,?,?,?,?)""",
                   (al["ativo_id"], al["edital_id"], qtd, al["data_saida"], al["data_prevista_retorno"], data_ret, al["local"],
                    "Devolução parcial"))
    audit("devolveu", "alocacoes", aid, f"{num(qtd)} de {num(al['quantidade'])}")
    db.commit()
    flash(f"Devolução de {num(qtd)} registrada; estoque atualizado.", "success")
    return redirect(voltar)


@app.route("/alocacoes/<int:aid>/excluir", methods=["POST"])
@editor_required
def alocacao_excluir(aid):
    al = _get_alocacao(aid)
    db = get_db()
    db.execute("DELETE FROM alocacoes WHERE id=?", (aid,))
    audit("excluiu", "alocacoes", aid, f"ativo {al['ativo_id']}, edital {al['edital_id']}")
    db.commit()
    flash("Alocação excluída.", "success")
    voltar = request.form.get("voltar", "")
    return redirect(voltar if voltar.startswith("/") and not voltar.startswith("//") else url_for("ativos"))


# ---------------------------------------------------------------- empresas

@app.route("/empresas")
@admin_required
def empresas():
    lista = get_db().execute("""SELECT emp.*, (SELECT COUNT(*) FROM editais e WHERE e.empresa_id=emp.id) AS qtd_editais
                                FROM empresas emp ORDER BY ativo DESC, razao_social""").fetchall()
    return render_template("empresas.html", empresas=lista)


@app.route("/empresas/novo", methods=["GET", "POST"])
@admin_required
def empresa_nova():
    return empresa_form(None)


@app.route("/empresas/<int:emp_id>/editar", methods=["GET", "POST"])
@admin_required
def empresa_editar(emp_id):
    return empresa_form(emp_id)


def empresa_form(emp_id):
    db = get_db()
    atual = db.execute("SELECT * FROM empresas WHERE id=?", (emp_id,)).fetchone() if emp_id else None
    if emp_id and not atual:
        abort(404)
    if request.method == "POST":
        dados, erros = ler_form(CAMPOS_EMPRESA)
        dados["aliquota_impostos"] = dados["aliquota_impostos"] or 0
        if erros:
            for x in erros:
                flash(x, "danger")
            return render_template("form.html", titulo="Empresa", campos=CAMPOS_EMPRESA, valores=request.form,
                                   voltar=url_for("empresas"))
        cols = list(dados)
        if emp_id:
            db.execute(f"UPDATE empresas SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [dados[c] for c in cols] + [emp_id])
            audit("editou", "empresa", emp_id, dados["razao_social"])
        else:
            cur = db.execute(f"INSERT INTO empresas ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [dados[c] for c in cols])
            audit("criou", "empresa", cur.lastrowid, dados["razao_social"])
        db.commit()
        flash("Empresa salva.", "success")
        return redirect(url_for("empresas"))
    valores = valores_form(CAMPOS_EMPRESA, atual) if atual else {"ativo": 1}
    return render_template("form.html", titulo="Empresa", campos=CAMPOS_EMPRESA, valores=valores, voltar=url_for("empresas"))


# ---------------------------------------------------------------- usuários

@app.route("/usuarios")
@admin_required
def usuarios():
    us = get_db().execute("""SELECT u.*, emp.razao_social AS empresa FROM usuarios u
                             LEFT JOIN empresas emp ON emp.id=u.empresa_id ORDER BY u.ativo DESC, u.nome""").fetchall()
    return render_template("usuarios.html", usuarios=us)


@app.route("/usuarios/novo", methods=["GET", "POST"])
@admin_required
def usuario_novo():
    return usuario_form(None)


@app.route("/usuarios/<int:uid>/editar", methods=["GET", "POST"])
@admin_required
def usuario_editar(uid):
    return usuario_form(uid)


def usuario_form(uid):
    db = get_db()
    atual = db.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone() if uid else None
    if uid and not atual:
        abort(404)
    lista_emp = db.execute("SELECT * FROM empresas ORDER BY razao_social").fetchall()
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        perfil = request.form.get("perfil", "leitura")
        ativo = 1 if request.form.get("ativo") else 0
        senha = request.form.get("senha", "")
        emp = request.form.get("empresa_id", "")
        empresa_id = int(emp) if emp.isdigit() and int(emp) in [x["id"] for x in lista_emp] else None
        erro = None
        if not nome or not email:
            erro = "Nome e e-mail são obrigatórios."
        elif perfil not in PERFIS:
            erro = "Perfil inválido."
        elif not uid and len(senha) < 8:
            erro = "Informe uma senha inicial com pelo menos 8 caracteres."
        elif senha and len(senha) < 8:
            erro = "A senha deve ter pelo menos 8 caracteres."
        elif db.execute("SELECT 1 FROM usuarios WHERE lower(email)=? AND id != ?", (email, uid or 0)).fetchone():
            erro = "Já existe um usuário com esse e-mail."
        elif uid == g.user["id"] and (perfil != "admin" or not ativo or empresa_id):
            erro = "Você não pode reduzir o seu próprio acesso de administrador."
        if erro:
            flash(erro, "danger")
            return render_template("usuario_form.html", u=request.form, novo=not uid, empresas=lista_emp)
        if uid:
            db.execute("UPDATE usuarios SET nome=?, email=?, perfil=?, ativo=?, empresa_id=? WHERE id=?",
                       (nome, email, perfil, ativo, empresa_id, uid))
            if senha:
                db.execute("UPDATE usuarios SET senha_hash=?, trocar_senha=1 WHERE id=?", (generate_password_hash(senha), uid))
            audit("editou", "usuario", uid, f"{email} ({perfil})")
        else:
            cur = db.execute("""INSERT INTO usuarios (nome, email, senha_hash, perfil, ativo, trocar_senha, empresa_id)
                                VALUES (?,?,?,?,?,1,?)""",
                             (nome, email, generate_password_hash(senha), perfil, ativo, empresa_id))
            audit("criou", "usuario", cur.lastrowid, f"{email} ({perfil})")
        db.commit()
        flash("Usuário salvo.", "success")
        return redirect(url_for("usuarios"))
    return render_template("usuario_form.html", u=dict(atual) if atual else {"ativo": 1, "perfil": "operador"},
                           novo=not uid, empresas=lista_emp)


@app.route("/auditoria")
@admin_required
def auditoria():
    logs = get_db().execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT 500").fetchall()
    return render_template("auditoria.html", logs=logs)


# ---------------------------------------------------------------- alertas por e-mail

CHAVES_SMTP = ["smtp_host", "smtp_porta", "smtp_usuario", "smtp_remetente", "smtp_seguranca",
               "alerta_destinatarios", "alerta_ativo", "alerta_hora"]


@app.route("/configuracoes", methods=["GET", "POST"])
@admin_required
def configuracoes():
    db = get_db()
    if request.method == "POST":
        valores = {k: request.form.get(k, "").strip() for k in CHAVES_SMTP}
        valores["alerta_ativo"] = "1" if request.form.get("alerta_ativo") else "0"
        if request.form.get("smtp_senha"):
            valores["smtp_senha"] = request.form["smtp_senha"]
        set_config(db, **valores)
        audit("alterou", "configuracoes", None, "e-mail / alertas")
        db.commit()
        if request.form.get("acao") == "testar":
            try:
                n = alertas.enviar_alertas(db, forcar=True)
                flash(f"E-mail de alertas enviado ({n} pendência(s) listadas).", "success")
            except Exception as x:  # mostra o erro do servidor de e-mail ao administrador
                flash(f"Falha ao enviar: {x}", "danger")
        else:
            flash("Configurações salvas.", "success")
        return redirect(url_for("configuracoes"))
    return render_template("configuracoes.html", cfg=get_config(db))


@app.errorhandler(403)
def proibido(_e):
    return render_template("erro.html", msg="Seu perfil não tem permissão para esta ação."), 403


@app.errorhandler(404)
def nao_encontrado(_e):
    return render_template("erro.html", msg="Página ou registro não encontrado."), 404


def iniciar_agendador():
    """Verifica a cada 15 minutos se é hora de mandar o resumo diário de alertas."""
    def loop():
        while True:
            try:
                db = conectar()
                alertas.enviar_alertas(db)
                db.close()
            except Exception as x:
                print(f"[alertas] {x}")
            time.sleep(900)
    threading.Thread(target=loop, daemon=True).start()


init_db()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "enviar-alertas":
        conn = conectar()
        print(f"Alertas enviados: {alertas.enviar_alertas(conn, forcar=True)} pendência(s).")
        sys.exit(0)
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        iniciar_agendador()
    print(f"Acesse http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
