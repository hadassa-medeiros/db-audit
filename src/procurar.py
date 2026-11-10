"""Procura arquivos pelo nome em todo o Drive que você enxerga — INCLUSIVE na lixeira.

Mostra: nome, se está na lixeira, quando foi para a lixeira e por quem (quando o Google informa),
onde está (caminho), dono, última modificação e link. Só leitura.

USO:
  python src/procurar.py
  (pede as palavras; todas precisam estar no nome, ex.: Varredura Sumário)
"""
from drive import connect

CAMPOS = ("id, name, mimeType, trashed, trashedTime, trashingUser(displayName, emailAddress), "
          "parents, owners(emailAddress), lastModifyingUser(emailAddress), modifiedTime, createdTime, webViewLink")


def caminho(drive, pais, cache):
    nomes, p = [], (pais or [None])[0]
    for _ in range(12):
        if not p:
            break
        if p not in cache:
            try:
                g = drive.files().get(fileId=p, fields="name, parents, trashed", supportsAllDrives=True).execute()
                cache[p] = (g["name"] + (" [NA LIXEIRA]" if g.get("trashed") else ""), (g.get("parents") or [None])[0])
            except Exception:
                cache[p] = ("(sem acesso)", None)
        nome, p = cache[p]
        nomes.insert(0, nome)
    return "/".join(nomes) or "(raiz ou sem acesso)"


if __name__ == "__main__":
    palavras = input("Palavras no nome (separadas por espaço): ").split()
    variantes = {"sumário": "sumario", "sumario": "sumário"}
    drive = connect()
    achados = {}
    # O Drive compara palavras do nome; procuro com e sem acento e junto os resultados.
    for alvo in palavras:
        for termo in {alvo, variantes.get(alvo.lower(), alvo)}:
            for lixeira in ("true", "false"):
                q = f"name contains '{termo.replace(chr(39), ' ')}' and trashed = {lixeira}"
                token = None
                while True:
                    r = drive.files().list(q=q, fields=f"nextPageToken, files({CAMPOS})", pageSize=1000,
                                           pageToken=token, corpora="allDrives", supportsAllDrives=True,
                                           includeItemsFromAllDrives=True).execute()
                    for f in r.get("files", []):
                        achados[f["id"]] = f
                    token = r.get("nextPageToken")
                    if not token:
                        break

    def tem_todas(nome):
        n = nome.lower().replace("á", "a")
        return all(p.lower().replace("á", "a") in n for p in palavras)

    res = sorted((f for f in achados.values() if tem_todas(f["name"])),
                 key=lambda f: (not f.get("trashed"), f.get("modifiedTime", "")))
    print(f"\n{len(res)} arquivo(s) com todas as palavras no nome:\n")
    cache = {}
    for f in res:
        quem = f.get("trashingUser") or {}
        print("=" * 80)
        print(f"NOME:        {f['name']}")
        print(f"NA LIXEIRA:  {'SIM' if f.get('trashed') else 'não'}")
        if f.get("trashed"):
            print(f"  desde:     {f.get('trashedTime', '(o Google não informa para este tipo de pasta)')}")
            print(f"  por:       {quem.get('displayName', '')} {quem.get('emailAddress', '(não informado)')}")
        print(f"ONDE:        {caminho(drive, f.get('parents'), cache)}")
        print(f"DONO:        {', '.join(o['emailAddress'] for o in f.get('owners', [])) or '(drive compartilhado)'}")
        print(f"MODIFICADO:  {f.get('modifiedTime', '')} por {(f.get('lastModifyingUser') or {}).get('emailAddress', '?')}")
        print(f"CRIADO:      {f.get('createdTime', '')}")
        print(f"LINK:        {f.get('webViewLink', '')}")
    if not res:
        print("Nada encontrado nem na lixeira com essas palavras, com o acesso da sua conta.")
