"""Operações de escrita no Drive. Todas reversíveis; nada é excluído.

USO:
  python src/ops.py apply --plan out/plano.csv --quarentena <ID_PASTA>            (dry-run)
  python src/ops.py apply --plan out/plano.csv --quarentena <ID_PASTA> --limit 3 --apply
  python src/ops.py undo  --log out/log_quarantine_AAAAMMDD_HHMMSS.csv --apply
  python src/ops.py rename --id <ID> --name "novo nome"
  python src/ops.py move   --id <ID> --dst <ID_PASTA>
"""
import argparse
import csv
from datetime import datetime

import pandas as pd
from googleapiclient.errors import HttpError

from drive import connect, RAIZ

ALL = dict(supportsAllDrives=True)


def get(drive, file_id, fields):
    return drive.files().get(fileId=file_id, fields=fields, **ALL).execute()


def rename(drive, file_id, new_name):
    # Troca o nome e devolve o antigo (para desfazer).
    old = get(drive, file_id, "name")["name"]
    drive.files().update(fileId=file_id, body={"name": new_name}, **ALL).execute()
    return old


def move(drive, file_id, dst_id):
    # Troca a pasta-mãe e devolve a antiga; se já está no destino, não faz nada.
    src_id = get(drive, file_id, "parents")["parents"][0]
    if src_id != dst_id:
        drive.files().update(fileId=file_id, addParents=dst_id, removeParents=src_id,
                             fields="id, parents", **ALL).execute()
    return src_id


def check(drive, row):
    # Antes de mexer: A continua igual ao plano e a cópia em B ainda existe, igual.
    a = get(drive, row.file_id, "md5Checksum, trashed")
    b = get(drive, row.match_id_b, "md5Checksum, trashed")
    if a.get("trashed"):
        return "A já está na lixeira"
    if a.get("md5Checksum") != row.md5:
        return "A mudou desde o plano"
    if b.get("trashed") or b.get("md5Checksum") != row.md5:
        return "cópia em B sumiu ou mudou"
    return None


def log_path(op):
    return RAIZ / "out" / f"log_{op}_{datetime.now():%Y%m%d_%H%M%S}.csv"


def run(drive, rows, op, acao, path):
    # Executa linha a linha e grava o log na hora (se cair no meio, o log vale até ali).
    ok = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["quando", "op", "file_id", "nome", "de", "para", "status"])
        for row in rows:
            de, para = "", ""
            try:
                de, para, status = acao(row)
            except HttpError as e:
                status = f"ERRO {e.resp.status}"
            ok += status == "ok"
            w.writerow([datetime.now().isoformat(timespec="seconds"), op, row.file_id, row.nome, de, para, status])
            fh.flush()
            print(f"  {status:<32} {row.nome}")
    print(f"{ok}/{len(rows)} ok  ->  log: {path}")


def cmd_apply(args):
    plano = pd.read_csv(RAIZ / args.plan, dtype=str).rename(columns={"name": "nome"})
    if args.limit:
        plano = plano.head(args.limit)
    print(f"{len(plano)} arquivos -> quarentena {args.quarentena}")
    if not args.apply:
        print(plano[["nome", "path_a", "path_b"]].to_string(index=False, max_rows=20))
        print("\nDRY-RUN: nada foi alterado. Rode de novo com --apply.")
        return
    drive = connect(write=True)

    def acao(row):
        problema = check(drive, row)
        if problema:
            return "", "", f"PULADO: {problema}"
        return move(drive, row.file_id, args.quarentena), args.quarentena, "ok"

    run(drive, list(plano.itertuples()), "quarantine", acao, log_path("quarantine"))


def cmd_undo(args):
    log = pd.read_csv(RAIZ / args.log, dtype=str)
    feitos = log[log["status"] == "ok"]
    print(f"{len(feitos)} operações a desfazer (de {len(log)} no log)")
    if not args.apply:
        print(feitos[["nome", "para", "de"]].to_string(index=False, max_rows=20))
        print("\nDRY-RUN: nada foi alterado. Rode de novo com --apply.")
        return
    drive = connect(write=True)

    def acao(row):
        move(drive, row.file_id, row.de)  # volta para a pasta de origem
        return row.para, row.de, "ok"

    run(drive, list(feitos.itertuples()), "undo", acao, log_path("undo"))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("apply", help="executa um plano de quarentena")
    a.add_argument("--plan", required=True)
    a.add_argument("--quarentena", required=True, help="ID da pasta de quarentena")
    a.add_argument("--limit", type=int, help="só as N primeiras linhas (para testar)")
    a.add_argument("--apply", action="store_true", help="sem isso, é só dry-run")

    u = sub.add_parser("undo", help="desfaz um log de quarentena")
    u.add_argument("--log", required=True)
    u.add_argument("--apply", action="store_true")

    r = sub.add_parser("rename")
    r.add_argument("--id", required=True)
    r.add_argument("--name", required=True)

    m = sub.add_parser("move")
    m.add_argument("--id", required=True)
    m.add_argument("--dst", required=True)

    args = p.parse_args()
    if args.cmd == "apply":
        cmd_apply(args)
    elif args.cmd == "undo":
        cmd_undo(args)
    elif args.cmd == "rename":
        old = rename(connect(write=True), args.id, args.name)
        print(f"'{old}' -> '{args.name}'   desfazer: rename --id {args.id} --name \"{old}\"")
    elif args.cmd == "move":
        src = move(connect(write=True), args.id, args.dst)
        print(f"{src} -> {args.dst}   desfazer: move --id {args.id} --dst {src}")
