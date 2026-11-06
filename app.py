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
# Pasta de dados persistentes (banco, anexos e chave de sessão). Em Docker/Coolify aponte para um volume.
DATA_DIR = os.environ.get("LICITACOES_DATA", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.environ.get("LICITACOES_DB", os.path.join(DATA_DIR, "licitacoes.db"))
UPLOAD_DIR = os.environ.get("LICITACOES_UPLOADS", os.path.join(DATA_DIR, "uploads"))
EXTENSOES_ANEXO = {"pdf", "doc", "docx", "xls", "xlsx", "odt", "ods", "csv", "txt", "xml",
                   "jpg", "jpeg", "png", "zip", "rar", "7z", "eml", "msg"}


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(DATA_DIR, ".secret_key")
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
TIPOS_EMPENHO = ["Pedido de compra", "Nota de empenho", "Ordem de fornecimento", "Autorização de fornecimento",
                 "Ordem de serviço", "Pedido / requisição"]
TIPOS_GARANTIA = ["Caução em dinheiro", "Seguro-garantia", "Fiança bancária", "Títulos da dívida pública"]
TIPOS_ADITIVO = ["Prorrogação de prazo", "Acréscimo de valor", "Supressão de valor", "Reajuste",
                 "Reequilíbrio econômico-financeiro", "Alteração de cláusula", "Outro"]
TIPOS_OS = ["Instalação / entrega", "Manutenção e limpeza", "Recolhimento", "Troca / substituição", "Vistoria",
            "Outro"]
STATUS_OS = ["Aberta", "Agendada", "Em execução", "Concluída", "Cancelada"]
RESULTADOS_CHECK = {"ok": "Conforme", "nc": "Não conforme", "na": "Não se aplica"}
EXTENSOES_FOTO = {"jpg", "jpeg", "png"}

CATEGORIAS_ANEXO = ["Edital", "Proposta", "Ata / homologação", "Contrato", "Empenho / OF", "Nota fiscal",
                    "Garantia", "Aditivo", "Comprovante de entrega", "Comprovante de pagamento", "Outro"]

# Modelos de checklist criados na primeira execução (podem ser editados em Administração → Modelos de checklist)
MODELOS_CHECKLIST_PADRAO = [
    ("Instalação de banheiro químico", "Instalação / entrega", [
        ("Posicionamento", "Local nivelado, firme e com acesso para o caminhão de manutenção"),
        ("Posicionamento", "Equipamento posicionado conforme orientação do contratante"),
        ("Posicionamento", "Equipamento estável, sem risco de tombamento"),
        ("Estrutura", "Cabine sem avarias (paredes, teto e piso)"),
        ("Estrutura", "Porta abrindo e fechando corretamente"),
        ("Estrutura", "Trinco e indicador livre/ocupado funcionando"),
        ("Estrutura", "Respiro e ventilação desobstruídos"),
        ("Higiene e insumos", "Tanque limpo e abastecido com produto químico desodorizante"),
        ("Higiene e insumos", "Vaso, assento e mictório higienizados"),
        ("Higiene e insumos", "Papel higiênico abastecido"),
        ("Higiene e insumos", "Lavatório com água e sabonete (quando houver)"),
        ("Identificação", "Adesivos de identificação e instruções de uso visíveis"),
        ("Identificação", "Números de patrimônio conferidos com a ordem de serviço"),
    ]),
    ("Manutenção e limpeza de banheiro químico", "Manutenção e limpeza", [
        ("Limpeza", "Sucção dos dejetos realizada"),
        ("Limpeza", "Lavagem interna com água sob pressão"),
        ("Limpeza", "Higienização de vaso, assento, mictório, paredes e piso"),
        ("Reposição", "Produto químico reposto no tanque"),
        ("Reposição", "Papel higiênico reposto"),
        ("Reposição", "Sabonete e papel-toalha repostos (quando houver)"),
        ("Conservação", "Porta, trinco e dobradiças verificados"),
        ("Conservação", "Avarias ou vandalismo registrados em ocorrências"),
        ("Meio ambiente", "Resíduos destinados a estação de tratamento licenciada (MTR)"),
        ("Meio ambiente", "Área ao redor deixada limpa"),
    ]),
    ("Recolhimento de equipamentos", "Recolhimento", [
        ("Conferência", "Quantidade recolhida confere com a alocada no contrato"),
        ("Conferência", "Números de patrimônio conferidos"),
        ("Limpeza", "Sucção final realizada antes da retirada"),
        ("Estado", "Equipamentos sem avarias causadas por terceiros (se houver, registrar em ocorrências)"),
        ("Local", "Local deixado limpo após a retirada"),
        ("Local", "Fotos do local registradas após a retirada"),
    ]),
    ("Entrega de contêiner", "Instalação / entrega", [
        ("Base", "Terreno nivelado e firme, com calços ou base adequada"),
        ("Base", "Contêiner posicionado conforme orientação do contratante"),
        ("Estrutura", "Portas, fechaduras e travas funcionando"),
        ("Estrutura", "Piso, paredes e forro sem avarias"),
        ("Estrutura", "Janelas e vidros íntegros"),
        ("Instalações", "Instalação elétrica testada (tomadas, iluminação e disjuntores)"),
        ("Instalações", "Ar-condicionado testado (quando houver)"),
        ("Instalações", "Instalações hidrossanitárias testadas (quando houver)"),
        ("Entrega", "Limpeza interna realizada"),
        ("Entrega", "Chaves entregues ao responsável do contratante"),
    ]),
]

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
CREATE TABLE IF NOT EXISTS ordens_servico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edital_id INTEGER NOT NULL REFERENCES editais(id) ON DELETE CASCADE,
    empenho_id INTEGER REFERENCES empenhos(id) ON DELETE SET NULL,
    ano INTEGER NOT NULL,
    sequencial INTEGER NOT NULL,
    numero TEXT NOT NULL,
    tipo TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Aberta',
    data_programada TEXT,
    hora_programada TEXT,
    data_execucao TEXT,
    hora_inicio TEXT,
    hora_fim TEXT,
    local TEXT,
    solicitante TEXT,
    equipe TEXT,
    veiculo TEXT,
    descricao TEXT,
    ocorrencias TEXT,
    recebedor_nome TEXT,
    recebedor_documento TEXT,
    recebedor_cargo TEXT,
    tecnico_nome TEXT,
    assinatura_cliente TEXT,
    assinatura_tecnico TEXT,
    assinado_em TEXT,
    criado_por INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ano, sequencial)
);
CREATE TABLE IF NOT EXISTS os_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    os_id INTEGER NOT NULL REFERENCES ordens_servico(id) ON DELETE CASCADE,
    ativo_id INTEGER REFERENCES ativos(id) ON DELETE SET NULL,
    descricao TEXT NOT NULL,
    quantidade REAL NOT NULL DEFAULT 1,
    unidade TEXT,
    identificacao TEXT
);
CREATE TABLE IF NOT EXISTS os_checklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    os_id INTEGER NOT NULL REFERENCES ordens_servico(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL DEFAULT 0,
    grupo TEXT,
    descricao TEXT NOT NULL,
    resultado TEXT,
    observacao TEXT
);
CREATE TABLE IF NOT EXISTS os_fotos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    os_id INTEGER NOT NULL REFERENCES ordens_servico(id) ON DELETE CASCADE,
    arquivo TEXT NOT NULL,
    legenda TEXT,
    enviado_por TEXT,
    enviado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS checklist_modelos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    tipo_os TEXT,
    ativo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS checklist_modelo_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    modelo_id INTEGER NOT NULL REFERENCES checklist_modelos(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL DEFAULT 0,
    grupo TEXT,
    descricao TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL CHECK (tipo IN ('pagar','receber')),
    empresa_id INTEGER REFERENCES empresas(id),
    edital_id INTEGER REFERENCES editais(id) ON DELETE SET NULL,
    descricao TEXT NOT NULL,
    fornecedor TEXT,
    categoria TEXT,
    documento TEXT,
    codigo_barras TEXT,
    vencimento TEXT NOT NULL,
    valor REAL NOT NULL DEFAULT 0,
    data_pagamento TEXT,
    valor_pago REAL,
    forma_pagamento TEXT,
    parcela INTEGER,
    total_parcelas INTEGER,
    grupo TEXT,
    gasto_id INTEGER REFERENCES gastos(id) ON DELETE SET NULL,
    anexo_nome TEXT,
    anexo_arquivo TEXT,
    observacoes TEXT,
    criado_por TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_contas_venc ON contas (tipo, vencimento);
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
    # pedidos de compra: local, solicitante, distância e frete
    _add_col(db, "empenhos", "solicitante", "TEXT")
    _add_col(db, "empenhos", "local_entrega", "TEXT")
    _add_col(db, "empenhos", "distancia_km", "REAL")
    _add_col(db, "empenhos", "valor_km", "REAL")
    if not db.execute("SELECT 1 FROM empresas LIMIT 1").fetchone():
        db.execute("INSERT INTO empresas (razao_social) VALUES ('Minha Empresa')")
    primeira = db.execute("SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()[0]
    db.execute("UPDATE editais SET empresa_id=? WHERE empresa_id IS NULL", (primeira,))
    if not db.execute("SELECT 1 FROM checklist_modelos LIMIT 1").fetchone():
        for nome, tipo, linhas in MODELOS_CHECKLIST_PADRAO:
            mid = db.execute("INSERT INTO checklist_modelos (nome, tipo_os) VALUES (?,?)", (nome, tipo)).lastrowid
            db.executemany("INSERT INTO checklist_modelo_itens (modelo_id, ordem, grupo, descricao) VALUES (?,?,?,?)",
                           [(mid, i, g_, d_) for i, (g_, d_) in enumerate(linhas, start=1)])
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
           "hoje": date.today().isoformat(), "badge_status": badge_status, "prazo_pedido": prazo_pedido,
           "frete_pedido": frete_pedido}
    if g.get("user"):
        emp = empresa_atual()
        ctx["empresas_menu"] = empresas_permitidas()
        ctx["empresa_sel"] = emp
        ctx["empresa_restrita"] = bool(g.user["empresa_id"])
        sql = """SELECT COUNT(*) FROM ordens_servico os JOIN editais e ON e.id=os.edital_id
                 WHERE os.status NOT IN ('Concluída','Cancelada') AND os.data_programada <= date('now','localtime')"""
        ctx["os_pendentes"] = get_db().execute(sql + (" AND e.empresa_id=?" if emp else ""), (emp,) if emp else ()).fetchone()[0]
        emp_ = g.user["empresa_id"] or emp
        ctx["contas_pendentes"] = {t: contas_pendentes(t, emp_) for t in TIPOS_CONTA}
    return ctx


FRETE_KM_PADRAO = 3.0


def valor_km_padrao(db=None):
    try:
        return float((get_config(db).get("frete_valor_km") or "").replace(",", ".") or FRETE_KM_PADRAO)
    except ValueError:
        return FRETE_KM_PADRAO


def frete_pedido(m):
    km = m["distancia_km"] if "distancia_km" in m.keys() else None
    return (km or 0) * (m["valor_km"] if m["valor_km"] is not None else FRETE_KM_PADRAO) if km else 0


def prazo_pedido(m):
    """Situação de prazo do pedido: (rótulo, classe do selo, dias de atraso)."""
    prazo, entrega = m["prazo_entrega"], m["data_entrega"]
    hoje_ = date.today().isoformat()
    def dias(a, b):
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    if entrega:
        if prazo and entrega[:10] > prazo[:10]:
            d = dias(prazo, entrega)
            return f"Entregue com {d} dia{'s' if d > 1 else ''} de atraso", "b-warn", d
        return ("Entregue no prazo" if prazo else "Entregue"), "b-ok", 0
    if prazo and prazo[:10] < hoje_:
        d = dias(prazo, hoje_)
        return f"Atrasado há {d} dia{'s' if d > 1 else ''}", "b-danger", d
    if prazo:
        d = dias(hoje_, prazo)
        return ("Vence hoje" if d == 0 else f"A entregar · faltam {d} dia{'s' if d > 1 else ''}"), ("b-signal" if d <= 3 else ""), 0
    return "A entregar", "", 0


TONS_STATUS = {
    # editais
    "Homologado": "b-info", "Contrato assinado": "b-brand", "Em execução": "b-signal", "Suspenso": "b-warn",
    "Encerrado": "", "Cancelado": "b-danger",
    # ordens de serviço
    "Aberta": "", "Agendada": "b-info", "Concluída": "b-ok", "Cancelada": "b-danger",
}


def badge_status(status):
    return TONS_STATUS.get(status, "")


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
    return render_template("dashboard.html", linhas=linhas, tot=tot, al=alertas.coletar_alertas(db, emp),
                           ped=painel_pedidos(), fin={t: painel_contas(t) for t in TIPOS_CONTA})


def painel_pedidos(dias=7):
    """Pedidos atrasados e próximos do prazo para o painel."""
    _, linhas, resumo = consultar_pedidos()
    limite = (date.today() + timedelta(days=dias)).isoformat()
    hoje_ = date.today().isoformat()
    atrasados = sorted((d for d in linhas if d["situacao"] == "Atrasados"), key=lambda d: -d["dias_atraso"])
    proximos = sorted((d for d in linhas if d["situacao"] == "A entregar" and d["prazo_entrega"]
                       and d["prazo_entrega"][:10] <= limite), key=lambda d: d["prazo_entrega"])
    entregues = resumo["Entregues no prazo"] + resumo["Entregues com atraso"]
    return {
        "atrasados": atrasados, "proximos": proximos, "dias": dias,
        "valor_atrasado": sum(d["valor_total"] for d in atrasados),
        "hoje": sum(1 for d in proximos if d["prazo_entrega"][:10] == hoje_),
        "sem_prazo": sum(1 for d in linhas if d["situacao"] == "A entregar" and not d["prazo_entrega"]),
        "pct_prazo": (resumo["Entregues no prazo"] / entregues * 100) if entregues else None,
        "entregues": entregues, "no_prazo": resumo["Entregues no prazo"], "total": len(linhas),
    }


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
        "ordens": db.execute("""SELECT os.*, (SELECT COUNT(*) FROM os_checklist c WHERE c.os_id=os.id) AS ck_total,
                                (SELECT COUNT(*) FROM os_checklist c WHERE c.os_id=os.id AND c.resultado='nc') AS ck_nc
                                FROM ordens_servico os WHERE os.edital_id=?
                                ORDER BY COALESCE(os.data_execucao, os.data_programada) DESC, os.id DESC""", (eid,)).fetchall(),
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
    ids_os = [x[0] for x in db.execute("SELECT id FROM ordens_servico WHERE edital_id=?", (eid,))]
    db.execute("DELETE FROM editais WHERE id=?", (eid,))
    audit("excluiu", "edital", eid, e["numero"])
    db.commit()
    shutil.rmtree(os.path.join(UPLOAD_DIR, str(eid)), ignore_errors=True)
    for os_id in ids_os:
        shutil.rmtree(os.path.join(UPLOAD_DIR, "os", str(os_id)), ignore_errors=True)
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
    voltar = request.form.get("voltar", "")
    if voltar.startswith("/") and not voltar.startswith("//"):
        return redirect(voltar)
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
        try:
            km = parse_num(form.get("distancia_km"))
            valor_km = parse_num(form.get("valor_km"))
            if valor_km is None:
                valor_km = valor_km_padrao(db)
            if (km or 0) < 0 or valor_km < 0:
                erros.append("Distância e valor por km não podem ser negativos.")
        except ValueError as x:
            erros.append(f"Frete: {x}")
            km, valor_km = None, None
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
                "solicitante": form.get("solicitante", "").strip() or None,
                "local_entrega": form.get("local_entrega", "").strip() or None,
                "distancia_km": km,
                "valor_km": valor_km,
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
            flash("Pedido salvo." + (" Quantidades entregues atualizadas nos itens." if dados["data_entrega"] else ""), "success")
            return redirect(voltar)
    valores = dict(atual) if atual else {"tipo": TIPOS_EMPENHO[0], "data_emissao": date.today().isoformat(),
                                         "local_entrega": e["local_entrega"]}
    if atual and atual["valor"]:
        valores["valor"] = f"{atual['valor']:.2f}".replace(".", ",")
    if atual and atual["distancia_km"] is not None:
        valores["distancia_km"] = num(atual["distancia_km"])
    vkm = atual["valor_km"] if atual and atual["valor_km"] is not None else valor_km_padrao(db)
    valores["valor_km"] = f"{vkm:.2f}".replace(".", ",")
    if form:
        valores = form
    return render_template("empenho_form.html", e=e, itens=itens, valores=valores, qtd_atual=qtd_atual,
                           valor_km_padrao=valor_km_padrao(db),
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
    voltar = request.form.get("voltar", "")
    if voltar.startswith("/") and not voltar.startswith("//"):
        return redirect(voltar)
    return redirect(url_for("edital_ver", eid=eid) + "#empenhos")


SQL_PEDIDOS = """SELECT em.*, e.numero AS edital_numero, e.orgao, e.empresa_id,
    COALESCE((SELECT SUM(ei.quantidade*i.valor_unitario) FROM empenho_itens ei JOIN itens i ON i.id=ei.item_id
              WHERE ei.empenho_id=em.id), 0) AS valor_itens,
    COALESCE((SELECT SUM(ei.quantidade) FROM empenho_itens ei WHERE ei.empenho_id=em.id), 0) AS qtd_total
    FROM empenhos em JOIN editais e ON e.id=em.edital_id"""

SITUACOES_PEDIDO = ["A entregar", "Atrasados", "Entregues no prazo", "Entregues com atraso"]


def consultar_pedidos():
    f = request.args
    sql, args = SQL_PEDIDOS + " WHERE 1=1", []
    q = f.get("q", "").strip()
    if q:
        sql += " AND (em.numero LIKE ? OR e.numero LIKE ? OR e.orgao LIKE ? OR em.local_entrega LIKE ? OR em.solicitante LIKE ?)"
        args += [f"%{q}%"] * 5
    if (f.get("edital_id") or "").isdigit():
        sql += " AND em.edital_id=?"
        args.append(int(f["edital_id"]))
    if f.get("de"):
        sql += " AND em.data_emissao >= ?"
        args.append(f["de"])
    if f.get("ate"):
        sql += " AND em.data_emissao <= ?"
        args.append(f["ate"])
    emp = empresa_atual()
    if emp:
        sql += " AND e.empresa_id=?"
        args.append(emp)
    linhas = []
    for m in get_db().execute(sql + " ORDER BY COALESCE(em.data_emissao, '') DESC, em.id DESC", args).fetchall():
        d = dict(m)
        d["valor_total"] = d["valor_itens"] or d["valor"] or 0
        d["frete"] = frete_pedido(m)
        d["prazo_rotulo"], d["prazo_tom"], d["dias_atraso"] = prazo_pedido(m)
        if d["data_entrega"]:
            d["situacao"] = "Entregues com atraso" if d["dias_atraso"] else "Entregues no prazo"
        else:
            d["situacao"] = "Atrasados" if d["dias_atraso"] else "A entregar"
        linhas.append(d)
    resumo = {s: 0 for s in SITUACOES_PEDIDO}
    for d in linhas:
        resumo[d["situacao"]] += 1
    st = f.get("situacao", "")
    if st in SITUACOES_PEDIDO:
        linhas = [d for d in linhas if d["situacao"] == st]
    filtros = {k: f.get(k, "") for k in ("q", "edital_id", "de", "ate", "situacao")}
    return filtros, linhas, resumo


@app.route("/pedidos")
@login_required
def pedidos():
    filtros, linhas, resumo = consultar_pedidos()
    entregues = resumo["Entregues no prazo"] + resumo["Entregues com atraso"]
    tot = {"qtd": len(linhas), "valor": sum(d["valor_total"] for d in linhas), "frete": sum(d["frete"] for d in linhas),
           "km": sum(d["distancia_km"] or 0 for d in linhas),
           "pct_prazo": (resumo["Entregues no prazo"] / entregues * 100) if entregues else None}
    return render_template("pedidos.html", linhas=linhas, f=filtros, resumo=resumo, tot=tot, SITUACOES=SITUACOES_PEDIDO,
                           editais=editais_para_os(), valor_km=valor_km_padrao())


@app.route("/pedidos/exportar.xlsx")
@login_required
def pedidos_xlsx():
    _, linhas, _ = consultar_pedidos()
    return send_file(relatorios.xlsx_pedidos(linhas), as_attachment=True,
                     download_name=f"pedidos_compra_{date.today():%Y%m%d}.xlsx")


# ---------------------------------------------------------------- financeiro: contas a pagar e a receber

TIPOS_CONTA = {
    "pagar": {"tipo": "pagar", "titulo": "Contas a pagar", "nova": "Nova conta a pagar", "pessoa": "Fornecedor / favorecido",
              "pessoa_curta": "Fornecedor", "quitadas": "Pagas", "quitada": "Paga", "acao": "Pagar", "data_q": "Pago em",
              "valor_q": "Valor pago", "icone": "bi-wallet2", "vencidas": "Vencidas",
              "sub": "Boletos, fornecedores, impostos e despesas fixas. Conta paga e ligada a um contrato entra nos gastos dele."},
    "receber": {"tipo": "receber", "titulo": "Contas a receber", "nova": "Nova conta a receber", "pessoa": "Cliente / pagador",
                "pessoa_curta": "Cliente", "quitadas": "Recebidas", "quitada": "Recebida", "acao": "Receber",
                "data_q": "Recebido em", "valor_q": "Valor recebido", "icone": "bi-cash-coin", "vencidas": "Atrasadas",
                "sub": "Locações e serviços para clientes particulares e outras entradas. Os recebimentos lançados nos "
                       "contratos públicos aparecem aqui automaticamente."},
}
CATEGORIA_CONTRATO = "Contratos públicos"
CATEGORIAS_CONTA = {
    "pagar": ["Fornecedores / mercadoria", "Frete / combustível", "Manutenção de veículos e equipamentos",
              "Folha / pró-labore", "Impostos e taxas", "Aluguel e condomínio", "Água, luz, telefone e internet",
              "Serviços de terceiros", "Empréstimos e tarifas bancárias", "Outros"],
    "receber": ["Locação de banheiros químicos", "Locação de contêineres", "Limpeza e manutenção", "Eventos",
                "Venda de produtos", "Serviços avulsos", "Reembolsos", "Outros"],
}
# categoria da conta a pagar -> categoria do gasto no contrato
CONTA_PARA_GASTO = {"Fornecedores / mercadoria": "Mercadoria / insumo", "Frete / combustível": "Frete / logística",
                    "Impostos e taxas": CATEGORIA_IMPOSTOS, "Folha / pró-labore": "Mão de obra"}
FORMAS_PAGAMENTO = ["Boleto", "PIX", "Transferência", "Cartão", "Dinheiro", "Débito automático", "Cheque"]
SITUACOES_CONTA = ["Vencidas", "Vencem hoje", "A vencer", "Quitadas"]
MODOS_LANCAMENTO = {"unica": "Conta única", "parcelada": "Parcelada (divide o valor)",
                    "mensal": "Recorrente mensal (repete o valor)"}

SQL_CONTAS = """SELECT c.*, e.numero AS edital_numero, e.orgao, emp.razao_social AS empresa
    FROM contas c LEFT JOIN editais e ON e.id=c.edital_id LEFT JOIN empresas emp ON emp.id=c.empresa_id"""
SQL_RECEB_CONTRATOS = """SELECT r.*, e.numero AS edital_numero, e.orgao, e.empresa_id, emp.razao_social AS empresa
    FROM recebimentos r JOIN editais e ON e.id=r.edital_id LEFT JOIN empresas emp ON emp.id=e.empresa_id
    WHERE e.status != 'Cancelado'"""


def tipo_conta(tipo):
    if tipo not in TIPOS_CONTA:
        abort(404)
    g.nav_conta = tipo
    return TIPOS_CONTA[tipo]


def somar_meses(d, meses):
    """Mesma data N meses depois; dia 31 vira o último dia do mês quando necessário."""
    m = d.month - 1 + meses
    ano, mes = d.year + m // 12, m % 12 + 1
    prox = date(ano + (mes == 12), mes % 12 + 1, 1)
    return date(ano, mes, min(d.day, (prox - timedelta(days=1)).day))


def situacao_conta(vencimento, quitada_em, tipo):
    """(situação, rótulo do selo, classe do selo, dias de atraso)."""
    T = TIPOS_CONTA[tipo]
    if quitada_em:
        if vencimento and quitada_em[:10] > vencimento[:10]:
            d = (date.fromisoformat(quitada_em[:10]) - date.fromisoformat(vencimento[:10])).days
            return "Quitadas", f"{T['quitada']} com {d} dia{'s' if d > 1 else ''} de atraso", "b-warn", 0
        return "Quitadas", T["quitada"], "b-ok", 0
    if not vencimento:
        return "A vencer", "Sem data prevista", "", 0
    d = (date.fromisoformat(vencimento[:10]) - date.today()).days
    if d < 0:
        rot = "Vencida" if tipo == "pagar" else "Atrasada"
        return "Vencidas", f"{rot} há {-d} dia{'s' if d < -1 else ''}", "b-danger", -d
    if d == 0:
        return "Vencem hoje", "Vence hoje", "b-signal", 0
    return "A vencer", f"Vence em {d} dia{'s' if d > 1 else ''}", ("b-signal" if d <= 3 else ""), 0


def _linha_conta(c):
    d = dict(c)
    d["origem"] = "conta"
    d["situacao"], d["rotulo"], d["tom"], d["dias_atraso"] = situacao_conta(d["vencimento"], d["data_pagamento"], d["tipo"])
    d["titulo"] = d["descricao"] + (f" ({d['parcela']}/{d['total_parcelas']})" if d["total_parcelas"] else "")
    d["valor_aberto"] = 0 if d["data_pagamento"] else d["valor"]
    return d


def _linha_recebimento(r):
    """Recebimento de contrato no mesmo formato de uma conta a receber."""
    aberto = round(r["valor_previsto"] - r["valor_recebido"] - r["retencoes"], 2)
    quitada = r["data_recebimento"] if aberto <= 0.004 else None
    d = {"origem": "contrato", "id": r["id"], "tipo": "receber", "edital_id": r["edital_id"],
         "edital_numero": r["edital_numero"], "orgao": r["orgao"], "empresa_id": r["empresa_id"], "empresa": r["empresa"],
         "descricao": r["descricao"], "titulo": r["descricao"], "fornecedor": r["orgao"], "categoria": CATEGORIA_CONTRATO,
         "documento": r["nota_fiscal"], "codigo_barras": None, "vencimento": r["data_prevista"], "valor": r["valor_previsto"],
         "data_pagamento": quitada, "valor_pago": r["valor_recebido"] + r["retencoes"] if quitada else None,
         "retencoes": r["retencoes"], "forma_pagamento": None, "parcela": None, "total_parcelas": None, "grupo": None,
         "anexo_arquivo": None, "anexo_nome": None, "observacoes": r["observacoes"],
         "valor_aberto": 0 if quitada else max(aberto, 0), "recebido_parcial": r["valor_recebido"] if not quitada else 0}
    d["situacao"], d["rotulo"], d["tom"], d["dias_atraso"] = situacao_conta(r["data_prevista"], quitada, "receber")
    if d["recebido_parcial"] > 0.004 and not quitada:
        d["rotulo"] += " · parcial"
    return d


def _empresa_filtro():
    return g.user["empresa_id"] or empresa_atual()


def listar_contas(tipo, f):
    """Todas as contas do tipo (qualquer situação) que atendem aos filtros f."""
    db = get_db()
    emp = _empresa_filtro()
    q = (f.get("q") or "").strip()
    cat = f.get("categoria") or ""
    ed = int(f["edital_id"]) if (f.get("edital_id") or "").isdigit() else None
    linhas = []
    if cat != CATEGORIA_CONTRATO:
        sql, args = SQL_CONTAS + " WHERE c.tipo=?", [tipo]
        if q:
            sql += " AND (c.descricao LIKE ? OR c.fornecedor LIKE ? OR c.documento LIKE ? OR e.numero LIKE ?)"
            args += [f"%{q}%"] * 4
        if cat in CATEGORIAS_CONTA[tipo]:
            sql += " AND c.categoria=?"
            args.append(cat)
        if ed:
            sql += " AND c.edital_id=?"
            args.append(ed)
        if f.get("de"):
            sql += " AND c.vencimento >= ?"
            args.append(f["de"])
        if f.get("ate"):
            sql += " AND c.vencimento <= ?"
            args.append(f["ate"])
        if emp:
            sql += " AND c.empresa_id=?"
            args.append(emp)
        linhas += [_linha_conta(c) for c in db.execute(sql, args)]
    if tipo == "receber" and (not cat or cat == CATEGORIA_CONTRATO):
        sql, args = SQL_RECEB_CONTRATOS, []
        if q:
            sql += " AND (r.descricao LIKE ? OR e.orgao LIKE ? OR r.nota_fiscal LIKE ? OR e.numero LIKE ?)"
            args += [f"%{q}%"] * 4
        if ed:
            sql += " AND r.edital_id=?"
            args.append(ed)
        if f.get("de"):
            sql += " AND r.data_prevista >= ?"
            args.append(f["de"])
        if f.get("ate"):
            sql += " AND r.data_prevista <= ?"
            args.append(f["ate"])
        if emp:
            sql += " AND e.empresa_id=?"
            args.append(emp)
        linhas += [_linha_recebimento(r) for r in db.execute(sql, args)]
    linhas.sort(key=lambda d: (d["vencimento"] or "9999", d["origem"], d["id"]))
    return linhas


def resumo_contas(linhas):
    resumo = {s: {"qtd": 0, "valor": 0} for s in SITUACOES_CONTA}
    for d in linhas:
        resumo[d["situacao"]]["qtd"] += 1
        resumo[d["situacao"]]["valor"] += (d["valor_pago"] or 0) if d["situacao"] == "Quitadas" else d["valor_aberto"]
    return resumo


def painel_contas(tipo, dias=7):
    """Vencidas, de hoje e dos próximos dias (em aberto) + quitado no mês."""
    limite = (date.today() + timedelta(days=dias)).isoformat()
    abertas = [d for d in listar_contas(tipo, {"ate": limite}) if d["situacao"] != "Quitadas"]
    vencidas = [d for d in abertas if d["situacao"] == "Vencidas"]
    proximas = [d for d in abertas if d["situacao"] != "Vencidas"]
    hoje_ = [d for d in proximas if d["situacao"] == "Vencem hoje"]
    quitadas_mes = [d for d in listar_contas(tipo, {})
                    if d["data_pagamento"] and d["data_pagamento"] >= date.today().replace(day=1).isoformat()]
    return {"T": TIPOS_CONTA[tipo], "abertas": abertas, "vencidas": vencidas, "proximas": proximas, "hoje": hoje_,
            "dias": dias, "valor_vencido": sum(d["valor_aberto"] for d in vencidas),
            "valor_hoje": sum(d["valor_aberto"] for d in hoje_), "valor_proximas": sum(d["valor_aberto"] for d in proximas),
            "quitado_mes": sum(d["valor_pago"] or 0 for d in quitadas_mes), "qtd_quitado_mes": len(quitadas_mes)}


def contas_pendentes(tipo, emp):
    """Quantidade vencida ou vencendo hoje (para o menu lateral)."""
    db = get_db()
    sql = "SELECT COUNT(*) FROM contas WHERE tipo=? AND data_pagamento IS NULL AND vencimento <= date('now','localtime')"
    n = db.execute(sql + (" AND empresa_id=?" if emp else ""), (tipo, emp) if emp else (tipo,)).fetchone()[0]
    if tipo == "receber":
        sql = """SELECT COUNT(*) FROM recebimentos r JOIN editais e ON e.id=r.edital_id
                 WHERE r.valor_recebido + r.retencoes < r.valor_previsto - 0.004 AND e.status != 'Cancelado'
                 AND r.data_prevista <= date('now','localtime')"""
        n += db.execute(sql + (" AND e.empresa_id=?" if emp else ""), (emp,) if emp else ()).fetchone()[0]
    return n


def get_conta(cid):
    c = get_db().execute(SQL_CONTAS + " WHERE c.id=?", (cid,)).fetchone() or abort(404)
    if g.user["empresa_id"] and c["empresa_id"] != g.user["empresa_id"]:
        abort(404)
    g.nav_conta = c["tipo"]
    return c


def _sincronizar_gasto(db, cid):
    """Conta a pagar paga e ligada a um contrato vira gasto do contrato (entra no lucro); senão o gasto sai."""
    c = db.execute("SELECT * FROM contas WHERE id=?", (cid,)).fetchone()
    if c["tipo"] == "pagar" and c["data_pagamento"] and c["edital_id"]:
        dados = (c["edital_id"], c["data_pagamento"], CONTA_PARA_GASTO.get(c["categoria"], "Outros"),
                 c["descricao"] + (f" ({c['parcela']}/{c['total_parcelas']})" if c["total_parcelas"] else ""),
                 c["fornecedor"], c["documento"], c["valor_pago"] or 0)
        existe = c["gasto_id"] and db.execute("SELECT 1 FROM gastos WHERE id=?", (c["gasto_id"],)).fetchone()
        if existe:
            db.execute("""UPDATE gastos SET edital_id=?, data=?, categoria=?, descricao=?, fornecedor=?, documento=?, valor=?
                          WHERE id=?""", dados + (c["gasto_id"],))
        else:
            gid = db.execute("""INSERT INTO gastos (edital_id, data, categoria, descricao, fornecedor, documento, valor)
                                VALUES (?,?,?,?,?,?,?)""", dados).lastrowid
            db.execute("UPDATE contas SET gasto_id=? WHERE id=?", (gid, cid))
    elif c["gasto_id"]:
        db.execute("DELETE FROM gastos WHERE id=?", (c["gasto_id"],))
        db.execute("UPDATE contas SET gasto_id=NULL WHERE id=?", (cid,))


def _pasta_contas():
    pasta = os.path.join(UPLOAD_DIR, "contas")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _remover_anexo_conta(arquivo):
    if arquivo:
        try:
            os.remove(os.path.join(_pasta_contas(), arquivo))
        except OSError:
            pass


def _voltar_seguro(valor, padrao):
    return valor if valor and valor.startswith("/") and not valor.startswith("//") else padrao


@app.route("/contas/<tipo>")
@login_required
def contas(tipo):
    T = tipo_conta(tipo)
    f = request.args
    linhas = listar_contas(tipo, f)
    resumo = resumo_contas(linhas)
    st = f.get("situacao", "")
    if st == "Em aberto":
        linhas = [d for d in linhas if d["situacao"] != "Quitadas"]
    elif st in SITUACOES_CONTA:
        linhas = [d for d in linhas if d["situacao"] == st]
    filtros = {k: f.get(k, "") for k in ("q", "categoria", "edital_id", "de", "ate", "situacao")}
    tot = {"qtd": len(linhas), "valor": sum(d["valor"] for d in linhas),
           "aberto": sum(d["valor_aberto"] for d in linhas),
           "quitado": sum(d["valor_pago"] or 0 for d in linhas if d["data_pagamento"])}
    categorias = CATEGORIAS_CONTA[tipo] + ([CATEGORIA_CONTRATO] if tipo == "receber" else [])
    return render_template("contas.html", T=T, linhas=linhas, f=filtros, resumo=resumo, tot=tot, pc=painel_contas(tipo),
                           SITUACOES=SITUACOES_CONTA, CATEGORIAS=categorias, editais=editais_para_os())


@app.route("/contas/<tipo>/exportar.xlsx")
@login_required
def contas_xlsx(tipo):
    T = tipo_conta(tipo)
    linhas = listar_contas(tipo, request.args)
    st = request.args.get("situacao", "")
    if st == "Em aberto":
        linhas = [d for d in linhas if d["situacao"] != "Quitadas"]
    elif st in SITUACOES_CONTA:
        linhas = [d for d in linhas if d["situacao"] == st]
    return send_file(relatorios.xlsx_contas(linhas, T), as_attachment=True,
                     download_name=f"contas_a_{tipo}_{date.today():%Y%m%d}.xlsx")


@app.route("/contas/<tipo>/nova", methods=["GET", "POST"])
@editor_required
def conta_nova(tipo):
    tipo_conta(tipo)
    return conta_form(tipo, None)


@app.route("/contas/<int:cid>/editar", methods=["GET", "POST"])
@editor_required
def conta_editar(cid):
    atual = get_conta(cid)
    return conta_form(atual["tipo"], atual)


def conta_form(tipo, atual):
    T = TIPOS_CONTA[tipo]
    db = get_db()
    cid = atual["id"] if atual else None
    empresas_ = empresas_permitidas()
    ids_emp = {e["id"] for e in empresas_}
    editais_ = editais_para_os(atual["edital_id"] if atual else None) if tipo == "pagar" else []
    ids_ed = {e["id"] for e in editais_}
    voltar = _voltar_seguro(request.values.get("voltar", ""), url_for("contas", tipo=tipo))
    form = request.form if request.method == "POST" else None
    if form:
        erros = []
        descricao = form.get("descricao", "").strip()
        if not descricao:
            erros.append("Informe a descrição da conta.")
        try:
            venc = date.fromisoformat(form.get("vencimento", ""))
        except ValueError:
            venc = None
            erros.append("Informe a data de vencimento.")
        try:
            valor = parse_num(form.get("valor")) or 0
            valor_pago = parse_num(form.get("valor_pago"))
        except ValueError as x:
            erros.append(f"Valor: {x}")
            valor, valor_pago = 0, None
        if valor <= 0:
            erros.append("O valor da conta deve ser maior que zero.")
        emp_id = int(form["empresa_id"]) if (form.get("empresa_id") or "").isdigit() else None
        if emp_id not in ids_emp:
            erros.append("Escolha a empresa.")
        ed_id = int(form["edital_id"]) if (form.get("edital_id") or "").isdigit() else None
        if ed_id not in ids_ed:
            ed_id = None
        data_pag = form.get("data_pagamento") or None
        if data_pag and valor_pago is None:
            valor_pago = valor
        modo = form.get("modo") if form.get("modo") in MODOS_LANCAMENTO and not atual else "unica"
        try:
            n = int(form.get("qtd_parcelas") or 1)
        except ValueError:
            n = 0
        if modo != "unica" and not 2 <= n <= 120:
            erros.append("Informe de 2 a 120 parcelas / meses.")
        if erros:
            for x in erros:
                flash(x, "danger")
        else:
            comum = {
                "empresa_id": emp_id, "edital_id": ed_id, "descricao": descricao,
                "fornecedor": form.get("fornecedor", "").strip() or None,
                "categoria": form.get("categoria") if form.get("categoria") in CATEGORIAS_CONTA[tipo] else None,
                "documento": form.get("documento", "").strip() or None,
                "codigo_barras": form.get("codigo_barras", "").strip() or None,
                "forma_pagamento": form.get("forma_pagamento") if form.get("forma_pagamento") in FORMAS_PAGAMENTO else None,
                "observacoes": form.get("observacoes", "").strip() or None,
            }
            arq = request.files.get("anexo")
            anexo = None
            if arq and arq.filename:
                ext = arq.filename.rsplit(".", 1)[-1].lower() if "." in arq.filename else ""
                if ext in EXTENSOES_ANEXO | EXTENSOES_FOTO:
                    nome_disco = f"{uuid.uuid4().hex}.{ext}"
                    arq.save(os.path.join(_pasta_contas(), nome_disco))
                    anexo = (arq.filename, nome_disco)
                else:
                    flash(f"Tipo de arquivo não permitido: {arq.filename}. A conta foi salva sem o anexo.", "warning")
            if atual:
                dados = dict(comum, vencimento=venc.isoformat(), valor=valor, data_pagamento=data_pag,
                             valor_pago=valor_pago if data_pag else None)
                if anexo:
                    _remover_anexo_conta(atual["anexo_arquivo"])
                    dados["anexo_nome"], dados["anexo_arquivo"] = anexo
                elif form.get("remover_anexo"):
                    _remover_anexo_conta(atual["anexo_arquivo"])
                    dados["anexo_nome"] = dados["anexo_arquivo"] = None
                cols = list(dados)
                db.execute(f"UPDATE contas SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                           [dados[c] for c in cols] + [cid])
                _sincronizar_gasto(db, cid)
                audit("editou", "contas", cid, f"a {tipo}: {descricao}")
                msg = "Conta atualizada."
            else:
                if modo == "unica":
                    valores_ = [(venc, valor)]
                elif modo == "parcelada":
                    base = round(valor / n, 2)
                    valores_ = [(somar_meses(venc, i), base) for i in range(n - 1)]
                    valores_.append((somar_meses(venc, n - 1), round(valor - base * (n - 1), 2)))
                else:
                    valores_ = [(somar_meses(venc, i), valor) for i in range(n)]
                grupo = uuid.uuid4().hex if len(valores_) > 1 else None
                for i, (v_, val_) in enumerate(valores_, start=1):
                    pago_ = data_pag if i == 1 else None
                    dados = dict(comum, tipo=tipo, vencimento=v_.isoformat(), valor=val_, data_pagamento=pago_,
                                 valor_pago=(valor_pago if modo == "unica" else val_) if pago_ else None,
                                 parcela=i if grupo else None, total_parcelas=len(valores_) if grupo else None,
                                 grupo=grupo, criado_por=g.user["nome"])
                    if anexo and i == 1:
                        dados["anexo_nome"], dados["anexo_arquivo"] = anexo
                    cols = list(dados)
                    nid = db.execute(f"INSERT INTO contas ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                     [dados[c] for c in cols]).lastrowid
                    _sincronizar_gasto(db, nid)
                    audit("criou", "contas", nid, f"a {tipo}: {dados['descricao']}")
                msg = (f"{len(valores_)} parcelas lançadas, de {fmt_data(valores_[0][0].isoformat())} a "
                       f"{fmt_data(valores_[-1][0].isoformat())}." if grupo else "Conta lançada.")
            db.commit()
            flash(msg + (" O pagamento entrou nos gastos do contrato." if ed_id and data_pag else ""), "success")
            return redirect(voltar)
    if form:
        valores = form
    elif atual:
        valores = dict(atual)
        valores["valor"] = f"{atual['valor']:.2f}".replace(".", ",")
        if atual["valor_pago"] is not None:
            valores["valor_pago"] = f"{atual['valor_pago']:.2f}".replace(".", ",")
    else:
        valores = {"empresa_id": empresa_atual() or (empresas_[0]["id"] if empresas_ else None),
                   "edital_id": request.args.get("edital_id", ""), "modo": "unica", "qtd_parcelas": "2"}
    return render_template("conta_form.html", T=T, valores=valores, atual=atual, empresas=empresas_, editais=editais_,
                           voltar=voltar, CATEGORIAS=CATEGORIAS_CONTA[tipo], FORMAS=FORMAS_PAGAMENTO,
                           MODOS=MODOS_LANCAMENTO)


@app.route("/contas/<int:cid>/quitar", methods=["POST"])
@editor_required
def conta_quitar(cid):
    c = get_conta(cid)
    db = get_db()
    if not c["data_pagamento"]:
        db.execute("UPDATE contas SET data_pagamento=date('now','localtime'), valor_pago=valor WHERE id=?", (cid,))
        _sincronizar_gasto(db, cid)
        audit("pagou" if c["tipo"] == "pagar" else "recebeu", "contas", cid, f"{c['descricao']} · {brl(c['valor'])}")
        db.commit()
        verbo = "Pagamento" if c["tipo"] == "pagar" else "Recebimento"
        flash(f"{verbo} de {brl(c['valor'])} registrado com a data de hoje.", "success")
    return redirect(_voltar_seguro(request.form.get("voltar"), url_for("contas", tipo=c["tipo"])))


@app.route("/contas/<int:cid>/estornar", methods=["POST"])
@editor_required
def conta_estornar(cid):
    c = get_conta(cid)
    db = get_db()
    if c["data_pagamento"]:
        db.execute("UPDATE contas SET data_pagamento=NULL, valor_pago=NULL WHERE id=?", (cid,))
        _sincronizar_gasto(db, cid)
        audit("estornou", "contas", cid, c["descricao"])
        db.commit()
        flash("Baixa desfeita. A conta voltou a ficar em aberto.", "success")
    return redirect(_voltar_seguro(request.form.get("voltar"), url_for("contas", tipo=c["tipo"])))


@app.route("/contas/<int:cid>/excluir", methods=["POST"])
@editor_required
def conta_excluir(cid):
    c = get_conta(cid)
    db = get_db()
    alvos = [c]
    if request.form.get("todas_abertas") and c["grupo"]:
        alvos = db.execute("SELECT * FROM contas WHERE grupo=? AND (id=? OR data_pagamento IS NULL)",
                           (c["grupo"], cid)).fetchall()
    for a in alvos:
        if a["gasto_id"]:
            db.execute("DELETE FROM gastos WHERE id=?", (a["gasto_id"],))
        db.execute("DELETE FROM contas WHERE id=?", (a["id"],))
        _remover_anexo_conta(a["anexo_arquivo"])
        audit("excluiu", "contas", a["id"], f"a {c['tipo']}: {a['descricao']}")
    db.commit()
    flash(f"{len(alvos)} contas excluídas." if len(alvos) > 1 else "Conta excluída.", "success")
    return redirect(url_for("contas", tipo=c["tipo"]))


@app.route("/contas/<int:cid>/anexo")
@login_required
def conta_anexo(cid):
    c = get_conta(cid)
    if not c["anexo_arquivo"]:
        abort(404)
    return send_from_directory(_pasta_contas(), c["anexo_arquivo"], as_attachment=True, download_name=c["anexo_nome"])


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


# ---------------------------------------------------------------- ordens de serviço

SQL_OS = """SELECT os.*, e.numero AS edital_numero, e.orgao, e.cnpj_orgao, e.numero_contrato, e.empresa_id,
    emp.razao_social AS empresa, emp.cnpj AS empresa_cnpj, em.numero AS empenho_numero, em.tipo AS empenho_tipo,
    (SELECT COUNT(*) FROM os_checklist c WHERE c.os_id=os.id) AS ck_total,
    (SELECT COUNT(*) FROM os_checklist c WHERE c.os_id=os.id AND c.resultado='ok') AS ck_ok,
    (SELECT COUNT(*) FROM os_checklist c WHERE c.os_id=os.id AND c.resultado='nc') AS ck_nc,
    (SELECT COUNT(*) FROM os_checklist c WHERE c.os_id=os.id AND c.resultado='na') AS ck_na,
    (SELECT COALESCE(SUM(quantidade),0) FROM os_itens oi WHERE oi.os_id=os.id) AS qtd_itens,
    (SELECT COUNT(*) FROM os_fotos f WHERE f.os_id=os.id) AS qtd_fotos
    FROM ordens_servico os JOIN editais e ON e.id=os.edital_id
    LEFT JOIN empresas emp ON emp.id=e.empresa_id LEFT JOIN empenhos em ON em.id=os.empenho_id"""


def get_os(os_id):
    o = get_db().execute(SQL_OS + " WHERE os.id=?", (os_id,)).fetchone()
    if not o or (g.user["empresa_id"] and o["empresa_id"] != g.user["empresa_id"]):
        abort(404)
    return o


def os_editavel(o):
    """Depois de assinada, a OS fica travada até ser reaberta por um administrador."""
    if o["assinado_em"]:
        flash("Esta OS já foi assinada pelo cliente. Para alterar, um administrador precisa reabri-la.", "warning")
        return False
    return True


def carregar_os(os_id):
    db = get_db()
    o = get_os(os_id)
    checklist = db.execute("SELECT * FROM os_checklist WHERE os_id=? ORDER BY ordem, id", (os_id,)).fetchall()
    grupos = []
    for c in checklist:
        if not grupos or grupos[-1][0] != (c["grupo"] or ""):
            grupos.append((c["grupo"] or "", []))
        grupos[-1][1].append(c)
    return {
        "o": o,
        "edital": db.execute("SELECT * FROM editais WHERE id=?", (o["edital_id"],)).fetchone(),
        "itens": db.execute("""SELECT oi.*, a.codigo FROM os_itens oi LEFT JOIN ativos a ON a.id=oi.ativo_id
                               WHERE oi.os_id=? ORDER BY oi.id""", (os_id,)).fetchall(),
        "checklist": checklist,
        "grupos": grupos,
        "fotos": db.execute("SELECT * FROM os_fotos WHERE os_id=? ORDER BY id", (os_id,)).fetchall(),
    }


def codigo_verificacao(o):
    import hashlib
    base = f"{o['id']}|{o['numero']}|{o['assinado_em']}|{(o['assinatura_cliente'] or '')[-200:]}"
    return hashlib.sha256(base.encode()).hexdigest()[:10].upper()


def consultar_os():
    f = request.args
    sql, args = SQL_OS + " WHERE 1=1", []
    q = f.get("q", "").strip()
    if q:
        sql += " AND (os.numero LIKE ? OR e.numero LIKE ? OR e.orgao LIKE ? OR os.local LIKE ? OR os.equipe LIKE ?)"
        args += [f"%{q}%"] * 5
    if f.get("status") in STATUS_OS:
        sql += " AND os.status=?"
        args.append(f["status"])
    if f.get("tipo") in TIPOS_OS:
        sql += " AND os.tipo=?"
        args.append(f["tipo"])
    if (f.get("edital_id") or "").isdigit():
        sql += " AND os.edital_id=?"
        args.append(int(f["edital_id"]))
    data_ref = "COALESCE(os.data_execucao, os.data_programada, substr(os.criado_em,1,10))"
    if f.get("de"):
        sql += f" AND {data_ref} >= ?"
        args.append(f["de"])
    if f.get("ate"):
        sql += f" AND {data_ref} <= ?"
        args.append(f["ate"])
    emp = empresa_atual()
    if emp:
        sql += " AND e.empresa_id=?"
        args.append(emp)
    sql += f" ORDER BY {data_ref} DESC, os.id DESC"
    filtros = {k: f.get(k, "") for k in ("q", "status", "tipo", "edital_id", "de", "ate")}
    return filtros, get_db().execute(sql, args).fetchall()


def editais_para_os(incluir_id=None):
    sql, args = "SELECT id, numero, orgao, local_entrega FROM editais WHERE (status != 'Cancelado' OR id=?)", [incluir_id or 0]
    emp = empresa_atual()
    if g.user["empresa_id"]:
        emp = g.user["empresa_id"]
    if emp:
        sql += " AND empresa_id=?"
        args.append(emp)
    return get_db().execute(sql + " ORDER BY id DESC", args).fetchall()


@app.route("/os")
@login_required
def os_lista():
    filtros, lista = consultar_os()
    resumo = {s: 0 for s in STATUS_OS}
    for o in lista:
        resumo[o["status"]] = resumo.get(o["status"], 0) + 1
    return render_template("os_lista.html", lista=lista, f=filtros, resumo=resumo, STATUS=STATUS_OS, TIPOS=TIPOS_OS,
                           editais=editais_para_os())


@app.route("/os/exportar.xlsx")
@login_required
def os_xlsx():
    _, lista = consultar_os()
    return send_file(relatorios.xlsx_os(lista), as_attachment=True, download_name=f"ordens_servico_{date.today():%Y%m%d}.xlsx")


@app.route("/os/relatorio.pdf")
@login_required
def os_relatorio_pdf():
    filtros, lista = consultar_os()
    edital = None
    if filtros["edital_id"]:
        edital = get_edital(int(filtros["edital_id"]))
    itens = {}
    if lista:
        marc = ",".join("?" * len(lista))
        for li in get_db().execute(f"SELECT * FROM os_itens WHERE os_id IN ({marc}) ORDER BY id", [o["id"] for o in lista]):
            itens.setdefault(li["os_id"], []).append(li)
    return send_file(relatorios.pdf_relatorio_os(lista, itens, filtros, edital), as_attachment=True,
                     download_name=f"relatorio_os_{date.today():%Y%m%d}.pdf", mimetype="application/pdf")


@app.route("/os/nova", methods=["GET", "POST"])
@editor_required
def os_nova():
    return os_form(None)


@app.route("/os/<int:os_id>/editar", methods=["GET", "POST"])
@editor_required
def os_editar(os_id):
    o = get_os(os_id)
    if not os_editavel(o):
        return redirect(url_for("os_ver", os_id=os_id))
    return os_form(o)


CAMPOS_OS_TEXTO = ["data_programada", "hora_programada", "data_execucao", "hora_inicio", "hora_fim", "local",
                   "solicitante", "equipe", "veiculo", "descricao", "ocorrencias"]


def os_form(atual):
    db = get_db()
    lista_editais = editais_para_os(atual["edital_id"] if atual else None)
    ids_editais = [x["id"] for x in lista_editais]
    empenhos = db.execute(f"""SELECT id, edital_id, tipo, numero FROM empenhos
                              WHERE edital_id IN ({','.join('?' * len(ids_editais)) or 'NULL'}) ORDER BY id DESC""",
                          ids_editais).fetchall()
    modelos = db.execute("SELECT * FROM checklist_modelos WHERE ativo=1 ORDER BY nome").fetchall()
    voltar = request.values.get("voltar", "")
    if not voltar.startswith("/") or voltar.startswith("//"):
        voltar = url_for("os_ver", os_id=atual["id"]) if atual else url_for("os_lista")
    if request.method == "POST":
        f = request.form
        erros = []
        edital_id = int(f["edital_id"]) if (f.get("edital_id") or "").isdigit() else None
        if edital_id not in ids_editais:
            erros.append("Escolha o contrato / edital.")
        empenho_id = int(f["empenho_id"]) if (f.get("empenho_id") or "").isdigit() else None
        if empenho_id and not any(m["id"] == empenho_id and m["edital_id"] == edital_id for m in empenhos):
            erros.append("O empenho / OF escolhido não pertence a este contrato.")
        tipo = f.get("tipo")
        if tipo not in TIPOS_OS:
            erros.append("Escolha o tipo de serviço.")
        status = f.get("status") if f.get("status") in STATUS_OS else "Aberta"
        dados = {k: (f.get(k, "").strip() or None) for k in CAMPOS_OS_TEXTO}
        if status == "Aberta" and dados["data_programada"]:
            status = "Agendada"
        if erros:
            for x in erros:
                flash(x, "danger")
        else:
            dados.update({"edital_id": edital_id, "empenho_id": empenho_id, "tipo": tipo, "status": status})
            cols = list(dados)
            if atual:
                db.execute(f"UPDATE ordens_servico SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                           [dados[c] for c in cols] + [atual["id"]])
                os_id = atual["id"]
                audit("editou", "ordem de serviço", os_id, atual["numero"])
            else:
                ano = int((dados["data_programada"] or date.today().isoformat())[:4])
                seq = db.execute("SELECT COALESCE(MAX(sequencial),0)+1 FROM ordens_servico WHERE ano=?", (ano,)).fetchone()[0]
                numero = f"{seq:04d}/{ano}"
                os_id = db.execute(f"""INSERT INTO ordens_servico ({', '.join(cols)}, ano, sequencial, numero, criado_por)
                                       VALUES ({', '.join('?' * len(cols))}, ?, ?, ?, ?)""",
                                   [dados[c] for c in cols] + [ano, seq, numero, g.user["id"]]).lastrowid
                modelo_id = int(f["modelo_id"]) if (f.get("modelo_id") or "").isdigit() else None
                if modelo_id:
                    db.execute("""INSERT INTO os_checklist (os_id, ordem, grupo, descricao)
                                  SELECT ?, ordem, grupo, descricao FROM checklist_modelo_itens WHERE modelo_id=?""",
                               (os_id, modelo_id))
                if f.get("importar_ativos"):
                    _importar_ativos(db, os_id, edital_id)
                audit("criou", "ordem de serviço", os_id, f"OS {numero} ({tipo})")
            db.commit()
            flash("Ordem de serviço salva.", "success")
            return redirect(url_for("os_ver", os_id=os_id))
    if request.method == "POST":
        valores = request.form
    elif atual:
        valores = dict(atual)
    else:
        eid = request.args.get("edital_id", "")
        tipo = request.args.get("tipo") if request.args.get("tipo") in TIPOS_OS else TIPOS_OS[0]
        local = next((x["local_entrega"] for x in lista_editais if str(x["id"]) == eid), None)
        modelo = min((m["id"] for m in modelos if m["tipo_os"] == tipo), default="")
        valores = {"edital_id": eid, "empenho_id": request.args.get("empenho_id", ""), "tipo": tipo,
                   "status": "Aberta", "data_programada": date.today().isoformat(), "local": local or "",
                   "modelo_id": modelo, "importar_ativos": "1"}
    return render_template("os_form.html", valores=valores, editais=lista_editais, empenhos=empenhos, modelos=modelos,
                           TIPOS=TIPOS_OS, STATUS=STATUS_OS, novo=not atual, o=atual, voltar=voltar)


def _importar_ativos(db, os_id, edital_id):
    linhas = db.execute("""SELECT al.ativo_id, a.nome, a.unidade, a.codigo, SUM(al.quantidade) AS qtd FROM alocacoes al
                           JOIN ativos a ON a.id=al.ativo_id WHERE al.edital_id=? AND COALESCE(al.data_retorno,'')=''
                           GROUP BY al.ativo_id ORDER BY a.nome""", (edital_id,)).fetchall()
    db.executemany("INSERT INTO os_itens (os_id, ativo_id, descricao, quantidade, unidade) VALUES (?,?,?,?,?)",
                   [(os_id, x["ativo_id"], x["nome"], x["qtd"], x["unidade"]) for x in linhas])
    return len(linhas)


@app.route("/os/<int:os_id>")
@login_required
def os_ver(os_id):
    d = carregar_os(os_id)
    ativos_lista = estoque(somente_ativos=True)
    return render_template("os_ver.html", ativos=ativos_lista, RESULTADOS=RESULTADOS_CHECK, STATUS=STATUS_OS,
                           codigo=codigo_verificacao(d["o"]) if d["o"]["assinado_em"] else None, **d)


@app.route("/os/<int:os_id>/documento.pdf")
@login_required
def os_pdf(os_id):
    d = carregar_os(os_id)
    o = d["o"]
    d["fotos_caminhos"] = [(os.path.join(UPLOAD_DIR, "os", str(os_id), f["arquivo"]), f["legenda"]) for f in d["fotos"]]
    d["codigo"] = codigo_verificacao(o) if o["assinado_em"] else None
    nome = secure_filename(f"OS_{o['numero'].replace('/', '-')}") or "os"
    return send_file(relatorios.pdf_os(d), as_attachment=request.args.get("baixar") == "1", download_name=f"{nome}.pdf",
                     mimetype="application/pdf")


@app.route("/os/<int:os_id>/excluir", methods=["POST"])
@editor_required
def os_excluir(os_id):
    o = get_os(os_id)
    if o["assinado_em"] and g.user["perfil"] != "admin":
        abort(403)
    db = get_db()
    db.execute("DELETE FROM ordens_servico WHERE id=?", (os_id,))
    audit("excluiu", "ordem de serviço", os_id, o["numero"])
    db.commit()
    shutil.rmtree(os.path.join(UPLOAD_DIR, "os", str(os_id)), ignore_errors=True)
    flash(f"OS {o['numero']} excluída.", "success")
    return redirect(url_for("os_lista"))


@app.route("/os/<int:os_id>/status", methods=["POST"])
@editor_required
def os_status(os_id):
    o = get_os(os_id)
    novo = request.form.get("status")
    if novo not in STATUS_OS or not os_editavel(o):
        return redirect(url_for("os_ver", os_id=os_id))
    db = get_db()
    extra = ""
    if novo == "Em execução" and not o["data_execucao"]:
        agora = datetime.now()
        db.execute("UPDATE ordens_servico SET data_execucao=?, hora_inicio=COALESCE(hora_inicio, ?) WHERE id=?",
                   (agora.date().isoformat(), agora.strftime("%H:%M"), os_id))
        extra = " Início registrado agora."
    db.execute("UPDATE ordens_servico SET status=? WHERE id=?", (novo, os_id))
    audit("mudou situação", "ordem de serviço", os_id, f"{o['numero']}: {o['status']} → {novo}")
    db.commit()
    flash(f"Situação alterada para {novo}.{extra}", "success")
    return redirect(url_for("os_ver", os_id=os_id))


@app.route("/os/<int:os_id>/itens", methods=["POST"])
@editor_required
def os_item_add(os_id):
    o = get_os(os_id)
    if not os_editavel(o):
        return redirect(url_for("os_ver", os_id=os_id))
    db = get_db()
    f = request.form
    if f.get("acao") == "importar":
        n = _importar_ativos(db, os_id, o["edital_id"])
        db.commit()
        flash(f"{n} ativo(s) alocado(s) no contrato incluído(s)." if n else "Não há ativos alocados neste contrato.",
              "success" if n else "warning")
        return redirect(url_for("os_ver", os_id=os_id) + "#equipamentos")
    ativo_id = int(f["ativo_id"]) if (f.get("ativo_id") or "").isdigit() else None
    ativo = get_ativo(ativo_id) if ativo_id else None
    descricao = f.get("descricao", "").strip() or (ativo["nome"] if ativo else "")
    try:
        qtd = parse_num(f.get("quantidade")) or 1
    except ValueError:
        qtd = 0
    if not descricao or qtd <= 0:
        flash("Informe o equipamento/serviço e uma quantidade maior que zero.", "danger")
    else:
        db.execute("INSERT INTO os_itens (os_id, ativo_id, descricao, quantidade, unidade, identificacao) VALUES (?,?,?,?,?,?)",
                   (os_id, ativo_id, descricao, qtd, f.get("unidade", "").strip() or (ativo["unidade"] if ativo else None),
                    f.get("identificacao", "").strip() or None))
        audit("incluiu item", "ordem de serviço", os_id, f"{o['numero']}: {num(qtd)} × {descricao}")
        db.commit()
    return redirect(url_for("os_ver", os_id=os_id) + "#equipamentos")


@app.route("/os/<int:os_id>/itens/<int:item_id>", methods=["POST"])
@editor_required
def os_item_salvar(os_id, item_id):
    o = get_os(os_id)
    if not os_editavel(o):
        return redirect(url_for("os_ver", os_id=os_id))
    db = get_db()
    it = db.execute("SELECT * FROM os_itens WHERE id=? AND os_id=?", (item_id, os_id)).fetchone() or abort(404)
    if request.form.get("acao") == "excluir":
        db.execute("DELETE FROM os_itens WHERE id=?", (item_id,))
        audit("excluiu item", "ordem de serviço", os_id, f"{o['numero']}: {it['descricao']}")
    else:
        try:
            qtd = parse_num(request.form.get("quantidade")) or it["quantidade"]
        except ValueError:
            qtd = it["quantidade"]
        db.execute("UPDATE os_itens SET quantidade=?, identificacao=? WHERE id=?",
                   (qtd, request.form.get("identificacao", "").strip() or None, item_id))
    db.commit()
    return redirect(url_for("os_ver", os_id=os_id) + "#equipamentos")


@app.route("/os/<int:os_id>/checklist", methods=["POST"])
@editor_required
def os_checklist_salvar(os_id):
    o = get_os(os_id)
    if not os_editavel(o):
        return redirect(url_for("os_ver", os_id=os_id))
    db = get_db()
    f = request.form
    if f.get("acao") == "adicionar":
        desc = f.get("nova_descricao", "").strip()
        if desc:
            ordem = db.execute("SELECT COALESCE(MAX(ordem),0)+1 FROM os_checklist WHERE os_id=?", (os_id,)).fetchone()[0]
            db.execute("INSERT INTO os_checklist (os_id, ordem, grupo, descricao) VALUES (?,?,?,?)",
                       (os_id, ordem, f.get("novo_grupo", "").strip() or "Itens adicionais", desc))
            db.commit()
        return redirect(url_for("os_ver", os_id=os_id) + "#checklist")
    n = 0
    for c in db.execute("SELECT id FROM os_checklist WHERE os_id=?", (os_id,)).fetchall():
        res = f.get(f"res_{c['id']}")
        db.execute("UPDATE os_checklist SET resultado=?, observacao=? WHERE id=?",
                   (res if res in RESULTADOS_CHECK else None, f.get(f"obs_{c['id']}", "").strip() or None, c["id"]))
        n += 1 if res in RESULTADOS_CHECK else 0
    if f.get("ocorrencias") is not None:
        db.execute("UPDATE ordens_servico SET ocorrencias=? WHERE id=?", (f.get("ocorrencias", "").strip() or None, os_id))
    if (f.get("excluir") or "").isdigit():
        db.execute("DELETE FROM os_checklist WHERE id=? AND os_id=?", (int(f["excluir"]), os_id))
        db.commit()
        return redirect(url_for("os_ver", os_id=os_id) + "#checklist")
    audit("preencheu checklist", "ordem de serviço", os_id, f"{o['numero']}: {n} de {o['ck_total']} itens")
    db.commit()
    flash("Checklist salvo.", "success")
    return redirect(url_for("os_ver", os_id=os_id) + ("#assinatura" if f.get("seguir") else "#checklist"))


@app.route("/os/<int:os_id>/fotos", methods=["POST"])
@editor_required
def os_foto_enviar(os_id):
    o = get_os(os_id)
    if not os_editavel(o):
        return redirect(url_for("os_ver", os_id=os_id))
    pasta = os.path.join(UPLOAD_DIR, "os", str(os_id))
    os.makedirs(pasta, exist_ok=True)
    db = get_db()
    legenda = request.form.get("legenda", "").strip() or None
    enviados = 0
    for arq in request.files.getlist("fotos"):
        if not arq or not arq.filename:
            continue
        ext = arq.filename.rsplit(".", 1)[-1].lower() if "." in arq.filename else ""
        if ext not in EXTENSOES_FOTO:
            flash(f"Envie fotos em JPG ou PNG ({arq.filename}).", "danger")
            continue
        nome = f"{uuid.uuid4().hex}.jpg"
        try:
            _salvar_foto(arq, os.path.join(pasta, nome))
        except Exception:
            flash(f"Não foi possível ler a imagem {arq.filename}.", "danger")
            continue
        db.execute("INSERT INTO os_fotos (os_id, arquivo, legenda, enviado_por) VALUES (?,?,?,?)",
                   (os_id, nome, legenda, g.user["nome"]))
        enviados += 1
    if enviados:
        audit("anexou fotos", "ordem de serviço", os_id, f"{o['numero']}: {enviados}")
        db.commit()
        flash(f"{enviados} foto(s) anexada(s).", "success")
    return redirect(url_for("os_ver", os_id=os_id) + "#fotos")


def _salvar_foto(arq, destino):
    """Reduz fotos de celular para no máximo 1600 px e grava em JPEG (corrige a rotação EXIF)."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(arq.stream))
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    img.save(destino, "JPEG", quality=82, optimize=True)


@app.route("/os/<int:os_id>/fotos/<int:foto_id>")
@login_required
def os_foto(os_id, foto_id):
    get_os(os_id)
    ft = get_db().execute("SELECT * FROM os_fotos WHERE id=? AND os_id=?", (foto_id, os_id)).fetchone() or abort(404)
    return send_from_directory(os.path.join(UPLOAD_DIR, "os", str(os_id)), ft["arquivo"])


@app.route("/os/<int:os_id>/fotos/<int:foto_id>/excluir", methods=["POST"])
@editor_required
def os_foto_excluir(os_id, foto_id):
    o = get_os(os_id)
    if not os_editavel(o):
        return redirect(url_for("os_ver", os_id=os_id))
    db = get_db()
    ft = db.execute("SELECT * FROM os_fotos WHERE id=? AND os_id=?", (foto_id, os_id)).fetchone() or abort(404)
    db.execute("DELETE FROM os_fotos WHERE id=?", (foto_id,))
    audit("excluiu foto", "ordem de serviço", os_id, o["numero"])
    db.commit()
    try:
        os.remove(os.path.join(UPLOAD_DIR, "os", str(os_id), ft["arquivo"]))
    except OSError:
        pass
    return redirect(url_for("os_ver", os_id=os_id) + "#fotos")


def _assinatura_valida(v):
    return bool(v) and v.startswith("data:image/png;base64,") and len(v) < 400_000


@app.route("/os/<int:os_id>/assinar", methods=["POST"])
@editor_required
def os_assinar(os_id):
    o = get_os(os_id)
    if not os_editavel(o):
        return redirect(url_for("os_ver", os_id=os_id))
    f = request.form
    erros = []
    if o["status"] == "Cancelada":
        erros.append("Não é possível assinar uma OS cancelada.")
    pendentes = o["ck_total"] - o["ck_ok"] - o["ck_nc"] - o["ck_na"]
    if pendentes:
        erros.append(f"Preencha todo o checklist antes da assinatura ({pendentes} item(ns) sem resposta).")
    nome = f.get("recebedor_nome", "").strip()
    if not nome:
        erros.append("Informe o nome de quem recebe pelo cliente.")
    ass_cli = f.get("assinatura_cliente", "")
    if not _assinatura_valida(ass_cli):
        erros.append("Colete a assinatura do cliente no quadro.")
    ass_tec = f.get("assinatura_tecnico", "")
    if ass_tec and not _assinatura_valida(ass_tec):
        ass_tec = ""
    if erros:
        for x in erros:
            flash(x, "danger")
        return redirect(url_for("os_ver", os_id=os_id) + "#assinatura")
    agora = datetime.now()
    db = get_db()
    db.execute("""UPDATE ordens_servico SET recebedor_nome=?, recebedor_documento=?, recebedor_cargo=?, tecnico_nome=?,
                  assinatura_cliente=?, assinatura_tecnico=?, assinado_em=?, status='Concluída',
                  data_execucao=COALESCE(data_execucao, ?), hora_fim=COALESCE(hora_fim, ?) WHERE id=?""",
               (nome, f.get("recebedor_documento", "").strip() or None, f.get("recebedor_cargo", "").strip() or None,
                f.get("tecnico_nome", "").strip() or g.user["nome"], ass_cli, ass_tec or None,
                agora.strftime("%Y-%m-%d %H:%M"), agora.date().isoformat(), agora.strftime("%H:%M"), os_id))
    audit("assinou", "ordem de serviço", os_id, f"{o['numero']}: recebido por {nome}")
    db.commit()
    flash(f"OS {o['numero']} assinada e concluída. O PDF já pode ser enviado ao cliente.", "success")
    return redirect(url_for("os_ver", os_id=os_id))


@app.route("/os/<int:os_id>/reabrir", methods=["POST"])
@admin_required
def os_reabrir(os_id):
    o = get_os(os_id)
    db = get_db()
    db.execute("""UPDATE ordens_servico SET assinatura_cliente=NULL, assinatura_tecnico=NULL, assinado_em=NULL,
                  status='Em execução' WHERE id=?""", (os_id,))
    audit("reabriu", "ordem de serviço", os_id, f"{o['numero']} (assinada em {o['assinado_em']})")
    db.commit()
    flash("OS reaberta. As assinaturas anteriores foram descartadas; colete-as novamente depois das correções.", "warning")
    return redirect(url_for("os_ver", os_id=os_id))


# ---------------------------------------------------------------- modelos de checklist

def _linhas_modelo(texto):
    """Converte o texto do formulário em (grupo, descrição). Linhas iniciadas por # definem o grupo."""
    grupo, linhas = None, []
    for bruto in (texto or "").splitlines():
        t = bruto.strip()
        if not t:
            continue
        if t.startswith("#"):
            grupo = t.lstrip("#").strip() or None
        else:
            linhas.append((grupo, t.lstrip("-•* ").strip()))
    return linhas


def _texto_modelo(itens):
    partes, grupo = [], object()
    for it in itens:
        if it["grupo"] != grupo:
            grupo = it["grupo"]
            if grupo:
                partes.append(("" if not partes else "\n") + f"# {grupo}")
        partes.append(it["descricao"])
    return "\n".join(partes)


@app.route("/checklists")
@editor_required
def checklists():
    lista = get_db().execute("""SELECT m.*, (SELECT COUNT(*) FROM checklist_modelo_itens i WHERE i.modelo_id=m.id) AS qtd
                                FROM checklist_modelos m ORDER BY m.ativo DESC, m.nome""").fetchall()
    return render_template("checklists.html", modelos=lista)


@app.route("/checklists/novo", methods=["GET", "POST"])
@editor_required
def checklist_novo():
    return checklist_form(None)


@app.route("/checklists/<int:mid>/editar", methods=["GET", "POST"])
@editor_required
def checklist_editar(mid):
    return checklist_form(mid)


def checklist_form(mid):
    db = get_db()
    atual = db.execute("SELECT * FROM checklist_modelos WHERE id=?", (mid,)).fetchone() if mid else None
    if mid and not atual:
        abort(404)
    if request.method == "POST":
        f = request.form
        nome = f.get("nome", "").strip()
        linhas = _linhas_modelo(f.get("itens"))
        tipo = f.get("tipo_os") if f.get("tipo_os") in TIPOS_OS else None
        if not nome or not linhas:
            flash("Informe o nome e pelo menos um item do checklist.", "danger")
            return render_template("checklist_form.html", m=f, texto=f.get("itens", ""), TIPOS=TIPOS_OS, novo=not mid)
        if mid:
            db.execute("UPDATE checklist_modelos SET nome=?, tipo_os=?, ativo=? WHERE id=?",
                       (nome, tipo, 1 if f.get("ativo") else 0, mid))
            db.execute("DELETE FROM checklist_modelo_itens WHERE modelo_id=?", (mid,))
            audit("editou", "modelo de checklist", mid, nome)
        else:
            mid = db.execute("INSERT INTO checklist_modelos (nome, tipo_os, ativo) VALUES (?,?,?)",
                             (nome, tipo, 1 if f.get("ativo") else 0)).lastrowid
            audit("criou", "modelo de checklist", mid, nome)
        db.executemany("INSERT INTO checklist_modelo_itens (modelo_id, ordem, grupo, descricao) VALUES (?,?,?,?)",
                       [(mid, i, gr, de) for i, (gr, de) in enumerate(linhas, start=1)])
        db.commit()
        flash("Modelo de checklist salvo. As OS já abertas mantêm o checklist que tinham.", "success")
        return redirect(url_for("checklists"))
    texto = ""
    if atual:
        texto = _texto_modelo(db.execute("SELECT * FROM checklist_modelo_itens WHERE modelo_id=? ORDER BY ordem, id",
                                         (mid,)).fetchall())
    return render_template("checklist_form.html", m=dict(atual) if atual else {"ativo": 1}, texto=texto, TIPOS=TIPOS_OS,
                           novo=not mid)


@app.route("/checklists/<int:mid>/excluir", methods=["POST"])
@admin_required
def checklist_excluir(mid):
    db = get_db()
    m = db.execute("SELECT * FROM checklist_modelos WHERE id=?", (mid,)).fetchone() or abort(404)
    db.execute("DELETE FROM checklist_modelos WHERE id=?", (mid,))
    audit("excluiu", "modelo de checklist", mid, m["nome"])
    db.commit()
    flash("Modelo excluído.", "success")
    return redirect(url_for("checklists"))


@app.route("/saude")
def saude():
    get_db().execute("SELECT 1").fetchone()
    return {"ok": True}


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
        try:
            vkm = parse_num(request.form.get("frete_valor_km"))
            valores["frete_valor_km"] = str(vkm if vkm is not None else FRETE_KM_PADRAO)
        except ValueError:
            flash("Valor do frete por km inválido; mantido o anterior.", "warning")
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
    if not debug:
        try:
            from waitress import serve  # servidor de produção (Docker / Coolify / rede local)
            serve(app, host="0.0.0.0", port=port, threads=int(os.environ.get("THREADS", 8)))
            sys.exit(0)
        except ImportError:
            pass
    app.run(host="0.0.0.0", port=port, debug=debug)
