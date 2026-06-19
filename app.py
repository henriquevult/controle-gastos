from flask import Flask, render_template, request, jsonify
import io, os, re, json, base64
import psycopg2
import anthropic
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

def extrair_pdf(arquivo_bytes):
    pdf_b64 = base64.standard_b64encode(arquivo_bytes).decode("utf-8")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64
                    }
                },
                {
                    "type": "text",
                    "text": """Extraia todas as transações deste extrato bancário.
Retorne APENAS um JSON válido, sem texto antes ou depois, no formato:
[{"id":"único","data":"YYYY-MM-DD","memo":"descrição","valor":-100.00}]
Valores negativos para débitos, positivos para créditos.
Se não houver ID, gere um baseado em data+descrição."""
                }
            ]
        }]
    )
    texto = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(texto)

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
        for t in extrair_pdf(conteudo_bytes):
            try:
                cur.execute(
                    "INSERT INTO transacoes VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (t["id"], t["data"], t["memo"], float(t["valor"]), categorizar(t["memo"]))
                )
                inseridas += 1
            except Exception as e:
                print(f"Erro: {e}")
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
