from openai import OpenAI

def extrair_pdf(arquivo_bytes):
    pdf_b64 = base64.standard_b64encode(arquivo_bytes).decode("utf-8")
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    msg = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:application/pdf;base64,{pdf_b64}"
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
    texto = msg.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
    return json.loads(texto)
