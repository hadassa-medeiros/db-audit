"""Dedup dentro de uma pasta: duplicatas (mesmo md5 + tamanho) vão para 'duplicatas_excluir'.

A pasta é pedida a cada rodada (aceita ID ou link). Quem sai é a cópia com marcador no nome
("cópia", "copia", "copy", "(1)", "(2)"...). Se o nome não decide, o grupo vai para revisão e
nada dele é movido. Nunca move a última cópia.

'duplicatas_excluir' é criada uma única vez, na pasta-mãe mais próxima cujo nome tem 3 caracteres
(ex.: a sigla do centro), e reaproveitada nas rodadas seguintes. Nada é excluído.

USO:
  python src/dedup.py
DESFAZER:
  python src/ops.py undo --log out/log_dedup_AAAAMMDD_HHMMSS.csv --apply
"""
import csv
import re
import sys
from datetime import datetime

import pandas as pd
from googleapiclient.errors import HttpError

from arvore import FOLDER, walk
from drive import RAIZ, connect
from ops import get, move

QUARENTENA = "duplicatas_excluir"
MARCADOR = re.compile(r"c[óo]pia|\bcopy\b|\(\d+\)", re.IGNORECASE)
GAPPS = "application/vnd.google-apps."
ALL = dict(supportsAllDrives=True)
COLS = ["acao", "file_id", "nome", "path", "de", "md5", "size", "manter_id", "manter_path"]


def pede_pasta():
    txt = input("ID ou link da pasta: ").strip()
    m = re.search(r"/folders/([\w-]+)", txt)
    return m.group(1) if m else txt


def ancestral_3(drive, folder_id):
    # Sobe a partir da pasta escolhida (inclusive) até achar um nome com exatamente 3 caracteres.
    atual = folder_id
    for _ in range(50):
        f = get(drive, atual, "id, name, parents")
        if len(f["name"].strip()) == 3:
            return f
        if not f.get("parents"):
            return None
        atual = f["parents"][0]
    return None


def acha_quarentena(drive, parent_id):
    q = f"name = '{QUARENTENA}' and '{parent_id}' in parents and mimeType = '{FOLDER}' and trashed = false"
    achadas = drive.files().list(q=q, fields="files(id)", supportsAllDrives=True,
                                 includeItemsFromAllDrives=True).execute().get("files", [])
    return achadas[0]["id"] if achadas else None


def dentro_de(info, fid, alvo):
    p = fid
    while p:
        if p == alvo:
            return True
        p = info[p]["parent"]
    return False


def planejar(info, quarentena_id=None):
    rows = []
    for fid, f in info.items():
        if f["mimeType"] == FOLDER or f["mimeType"].startswith(GAPPS) or not f.get("md5Checksum"):
            continue  # pastas, nativos do Google e atalhos não têm md5: ficam fora
        if quarentena_id in info and dentro_de(info, fid, quarentena_id):
            continue  # o que já está na quarentena não entra
        rows.append({"file_id": fid, "nome": f["name"], "path": f["path"], "de": f["parent"],
                     "md5": f["md5Checksum"], "size": f.get("size", ""),
                     "marcador": bool(MARCADOR.search(f["name"]))})
    df = pd.DataFrame(rows, columns=["file_id", "nome", "path", "de", "md5", "size", "marcador"])
    df = df[df.duplicated(["md5", "size"], keep=False)]

    saida = []
    for _, g in df.groupby(["md5", "size"]):
        limpos, marcados = g[~g["marcador"]], g[g["marcador"]]
        if limpos.empty:
            keep, acoes = None, {fid: "revisar" for fid in g["file_id"]}  # todos com marcador: decidir à mão
        else:
            keep = limpos.iloc[0]
            acoes = {fid: "mover" for fid in marcados["file_id"]}
            sem_marca = "manter" if len(limpos) == 1 else "revisar"  # 2+ sem marcador: decidir à mão
            acoes.update({fid: sem_marca for fid in limpos["file_id"]})
        for r in g.itertuples():
            saida.append({"acao": acoes[r.file_id], "file_id": r.file_id, "nome": r.nome, "path": r.path,
                          "de": r.de, "md5": r.md5, "size": r.size,
                          "manter_id": keep.file_id if keep is not None else "",
                          "manter_path": keep.path if keep is not None else ""})
    return pd.DataFrame(saida, columns=COLS).sort_values(["md5", "acao", "path"])


