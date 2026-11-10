"""Achatar uma pasta: traz todos os arquivos das subpastas para a raiz.

O nome da subpasta é metadado: entra no nome do arquivo como prefixo, para não se perder.
Plano primeiro (só leitura); apply sem --apply é dry-run; undo desfaz (devolve e restaura o nome).

USO:
  python src/flatten.py plan  --root <ID_PASTA> --out out/plano_flatten.csv
  python src/flatten.py apply --plan out/plano_flatten.csv [--quarentena <ID>] [--limit N] [--apply]
  python src/flatten.py undo  --log out/log_flatten_AAAAMMDD_HHMMSS.csv [--apply]
"""
import argparse
import csv
from datetime import datetime

import pandas as pd
from googleapiclient.errors import HttpError

from arvore import FOLDER, walk
from drive import RAIZ, connect
from ops import get, move, rename

COLS = ["file_id", "nome", "nome_novo", "de", "para", "subpasta_topo", "path", "status_plano"]
LOG = ["quando", "op", "file_id", "nome", "nome_novo", "de", "para", "status"]


def subpastas(info, fid, root_id):
    # Nomes das pastas entre a raiz e o arquivo, de cima para baixo.
    nomes, p = [], info[fid]["parent"]
    while p != root_id:
        nomes.insert(0, info[p]["name"])
        p = info[p]["parent"]
    return nomes


def topo(info, fid, root_id):
    # A subpasta de primeiro nível (filha direta da raiz) que contém este item.
    p = fid
    while info[p]["parent"] != root_id:
        p = info[p]["parent"]
    return p


def plan_flatten(info, root_id, sep):
    rows = []
    for fid, f in info.items():
        if fid == root_id or f["mimeType"] == FOLDER or f["parent"] == root_id:
            continue
        rows.append({
            "file_id": fid,
            "nome": f["name"],
            "nome_novo": sep.join(subpastas(info, fid, root_id) + [f["name"]]),
            "de": f["parent"],
            "para": root_id,
            "subpasta_topo": topo(info, fid, root_id),
            "path": f["path"],
        })
    plano = pd.DataFrame(rows, columns=COLS[:-1])
    # Colisão: dois arquivos ganhariam o mesmo nome, ou o nome já existe na raiz.
    na_raiz = {f["name"] for f in info.values() if f["parent"] == root_id and f["mimeType"] != FOLDER}
    colide = plano["nome_novo"].duplicated(keep=False) | plano["nome_novo"].isin(na_raiz)
    plano["status_plano"] = colide.map({True: "COLISAO", False: "ok"})
    return plano.sort_values("path")


def novo_log(tipo):
    # Um arquivo novo por execução; nunca sobrescreve um log existente.
    base = RAIZ / "out" / f"log_{tipo}_{datetime.now():%Y%m%d_%H%M%S}"
    base.parent.mkdir(parents=True, exist_ok=True)
    path, n = base.with_suffix(".csv"), 2
    while path.exists():
        path, n = base.with_name(f"{base.name}_{n}.csv"), n + 1
    return path


def cmd_plan(args):
    drive = connect()
    root_id, info = walk(drive, args.root)
    plano = plan_flatten(info, root_id, args.sep)
    out = RAIZ / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    plano.to_csv(out, index=False, encoding="utf-8-sig")
    n_col = int((plano["status_plano"] == "COLISAO").sum())
    print(f"{len(plano)} arquivos em subpastas | {len(plano) - n_col} ok | {n_col} com colisão de nome")
    print(f"  plano: {out}")


