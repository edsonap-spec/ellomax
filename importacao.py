"""Importação de editais ganhos a partir de um arquivo JSON (ex.: dados/editais_ganhos.json).

Um edital não é importado de novo quando já existe outro com o mesmo número, a mesma cidade
e o mesmo valor total dos itens. A comparação ignora acentos, maiúsculas, zeros à esquerda e
pontos no ano ("09/2.026" = "9/2026").
"""
import json
import os
import re
import unicodedata

ARQUIVO_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados", "editais_ganhos.json")

COLUNAS = ["orgao", "cidade", "uf", "cnpj_orgao", "uasg", "numero", "processo", "modalidade", "objeto",
           "data_abertura", "data_homologacao", "numero_contrato", "vigencia_inicio", "vigencia_fim",
           "prazo_entrega", "local_entrega", "status", "contato_orgao", "responsavel", "link_edital", "observacoes"]


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def norm_numero(s):
    s = (s or "").replace(".", "")
    m = re.search(r"(\d+)\s*/\s*(\d{4})", s)
    if m:
        return f"{int(m.group(1))}/{m.group(2)}"
    return re.sub(r"[^a-z0-9]", "", _sem_acento(s).lower())


def norm_cidade(s):
    return re.sub(r"[^a-z0-9]+", " ", _sem_acento(s).lower()).strip()


def total_itens(itens):
    return round(sum(float(i.get("quantidade") or 0) * float(i.get("valor_unitario") or 0) for i in itens), 2)


def carregar(caminho=None):
    with open(caminho or ARQUIVO_PADRAO, encoding="utf-8") as f:
        return validar(json.load(f))


def validar(dados):
    """Aceita {"editais": [...]} ou só a lista; confere os campos obrigatórios."""
    if isinstance(dados, list):
        dados = {"editais": dados}
    if not isinstance(dados, dict) or not isinstance(dados.get("editais"), list):
        raise ValueError("o JSON precisa ter a lista \"editais\"")
    for e in dados["editais"]:
        if not isinstance(e, dict):
            raise ValueError("cada edital deve ser um objeto JSON")
        for it in e.get("itens") or []:
            if not (it.get("descricao") or "").strip():
                raise ValueError(f"Item sem descrição no edital {e.get('numero')}")
            float(it.get("quantidade") or 0), float(it.get("valor_unitario") or 0)
        for campo in ("orgao", "numero", "objeto"):
            if not (e.get(campo) or "").strip():
                raise ValueError(f"Edital sem '{campo}' no arquivo: {e.get('numero') or e.get('orgao') or e}")
    return dados


def _mesma_cidade(cidade, existente):
    """Compara a cidade; editais antigos sem cidade são comparados pelo nome do órgão e local."""
    if existente["cidade"]:
        return norm_cidade(existente["cidade"]) == cidade
    texto = f" {norm_cidade(existente['orgao'])} {norm_cidade(existente['local_entrega'])} "
    return f" {cidade} " in texto


def analisar(db, dados):
    """Classifica cada edital do arquivo como 'novo', 'existe' (já cadastrado) ou 'repetido' (duplicado no arquivo)."""
    existentes = db.execute("""SELECT e.id, e.numero, e.cidade, e.orgao, e.local_entrega,
                               ROUND(COALESCE((SELECT SUM(quantidade*valor_unitario) FROM itens i WHERE i.edital_id=e.id),0),2) AS total
                               FROM editais e""").fetchall()
    vistos = {}
    linhas = []
    for e in dados.get("editais", []):
        total = total_itens(e.get("itens", []))
        num, cid = norm_numero(e["numero"]), norm_cidade(e.get("cidade"))
        chave = (num, cid, total)
        linha = {"edital": e, "total": total, "situacao": "novo", "existente_id": None, "aviso": None}
        if chave in vistos:
            linha["situacao"] = "repetido"
            linha["aviso"] = f"Igual ao edital {vistos[chave]} deste mesmo arquivo."
        else:
            vistos[chave] = e["numero"]
            for x in existentes:
                if norm_numero(x["numero"]) != num or not _mesma_cidade(cid, x):
                    continue
                if abs((x["total"] or 0) - total) < 0.005:
                    linha["situacao"], linha["existente_id"] = "existe", x["id"]
                    linha["aviso"] = "Já cadastrado (mesmo nº, cidade e valor)."
                    break
                linha["aviso"] = (f"Já existe o edital {x['numero']} desta cidade com valor diferente "
                                  f"(R$ {x['total']:,.2f}); será importado como outro edital.")
        if linha["situacao"] == "novo" and not e.get("itens") and not linha["aviso"]:
            linha["aviso"] = "Sem itens no arquivo: lance os itens ganhos e valores depois."
        linhas.append(linha)
    return linhas


def empresa_destino(db, dados, preferida=None):
    """Empresa do CNPJ informado no arquivo; senão a preferida; senão a primeira cadastrada."""
    cnpj = re.sub(r"\D", "", dados.get("empresa_cnpj") or "")
    if cnpj:
        for emp in db.execute("SELECT id, cnpj FROM empresas WHERE ativo=1"):
            if re.sub(r"\D", "", emp["cnpj"] or "") == cnpj:
                return emp["id"]
    if preferida:
        return preferida
    return db.execute("SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()[0]


def importar(db, dados, empresa_id, usuario_id=None):
    """Grava os editais novos com seus itens. Devolve (ids criados, linhas da análise). Não faz commit."""
    criados = []
    linhas = analisar(db, dados)
    for linha in linhas:
        if linha["situacao"] != "novo":
            continue
        e = dict(linha["edital"])
        if e.get("arquivos"):
            obs = (e.get("observacoes") or "").strip()
            e["observacoes"] = (obs + "\n\n" if obs else "") + "Arquivos de origem: " + "; ".join(e["arquivos"])
        e.setdefault("status", "Homologado")
        cols = [c for c in COLUNAS if e.get(c) not in (None, "")]
        cur = db.execute(f"INSERT INTO editais ({', '.join(cols)}, empresa_id, criado_por) "
                         f"VALUES ({', '.join('?' * len(cols))}, ?, ?)",
                         [e[c] for c in cols] + [empresa_id, usuario_id])
        eid = cur.lastrowid
        for it in e.get("itens", []):
            qtd = float(it.get("quantidade") or 0)
            db.execute("""INSERT INTO itens (edital_id, lote, numero_item, descricao, marca, unidade, quantidade,
                          valor_unitario, custo_unitario, qtd_entregue) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                       (eid, it.get("lote"), it.get("numero_item"), it["descricao"], it.get("marca"), it.get("unidade"),
                        qtd, float(it.get("valor_unitario") or 0), it.get("custo_unitario"),
                        qtd if e.get("entregue") else float(it.get("qtd_entregue") or 0)))
        linha["criado_id"] = eid
        criados.append(eid)
    return criados, linhas
