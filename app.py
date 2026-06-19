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

import os
import psycopg2
from urllib.parse import urlparse

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

@app.route("/upload", methods=["POST"])
def upload():
    arquivo = request.files["ofx"]
    ofx = OfxParser.parse(io.BytesIO(arquivo.read()))
    conn = get_conn()
    cur = conn.cursor()
    inseridas = 0
    for t in ofx.account.statement.transactions:
        try:
            cur.execute(
                "INSERT INTO transacoes VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (t.id, str(t.date.date()), t.memo, float(t.amount), categorizar(t.memo))
            )
            inseridas += 1
        except:
            pass
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