def cmd_apply(args):
    todos = pd.read_csv(RAIZ / args.plan, dtype=str)
    plano = todos[todos["status_plano"] == "ok"]
    if args.limit:
        plano = plano.head(args.limit)
    print(f"{len(plano)} arquivos -> raiz (colisões ficam de fora: {int((todos['status_plano'] != 'ok').sum())})")
    if not args.apply:
        print(plano[["path", "nome_novo"]].to_string(index=False, max_rows=20))
        print("\nDRY-RUN: nada foi alterado. Rode de novo com --apply.")
        return

    drive = connect(write=True)
    movidos, log = set(), novo_log("flatten")
    with open(log, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(LOG)
        for row in plano.itertuples():
            try:
                atual = get(drive, row.file_id, "parents")["parents"][0]
                if atual != row.de:
                    status = "PULADO: mudou de pasta desde o plano"
                else:
                    move(drive, row.file_id, row.para)
                    rename(drive, row.file_id, row.nome_novo)
                    status = "ok"
                    movidos.add(row.file_id)
            except HttpError as e:
                status = f"ERRO {e.resp.status}"
            w.writerow([datetime.now().isoformat(timespec="seconds"), "flatten", row.file_id,
                        row.nome, row.nome_novo, row.de, row.para, status])
            fh.flush()
            print(f"  {status:<38} {row.nome_novo}")

        # Subpastas que ficaram sem nenhum arquivo vão inteiras para a quarentena (nada é excluído).
        if args.quarentena:
            for topo_id, grupo in todos.groupby("subpasta_topo"):
                if not set(grupo["file_id"]) <= movidos:
                    continue
                try:
                    nome = get(drive, topo_id, "name")["name"]
                    de = move(drive, topo_id, args.quarentena)
                    status = "ok"
                except HttpError as e:
                    nome, de, status = "", "", f"ERRO {e.resp.status}"
                w.writerow([datetime.now().isoformat(timespec="seconds"), "quarantine_pasta", topo_id,
                            nome, "", de, args.quarentena, status])
                fh.flush()
                print(f"  {status:<38} [pasta vazia -> quarentena] {nome}")
    print(f"{len(movidos)}/{len(plano)} ok  ->  log: {log}")


def cmd_undo(args):
    log = pd.read_csv(RAIZ / args.log, dtype=str, keep_default_na=False)
    feitos = log[log["status"] == "ok"].iloc[::-1]  # ordem inversa: pastas voltam antes dos arquivos
    print(f"{len(feitos)} operações a desfazer (de {len(log)} no log)")
    if not args.apply:
        print(feitos[["op", "nome", "nome_novo"]].to_string(index=False, max_rows=20))
        print("\nDRY-RUN: nada foi alterado. Rode de novo com --apply.")
        return

    drive = connect(write=True)
    out = novo_log("flatten_undo")
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(LOG)
        for row in feitos.itertuples():
            try:
                move(drive, row.file_id, row.de)
                if row.nome_novo:
                    rename(drive, row.file_id, row.nome)
                status = "ok"
            except HttpError as e:
                status = f"ERRO {e.resp.status}"
            w.writerow([datetime.now().isoformat(timespec="seconds"), "undo_" + row.op, row.file_id,
                        row.nome_novo, row.nome, row.para, row.de, status])
            fh.flush()
            print(f"  {status:<38} {row.nome}")
    print(f"log do undo: {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("plan", help="gera o plano (só leitura)")
    pl.add_argument("--root", required=True, help="ID da pasta a achatar")
    pl.add_argument("--out", required=True, help="CSV do plano, ex: out/plano_flatten.csv")
    pl.add_argument("--sep", default=" - ", help='separador entre subpasta e nome (padrão: " - ")')

    ap = sub.add_parser("apply", help="executa o plano")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--quarentena", help="ID da quarentena para as subpastas que ficarem vazias")
    ap.add_argument("--limit", type=int, help="só as N primeiras linhas (para testar)")
    ap.add_argument("--apply", action="store_true", help="sem isso, é só dry-run")

    un = sub.add_parser("undo", help="desfaz a partir do log")
    un.add_argument("--log", required=True)
    un.add_argument("--apply", action="store_true")

    args = p.parse_args()
    {"plan": cmd_plan, "apply": cmd_apply, "undo": cmd_undo}[args.cmd](args)