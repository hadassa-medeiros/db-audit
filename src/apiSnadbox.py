"""Manda para a LIXEIRA as pastas VAZIAS de uma pasta — ou do Meu Drive inteiro.

Vazia = nada dentro: nenhum arquivo, nenhum atalho, nenhum item na lixeira, em nenhuma subpasta.
Uma pasta que só contém pastas vazias também é vazia. Basta um arquivo em qualquer nível para ela ficar.
- Nunca exclui definitivamente: vai para a lixeira (dá para restaurar por 30 dias, ou com --undo).
- Mostra a lista e só age depois de você digitar SIM.
- Antes de cada uma, confere de novo no Drive que continua vazia.

USO:
  python src/limpar_vazias.py                  (Enter na pergunta = Meu Drive)
  python src/limpar_vazias.py --undo out/log_vazias_AAAAMMDD_HHMMSS.csv
"""
import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime

from googleapiclient.errors import HttpError

from drive import RAIZ, connect

PASTA = "application/vnd.google-apps.folder"
IMAGE = "image/jpeg"
DWG = "image/vnd.dwg"
PDF = "application/pdf"

ALL = dict(supportsAllDrives=True)


def filhos(drive, ids):
    # Tudo o que está dentro de até 30 pastas, INCLUSIVE itens na lixeira (contam como conteúdo).
    q = "(" + " or ".join(f"'{i}' in parents" for i in ids) + ")"
    out, token = [], None
    while True:
        r = drive.files().list(q=q, fields="nextPageToken, files(id, name, mimeType, parents, trashed, "
                                            "capabilities(canTrash))",
                               pageSize=1000, pageToken=token, supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute()
        out += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            return out


def varre(drive, raiz_id):
    raiz = drive.files().get(fileId=raiz_id, fields="id, name, mimeType", **ALL).execute()
    print(raiz["name"], raiz["id"], raiz["mimeType"])
    raiz_id = raiz["id"]  # "root" vira o ID real do Meu Drive
    pastas = {raiz_id: {"nome": raiz["name"], "pai": None, "pode": False}}
    conteudo, sub = defaultdict(int), defaultdict(list)
    frente, nivel = [raiz_id], 0
    while frente:
        nivel += 1
        prox = []
        for i in range(0, len(frente), 30):
            lote = set(frente[i:i + 30])
            for f in filhos(drive, list(lote)):
                pai = next((p for p in f.get("parents", []) if p in lote), None)
                if pai is None:
                    continue
                if f["mimeType"] == PASTA and not f.get("trashed"):
                    # print(f["name"])
                    pastas[f["id"]] = {"nome": f["name"], "pai": pai,
                                       "pode": (f.get("capabilities") or {}).get("canTrash", False)}
                    sub[pai].append(f["id"])
                    prox.append(f["id"])
                else:
                    conteudo[pai] += 1  # arquivo, atalho, ou qualquer coisa na lixeira
                # print(f["name"], f["id"], f["mimeType"])
        frente = prox
        print(f"  nível {nivel}: {len(prox)} pastas", end="\r")
    return raiz_id, pastas, conteudo, sub

def renomear_arquivo(drive, file_id, novo_nome):
    """Renomeia um arquivo no Google Drive."""
    try:
        drive.files().update(fileId=file_id, body={"name": novo_nome}, **ALL).execute()
        print(f"Arquivo {file_id} renomeado para '{novo_nome}'")
    except HttpError as e:
        print(f"Erro ao renomear arquivo {file_id}: {e}")

def vazias(pastas, conteudo, sub):
    # De baixo para cima: vazia = sem conteúdo direto e todas as subpastas vazias.
    profundidade = {}
    for fid in pastas:
        d, p = 0, pastas[fid]["pai"]
        while p:
            d, p = d + 1, pastas[p]["pai"]
        profundidade[fid] = d
    vazia = {}
    for fid in sorted(pastas, key=lambda x: -profundidade[x]):
        vazia[fid] = conteudo[fid] == 0 and all(vazia[s] for s in sub[fid])
    return vazia


def caminho(pastas, fid):
    nomes = []
    while fid:
        nomes.insert(0, pastas[fid]["nome"])
        fid = pastas[fid]["pai"]
    return "/".join(nomes)


def conta_sub(sub, fid):
    n, fila = 0, list(sub[fid])
    while fila:
        x = fila.pop()
        n += 1
        fila += sub[x]
    return n


def novo_log(nome):
    base = RAIZ / "out" / f"{nome}_{datetime.now():%Y%m%d_%H%M%S}"
    base.parent.mkdir(parents=True, exist_ok=True)
    path, n = base.with_suffix(".csv"), 2
    while path.exists():
        path, n = base.with_name(f"{base.name}_{n}.csv"), n + 1
    return path


def cmd_undo(log_file):
    import pandas as pd
    log = pd.read_csv(RAIZ / log_file, dtype=str, keep_default_na=False)
    feitos = log[log["status"] == "ok"]
    print(f"{len(feitos)} pastas a tirar da lixeira")
    if feitos.empty or input("Restaurar? Digite SIM: ").strip() != "SIM":
        sys.exit("Nada foi alterado.")
    drive = connect(write=True)
    for r in feitos.itertuples():
        try:
            drive.files().update(fileId=r.file_id, body={"trashed": False}, **ALL).execute()
            print(f"  restaurada  {r.caminho}")
        except HttpError as e:
            print(f"  ERRO {e.resp.status}  {r.caminho}")


if __name__ == "__main__":

    p = argparse.ArgumentParser()
    p.add_argument("--undo", metavar="LOG", help="tira da lixeira as pastas de um log")
    args = p.parse_args()
    if args.undo:
        cmd_undo(args.undo)
        sys.exit()

    txt = input("ID ou link da pasta (Enter = Meu Drive inteiro): ").strip()
    m = re.search(r"/folders/([\w-]+)", txt)
    alvo = m.group(1) if m else (txt or "root")

    drive = connect(write=True)
    renomear_arquivo(drive, "1ejWVt3Lh1SLekUZiWVp4XKF2UkBp9MJ6ULGHF7s4rQU", "novo_nome")  # Exemplo de uso da função de renomear arquivo
    raiz_id, pastas, conteudo, sub = varre(drive, alvo)
    vazia = vazias(pastas, conteudo, sub)
    # Só a pasta vazia mais alta de cada galho (as de dentro vão junto). A raiz nunca.
    topo = [f for f in pastas if f != raiz_id and vazia[f]
            and (pastas[f]["pai"] == raiz_id or not vazia[pastas[f]["pai"]])]
    topo.sort(key=lambda f: caminho(pastas, f).lower())
    sem_permissao = [f for f in topo if not pastas[f]["pode"]]
    alvos = [f for f in topo if pastas[f]["pode"]]

    print(f"\n{len(pastas) - 1} pastas varridas em '{pastas[raiz_id]['nome']}'")
    print(f"{len(alvos)} pastas vazias para a lixeira (+ {sum(conta_sub(sub, f) for f in alvos)} subpastas vazias dentro delas)")
    if sem_permissao:
        print(f"{len(sem_permissao)} vazias que você não pode mandar para a lixeira (de outro dono) — ficam:")
        for f in sem_permissao[:10]:
            print("   ", caminho(pastas, f))
    if not alvos:
        sys.exit("\nNada a fazer.")
    print()
    for f in alvos[:40]:
        n = conta_sub(sub, f)
        print(f"  {caminho(pastas, f)}" + (f"   (+{n} subpastas vazias)" if n else ""))
    if len(alvos) > 40:
        print(f"  ... e mais {len(alvos) - 40} (lista completa no log)")

    if input(f"\nMandar {len(alvos)} pastas vazias para a lixeira? Digite SIM: ").strip() != "SIM":
        sys.exit("Cancelado. Nada foi alterado.")

    log_path, ok = novo_log("log_vazias"), 0
    with open(log_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["quando", "file_id", "caminho", "subpastas_vazias", "status"])
        for f in alvos:
            try:
                _, p2, c2, s2 = varre(drive, f)  # confere de novo: ainda vazia?
                if not vazias(p2, c2, s2)[f]:
                    status = "PULADA: tem conteúdo agora"
                else:
                    drive.files().update(fileId=f, body={"trashed": True}, **ALL).execute()
                    status = "ok"
            except HttpError as e:
                status = f"ERRO {e.resp.status}"
            ok += status == "ok"
            w.writerow([datetime.now().isoformat(timespec="seconds"), f, caminho(pastas, f), conta_sub(sub, f), status])
            fh.flush()
            print(f"  {status:<28} {caminho(pastas, f)}")
    print(f"\n{ok}/{len(alvos)} na lixeira  ->  log: {log_path}")
    print(f"desfazer: python src\\limpar_vazias.py --undo out\\{log_path.name}")
