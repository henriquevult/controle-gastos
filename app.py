from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import os, re, json, base64
import psycopg2
from urllib.parse import urlparse
from PIL import Image
import io

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

PROMPT = """Extraia todas as transações deste extrato bancário.
Retorne APENAS um JSON válido, sem texto antes ou depois, no formato:
[{"id":"unico","data":"YYYY-MM-DD","memo":"descricao","valor":-100.00}]
Valores negativos para débitos, positivos para créditos.
Se não houver ID, gere um baseado em data+descrição."""

def chamar_gpt(content):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    msg = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}]
    )
    texto = msg.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
    return json.loads(texto)

def extrair_pdf(arquivo_bytes):
    pdf_b64 = base64.standard_b64encode(arquivo_bytes).decode("utf-8")
    return chamar_gpt([
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{pdf_b64}"}}
    ])

def extrair_imagem(arquivo_bytes, media_type):
    img = Image.open(io.BytesIO(arquivo_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    img_b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    return chamar_gpt([
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
    ])

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

    elif nome.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
        media_type = "image/png" if nome.endswith(".png") else "image/jpeg"
        inseridas = salvar(cur, extrair_imagem(conteudo_bytes, media_type))

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
