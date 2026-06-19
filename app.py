from flask import Flask, render_template, request, jsonify
from ofxparse import OfxParser
import sqlite3, io

app = Flask(__name__)

CATEGORIAS = {
    "mercado": ["supermercado", "atacado", "carrefour", "extra", "pao de acucar"],
    "transporte": ["uber", "99", "posto", "combustivel", "estacionamento"],
    "alimentacao": ["restaurante", "ifood", "lanchonete", "padaria", "pizza"],
    "saude": ["farmacia", "drogaria", "clinica", "hospital"],
    "lazer": ["cinema", "netflix", "spotify", "steam"],
}

def categorizar(descricao):
    desc = descricao.lower()
    for categoria, palavras in CATEGORIAS.items():
        if any(p in desc for p in palavras):
            return categoria
    return "outros"

def init_db():
    conn = sqlite3.connect("gastos.db")
    conn.execute("""
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
    ofx = OfxParser.parse(io.BytesIO(arquivo.read()))
    conn = sqlite3.connect("gastos.db")
    inseridas = 0
    for conta in ofx.account.statement.transactions:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO transacoes VALUES (?,?,?,?,?)",
                (conta.id, str(conta.date.date()), conta.memo,
                 float(conta.amount), categorizar(conta.memo))
            )
            inseridas += 1
        except:
            pass
    conn.commit()
    conn.close()
    return jsonify({"inseridas": inseridas})

@app.route("/api/transacoes")
def transacoes():
    conn = sqlite3.connect("gastos.db")
    rows = conn.execute(
        "SELECT data, descricao, valor, categoria FROM transacoes ORDER BY data DESC"
    ).fetchall()
    conn.close()
    return jsonify([
        {"data": r[0], "descricao": r[1], "valor": r[2], "categoria": r[3]}
        for r in rows
    ])

init_db()

if __name__ == "__main__":
    app.run(debug=True)
