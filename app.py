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

@app.route("/zerar", methods=["POST"])
def zerar():
    conn = get_conn()
    conn.cursor().execute("DELETE FROM transacoes")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

def init_db():
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
    linhas = texto.splitlines()

    for i, linha in enumerate(linhas):
        # Tenta encontrar padrão: data DD/MM/AAAA seguida de descrição e valor
        match_data = re.search(r'(\d{2}/\d{2}/\d{4})', linha)
        if not match_data:
            continue

        data_raw = match_data.group(1)
        data = f"{data_raw[6:]}-{data_raw[3:5]}-{data_raw[0:2]}"

        # Pega o restante da linha como descrição
        resto = linha[match_data.end():].strip()

        # Procura valor no padrão brasileiro: 1.234,56 ou -1.234,56
        match_valor = re.search(r'(-?\d{1,3}(?:\.\d{3})*,\d{2})', resto)
        if not match_valor:
            # Tenta na próxima linha
            if i + 1 < len(linhas):
                match_valor = re.search(r'(-?\d{1,3}(?:\.\d{3})*,\d{2})', linhas[i+1])

        if not match_valor:
            continue

        valor_raw = match_valor.group(1).replace(".", "").replace(",", ".")
        valor = float(valor_raw)

        memo = resto.replace(match_valor.group(1), "").strip() or f"transacao_{data}"
        tid = re.sub(r'\W+', '', f"{data}{memo}")[:50]

        transacoes.append({
            "id": tid,
            "data": data,
            "memo": memo or "Sem descrição",
            "valor": valor
        })

    return transacoes

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
