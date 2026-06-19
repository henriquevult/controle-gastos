import re

@app.route("/upload", methods=["POST"])
def upload():
    arquivo = request.files["ofx"]
    conteudo = arquivo.read().decode("latin-1", errors="ignore")

    transacoes = re.findall(
        r'<STMTTRN>(.*?)</STMTTRN>', conteudo, re.DOTALL
    )

    def extrair(bloco, tag):
        m = re.search(rf'<{tag}>(.*?)(?:<|$)', bloco, re.DOTALL)
        return m.group(1).strip() if m else ""

    conn = get_conn()
    cur = conn.cursor()
    inseridas = 0

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
            print(f"Erro na transação {tid}: {e}")

    conn.commit()
    conn.close()
    return jsonify({"inseridas": inseridas})
