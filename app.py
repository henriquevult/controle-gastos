from flask import Flask, render_template, request, jsonify
import os, re, json
import psycopg2
import fitz
from urllib.parse import urlparse

app = Flask(__name__)

CATEGORIAS = {
    "mercado":     ["supermercado", "atacado", "carrefour", "extra", "pao de acucar"],
    "transporte":  ["uber", "99", "posto", "combustivel", "estacionamento"],
    "alimentacao": ["restaurante", "ifood", "lanchonete", "padaria", "pizza"],
    "saude":       ["farmacia", "drogaria", "clinica", "hospital"],
    "lazer":       ["cinema", "netflix", "spotify", "steam"],
}

def categorizar(descricao):
    desc = descricao.lower()
    for categoria, palavras in CATEGORIAS.items():
        if any(p in desc for p in palavras):
            return categoria
    return "outros"

def get_conn():
    db_url = os.environ["DATABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(db_url)

@app.route("/migrar", methods=["POST"])
def migrar():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE transacoes ADD COLUMN IF NOT EXISTS categoria_manual TEXT")
    cur.execute("ALTER TABLE transacoes ADD COLUMN IF NOT EXISTS categoria_custom TEXT")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/zerar", methods=["POST"])
def zerar():
    conn = get_conn()
    conn.cursor().execute("DELETE FROM transacoes")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

def init_db():
    conn.cursor().execute("""
    CREATE TABLE IF NOT EXISTS categorias (
        id SERIAL PRIMARY KEY,
        nome TEXT UNIQUE NOT NULL,
        cor TEXT DEFAULT '#388bfd',
        icone TEXT DEFAULT '📦'
    )
""")
    conn = get_conn()
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS transacoes (
            id TEXT PRIMARY KEY,
            data TEXT,
            descricao TEXT,
            valor REAL,
            categoria TEXT
        )
    """)
    conn.commit()
    conn.close()

def extrair_pdf(arquivo_bytes):
    doc = fitz.open(stream=arquivo_bytes, filetype="pdf")
    texto = ""
    for pagina in doc:
        texto += pagina.get_text()

    transacoes = []

    # --- COMPRAS COM CARTÃO DE DÉBITO ---
    # Formato: 01/05 4893.3185 ESTABELECIMENTO 36,89
    for m in re.finditer(
        r'(\d{2}/\d{2})\s+[\d.]+\s+(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*$',
        texto, re.MULTILINE
    ):
        data_raw, memo, valor_raw = m.group(1), m.group(2).strip(), m.group(3)
        ano = "2026"
        data = f"{ano}-{data_raw[3:5]}-{data_raw[0:2]}"
        valor = -float(valor_raw.replace(".", "").replace(",", "."))
        tid = re.sub(r'\W+', '', f"debito{data}{memo}")[:60]
        transacoes.append({"id": tid, "data": data, "memo": memo, "valor": valor})

    # --- PIX ENVIADOS (Comprovantes de Pagamento) ---
    # Formato: 01/05 INTERNET BANKING PIX FAVORECIDO ISPB 0000 0000... VALOR
    for m in re.finditer(
        r'(\d{2}/\d{2})\s+INTERNET BANKING\s+PIX\s+(.+?)\s+\d{8}\s+0000\s+\S+\s+(\d{1,3}(?:\.\d{3})*,\d{2})',
        texto, re.MULTILINE
    ):
        data_raw, memo, valor_raw = m.group(1), m.group(2).strip(), m.group(3)
        ano = "2026"
        data = f"{ano}-{data_raw[3:5]}-{data_raw[0:2]}"
        valor = -float(valor_raw.replace(".", "").replace(",", "."))
        tid = re.sub(r'\W+', '', f"pix{data}{memo}")[:60]
        transacoes.append({"id": tid, "data": data, "memo": f"PIX {memo}", "valor": valor})

    # --- PIX RECEBIDOS (seção de movimentação) ---
    for m in re.finditer(
        r'PIX RECEBIDO\s*\n(.+?)\n.*?(\d{1,3}(?:\.\d{3})*,\d{2})',
        texto, re.MULTILINE
    ):
        favorecido = m.group(1).strip()
        valor_raw  = m.group(2)
        # Tenta pegar data da linha anterior
        inicio = m.start()
        trecho = texto[max(0, inicio-30):inicio]
        data_m = re.search(r'(\d{2}/\d{2})', trecho)
        data = f"2026-{data_m.group(1)[3:5]}-{data_m.group(1)[0:2]}" if data_m else "2026-05-01"
        valor = float(valor_raw.replace(".", "").replace(",", "."))
        tid = re.sub(r'\W+', '', f"recebido{data}{favorecido}")[:60]
        transacoes.append({"id": tid, "data": data, "memo": f"PIX RECEBIDO {favorecido}", "valor": valor})

    # --- IOF e JUROS ---
    for m in re.finditer(
        r'(IOF[^\n]+|JUROS[^\n]+)\n.*?(\d{1,3}(?:\.\d{3})*,\d{2})-',
        texto, re.MULTILINE
    ):
        memo      = m.group(1).strip()
        valor_raw = m.group(2)
        valor     = -float(valor_raw.replace(".", "").replace(",", "."))
        tid       = re.sub(r'\W+', '', f"taxa{memo}")[:60]
        transacoes.append({"id": tid, "data": "2026-05-01", "memo": memo, "valor": valor})

    # Remove duplicatas por id
    vistos = set()
    unicas = []
    for t in transacoes:
        if t["id"] not in vistos:
            vistos.add(t["id"])
            unicas.append(t)

    return unicas

def salvar(cur, transacoes):
    inseridas = 0
    for t in transacoes:
        try:
            cur.execute(
                "INSERT INTO transacoes VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (t["id"], t["data"], t["memo"], float(t["valor"]), categorizar(t["memo"]))
            )
            inseridas += 1
        except Exception as e:
            print(f"Erro: {e}")
    return inseridas

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    arquivo = request.files["ofx"]
    nome = arquivo.filename.lower()
    conteudo_bytes = arquivo.read()
    conn = get_conn()
    cur = conn.cursor()
    inseridas = 0

    if nome.endswith(".pdf"):
        inseridas = salvar(cur, extrair_pdf(conteudo_bytes))

    else:
        conteudo = conteudo_bytes.decode("latin-1", errors="ignore")
        transacoes = re.findall(r'<STMTTRN>(.*?)</STMTTRN>', conteudo, re.DOTALL)

        def extrair(bloco, tag):
            m = re.search(rf'<{tag}>(.*?)(?:<|$)', bloco, re.DOTALL)
            return m.group(1).strip() if m else ""

        for t in transacoes:
            tid   = extrair(t, "FITID")
            data  = extrair(t, "DTPOSTED")[:8]
            data  = f"{data[:4]}-{data[4:6]}-{data[6:8]}"
            memo  = extrair(t, "MEMO") or extrair(t, "NAME")
            valor = extrair(t, "TRNAMT").replace(",", ".")
            try:
                cur.execute(
                    "INSERT INTO transacoes VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (tid, data, memo, float(valor), categorizar(memo))
                )
                inseridas += 1
            except Exception as e:
                print(f"Erro: {e}")

    conn.commit()
    conn.close()
    return jsonify({"inseridas": inseridas})

@app.route("/api/transacoes")
def transacoes():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT data, descricao, valor, categoria FROM transacoes ORDER BY data DESC")
    rows = cur.fetchall()
    conn.close()
    return jsonify([
        {"data": r[0], "descricao": r[1], "valor": r[2], "categoria": r[3]}
        for r in rows
    ])

init_db()

if __name__ == "__main__":
    app.run(debug=True)
