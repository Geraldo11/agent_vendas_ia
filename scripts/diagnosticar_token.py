"""Diagnostica o DATABRICKS_TOKEN SEM imprimir o valor dele.

Uso, dentro do container:  python scripts/diagnosticar_token.py
"""
import os
import re
import urllib.error
import urllib.request

host = os.environ.get("DATABRICKS_HOST", "").strip().rstrip("/")
token = os.environ.get("DATABRICKS_TOKEN", "")

print("1) Formato do token (o valor NÃO é mostrado)")
print("   tamanho                          :", len(token), "(esperado: cerca de 36 a 40)")
print("   começa com 'dapi'                :", token.startswith("dapi"))
print("   tem espaço, aspas ou quebra      :", bool(re.search(r"[\s\"']", token)))
print("   só caracteres válidos            :", bool(re.fullmatch(r"dapi[0-9a-zA-Z_\-]+", token)))

print("\n2) Teste direto na API (só o código HTTP é mostrado)")
req = urllib.request.Request(f"{host}/api/2.0/preview/scim/v2/Me",
                             headers={"Authorization": f"Bearer {token.strip()}"})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        print("   HTTP", r.status, "-> token ACEITO")
except urllib.error.HTTPError as e:
    print("   HTTP", e.code, "-> token RECUSADO" if e.code in (401, 403) else "-> outro problema")
except Exception as e:
    print("   falha de rede:", type(e).__name__)