def verifica(drive, row):
    # Antes de mover: o arquivo continua igual e a cópia que fica ainda existe, igual.
    a = get(drive, row.file_id, "md5Checksum, trashed, parents")
    k = get(drive, row.manter_id, "md5Checksum, trashed")
    if a.get("trashed") or a.get("md5Checksum") != row.md5 or a["parents"][0] != row.de:
        return "arquivo mudou desde o plano"
    if k.get("trashed") or k.get("md5Checksum") != row.md5:
        return "cópia que fica sumiu ou mudou"
    return None


def novo_arquivo(tipo):
    base = RAIZ / "out" / f"{tipo}_{datetime.now():%Y%m%d_%H%M%S}"
    base.parent.mkdir(parents=True, exist_ok=True)
    path, n = base.with_suffix(".csv"), 2
    while path.exists():
        path, n = base.with_name(f"{base.name}_{n}.csv"), n + 1
    return path


if __name__ == "__main__":
    pasta = pede_pasta()
    leitura = connect()
    root_id, info = walk(leitura, pasta)

    anc = ancestral_3(leitura, root_id)
    if anc is None:
        r = input(f"Nenhuma pasta-mãe com nome de 3 caracteres. Criar '{QUARENTENA}' dentro da pasta escolhida? [s/N] ")
        if r.strip().lower() != "s":
            sys.exit("Cancelado.")
        anc = {"id": root_id, "name": info[root_id]["name"]}

    plano = planejar(info, acha_quarentena(leitura, anc["id"]))
    plano_path = novo_arquivo("plano_dedup")
    plano.to_csv(plano_path, index=False, encoding="utf-8-sig")

    mover = plano[plano["acao"] == "mover"]
    n_grupos = plano["md5"].nunique()
    print(f"\n{n_grupos} grupos de duplicatas | mover: {len(mover)} | "
          f"revisar à mão: {int((plano['acao'] == 'revisar').sum())}")
    print(f"plano: {plano_path}\n")
    if mover.empty:
        sys.exit("Nada a mover.")
    print(mover[["path", "manter_path"]].rename(columns={"path": "sai", "manter_path": "fica"})
          .to_string(index=False, max_rows=20))

    destino = f"{anc['name']}/{QUARENTENA}"
    if input(f"\nMover {len(mover)} arquivos para '{destino}'? Digite SIM para confirmar: ").strip() != "SIM":
        sys.exit("Cancelado. Nada foi alterado.")

    drive = connect(write=True)
    q_id = acha_quarentena(drive, anc["id"])
    log_path = novo_arquivo("log_dedup")
    ok = 0
    with open(log_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["quando", "op", "file_id", "nome", "de", "para", "status"])
        if q_id is None:
            q_id = drive.files().create(body={"name": QUARENTENA, "mimeType": FOLDER, "parents": [anc["id"]]},
                                        fields="id", **ALL).execute()["id"]
            # status "criada" (não "ok"): o undo ignora esta linha
            w.writerow([datetime.now().isoformat(timespec="seconds"), "criar_pasta", q_id, QUARENTENA,
                        "", anc["id"], "criada"])
            print(f"criada: {destino}")
        for row in mover.itertuples():
            try:
                problema = verifica(drive, row)
                if problema:
                    status = f"PULADO: {problema}"
                else:
                    move(drive, row.file_id, q_id)
                    status = "ok"
            except HttpError as e:
                status = f"ERRO {e.resp.status}"
            ok += status == "ok"
            w.writerow([datetime.now().isoformat(timespec="seconds"), "dedup", row.file_id, row.nome,
                        row.de, q_id, status])
            fh.flush()
            print(f"  {status:<36} {row.nome}")
    print(f"\n{ok}/{len(mover)} ok  ->  log: {log_path}")
    print(f"desfazer: python src\\ops.py undo --log out\\{log_path.name} --apply")