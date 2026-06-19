from flask import Flask, render_template, request, jsonify
import io, os, re
import psycopg2
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
    url = urlparse(os.environ["DATABASE_URL"])
    return psycopg2.connect(
        dbname=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )

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

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    arquivo = request.files["ofx"]
    conteudo = arquivo.read().decode("latin-1", errors="ignore")

    transacoes = re.findall(r'<STMTTRN>(.*?)</STMTTRN>', conteudo, re.DOTALL)

    def extrair(bloco, tag):
        m = re.search(rf'<{tag}>(.*?)(?:<|$)', bloco, re.DOTALL)
        return m.group(1).strip() if m else ""

    conn = get_conn()
    cur = conn.cursor()
    inseridas = 0

    for t in transacoes:
        tid  = extrair(t, "FITID")
        data = extrair(t, "DTPOSTED")[:8]
        data = f"{data[:4]}-{data[4:6]}-{data[6:8]}"
        memo = extrair(t, "MEMO") or extrair(t, "NAME")
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
