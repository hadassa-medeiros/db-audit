"""Procura no LOG DE AUDITORIA do Google Workspace quem mandou para a lixeira / excluiu um arquivo, e quando.

Usa a Admin SDK (Reports API). Precisa de uma conta com papel de administrador que inclua Relatórios.
Só leitura: não altera nada. A restauração em si é feita no Admin Console (instruções no fim da saída).

USO:
  python src/auditoria.py
  (pergunta: palavras do nome, quantos dias para trás, e de qual usuário — Enter = todos)
"""
import csv
import unicodedata
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from drive import RAIZ

SCOPES = ["https://www.googleapis.com/auth/admin.reports.audit.readonly"]
EVENTOS = ["trash", "delete", "move", "remove_from_folder"]  # lixeira, exclusão definitiva, movido, tirado da pasta


def conecta_admin():
    config_path = RAIZ / "config" / "oauth_client.json"
    token_path = RAIZ / "config" / "token_admin.json"
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(config_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("admin", "reports_v1", credentials=creds)


def normal(t):
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def params(evento):
    out = {}
    for p in evento.get("parameters", []):
        out[p["name"]] = p.get("value") or ", ".join(p.get("multiValue", []))
    return out


if __name__ == "__main__":
    palavras = [normal(p) for p in input("Palavras no nome do arquivo (ex.: Varredura Sumário): ").split()]
    dias = input("Quantos dias para trás procurar? (Enter = 60; o Google guarda até ~180): ").strip()
    dias = int(dias) if dias.isdigit() else 60
    usuario = input("E-mail de quem pode ter excluído (Enter = todos os usuários): ").strip() or "all"

    inicio = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    reports = conecta_admin()
    achados = []
    for nome_evento in EVENTOS:
        token, paginas = None, 0
        while True:
            r = reports.activities().list(userKey=usuario, applicationName="drive", eventName=nome_evento,
                                          startTime=inicio, maxResults=1000, pageToken=token).execute()
            paginas += 1
            for atv in r.get("items", []):
                for ev in atv.get("events", []):
                    p = params(ev)
                    titulo = p.get("doc_title", "")
                    if all(w in normal(titulo) for w in palavras):
                        achados.append({
                            "quando_utc": atv["id"]["time"], "evento": ev.get("name", nome_evento),
                            "quem": atv.get("actor", {}).get("email", "(sem e-mail)"),
                            "titulo": titulo, "dono": p.get("owner", ""), "doc_id": p.get("doc_id", ""),
                            "tipo": p.get("doc_type", ""),
                            "de_pasta": p.get("source_folder_title", ""), "para_pasta": p.get("destination_folder_title", ""),
                        })
            token = r.get("nextPageToken")
            print(f"  {nome_evento}: {paginas} página(s) lida(s), {len(achados)} achado(s) até agora", end="\r")
            if not token:
                break
        print()

    achados.sort(key=lambda a: a["quando_utc"])
    print(f"\n{len(achados)} evento(s) com essas palavras no nome, nos últimos {dias} dias:\n")
    for a in achados:
        print("=" * 80)
        for k, v in a.items():
            if v:
                print(f"{k:<12} {v}")
    if achados:
        out = RAIZ / "out" / f"auditoria_{datetime.now():%Y%m%d_%H%M%S}.csv"
        out.parent.mkdir(exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(achados[0]))
            w.writeheader()
            w.writerows(achados)
        print(f"\nsalvo em {out}")
        print("\nPARA RESTAURAR (exclusão definitiva, até 25 dias):")
        print("  Admin Console > Diretório > Usuários > clique no DONO acima > Restaurar dados")
        print("  Intervalo: do dia anterior ao dia seguinte ao evento 'delete' > Aplicativo: Drive > Restaurar")
        print("  Se o último evento for só 'trash': o arquivo ainda está na lixeira do dono — ele restaura lá.")
    else:
        print("Nada encontrado. Tente mais dias, outra palavra, ou confira se o nome era outro.")
