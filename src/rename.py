"""Renomeação em lote por substituição de texto no nome.

Pede a pasta, o texto atual e o texto novo, e varre a pasta inteira (subpastas incluídas).
  padrão     casa quando o texto aparece em qualquer parte do nome; troca só esse trecho
  --exato    casa quando o nome inteiro é igual ao texto; o nome novo é o texto novo inteiro
  --pastas   só pastas      |  --arquivos  só arquivos   (sem flag: os dois)
Plano na tela -> SIM -> renomeia com log. O primeiro nome original fica gravado nos metadados
do próprio arquivo (properties.nome_original).

USO:
  python src/rename.py [--pastas | --arquivos] [--exato]
  python src/rename.py --undo out/log_rename_AAAAMMDD_HHMMSS.csv
"""
import argparse
import csv
import re
import sys
from datetime import datetime

import pandas as pd
from googleapiclient.errors import HttpError

from arvore import FOLDER, walk
from drive import RAIZ, connect
from ops import get

ALL = dict(supportsAllDrives=True)
LOG = ["quando", "op", "file_id", "nome", "nome_novo", "de", "para", "status"]


def pede_pasta():
    txt = input("ID ou link da pasta: ").strip()
    m = re.search(r"/folders/([\w-]+)", txt)
    return m.group(1) if m else txt


def planejar(info, root_id, velho, novo, exato, tipo):
    rows = []
    for fid, f in info.items():
        if fid == root_id:
            continue
        pasta = f["mimeType"] == FOLDER
        if (tipo == "pastas" and not pasta) or (tipo == "arquivos" and pasta):
            continue
        nome = f["name"]
        casa = nome == velho if exato else velho in nome
        nome_novo = novo if exato else nome.replace(velho, novo)
        if casa and nome_novo != nome:
            rows.append({"file_id": fid, "tipo": "pasta" if pasta else "arquivo", "nome": nome,
                         "nome_novo": nome_novo, "parent": f["parent"], "path": f["path"]})
    plano = pd.DataFrame(rows, columns=["file_id", "tipo", "nome", "nome_novo", "parent", "path", "status_plano"])
    if plano.empty:
        return plano

    # Colisão: depois da troca, dois itens da mesma pasta ficariam com o mesmo nome.
    final = {fid: f["name"] for fid, f in info.items() if fid != root_id}
    final.update(dict(zip(plano["file_id"], plano["nome_novo"])))
    contagem = pd.Series([(info[fid]["parent"], n) for fid, n in final.items()]).value_counts()
    colide = [contagem[(p, n)] > 1 for p, n in zip(plano["parent"], plano["nome_novo"])]
    vazio = plano["nome_novo"].str.strip() == ""
    plano["status_plano"] = "ok"
    plano.loc[colide, "status_plano"] = "COLISAO"
    plano.loc[vazio, "status_plano"] = "NOME_VAZIO"
    return plano.sort_values("path")


def renomeia(drive, file_id, esperado, novo, grava_original=True):
    # Só renomeia se o nome atual ainda for o esperado; guarda o primeiro nome original nos metadados.
    f = get(drive, file_id, "name, properties")
    if f["name"] != esperado:
        return "PULADO: nome mudou desde o plano"
    body = {"name": novo}
    if grava_original and "nome_original" not in (f.get("properties") or {}):
        body["properties"] = {"nome_original": esperado}
    drive.files().update(fileId=file_id, body=body, **ALL).execute()
    return "ok"


def novo_arquivo(nome):
    # Um arquivo novo por execução; nunca sobrescreve.
    base = RAIZ / "out" / f"{nome}_{datetime.now():%Y%m%d_%H%M%S}"
    base.parent.mkdir(parents=True, exist_ok=True)
    path, n = base.with_suffix(".csv"), 2
    while path.exists():
        path, n = base.with_name(f"{base.name}_{n}.csv"), n + 1
    return path


def executa(drive, linhas, op, path):
    ok = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(LOG)
        for r in linhas:
            try:
                status = renomeia(drive, r["file_id"], r["de_nome"], r["para_nome"], grava_original=(op == "rename"))
            except HttpError as e:
                status = f"ERRO {e.resp.status}"
            ok += status == "ok"
            w.writerow([datetime.now().isoformat(timespec="seconds"), op, r["file_id"],
                        r["de_nome"], r["para_nome"], r["parent"], r["parent"], status])
            fh.flush()
            print(f"  {status:<34} {r['de_nome']}  ->  {r['para_nome']}")
    print(f"\n{ok}/{len(linhas)} ok  ->  log: {path}")
    return path


def cmd_undo(log_file):
    log = pd.read_csv(RAIZ / log_file, dtype=str, keep_default_na=False)
    feitos = log[(log["status"] == "ok") & (log["op"] == "rename")].iloc[::-1]
    print(f"{len(feitos)} renomeações a desfazer (de {len(log)} no log)")
    if feitos.empty:
        return
    print(feitos[["nome_novo", "nome"]].rename(columns={"nome_novo": "atual", "nome": "volta para"})
          .to_string(index=False, max_rows=20))
    if input("\nDesfazer? Digite SIM para confirmar: ").strip() != "SIM":
        sys.exit("Cancelado. Nada foi alterado.")
    linhas = [{"file_id": r.file_id, "de_nome": r.nome_novo, "para_nome": r.nome, "parent": r.de}
              for r in feitos.itertuples()]
    executa(connect(write=True), linhas, "undo_rename", novo_arquivo("log_rename_undo"))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    alvo = p.add_mutually_exclusive_group()
    alvo.add_argument("--pastas", action="store_true", help="só pastas")
    alvo.add_argument("--arquivos", action="store_true", help="só arquivos")
    p.add_argument("--exato", action="store_true", help="o nome inteiro tem que ser igual ao texto")
    p.add_argument("--undo", metavar="LOG", help="desfaz a partir de um log de rename")
    args = p.parse_args()

    if args.undo:
        cmd_undo(args.undo)
        sys.exit()

    tipo = "pastas" if args.pastas else "arquivos" if args.arquivos else "tudo"
    pasta = pede_pasta()
    velho = input("Texto atual: ")
    novo = input("Texto novo (vazio = remover o trecho): ")
    if not velho:
        sys.exit("Texto atual vazio. Cancelado.")

    root_id, info = walk(connect(), pasta)
    plano = planejar(info, root_id, velho, novo, args.exato, tipo)
    modo = "nome exato" if args.exato else "trecho do nome"
    print(f"\nbusca: '{velho}' -> '{novo}'  ({modo}, {tipo})")
    if plano.empty:
        sys.exit("Nenhum item casou.")

    plano_path = novo_arquivo("plano_rename")
    plano.to_csv(plano_path, index=False, encoding="utf-8-sig")
    ok = plano[plano["status_plano"] == "ok"]
    fora = plano[plano["status_plano"] != "ok"]
    print(f"{len(ok)} a renomear | {len(fora)} de fora (colisão ou nome vazio)\nplano: {plano_path}\n")
    if not ok.empty:
        print(ok[["path", "nome_novo"]].rename(columns={"path": "atual", "nome_novo": "novo nome"})
              .to_string(index=False, max_rows=25))
    if not fora.empty:
        print("\nDE FORA:\n" + fora[["path", "nome_novo", "status_plano"]].to_string(index=False, max_rows=10))
    if ok.empty:
        sys.exit("\nNada a renomear.")

    if input(f"\nRenomear {len(ok)} itens? Digite SIM para confirmar: ").strip() != "SIM":
        sys.exit("Cancelado. Nada foi alterado.")
    linhas = [{"file_id": r.file_id, "de_nome": r.nome, "para_nome": r.nome_novo, "parent": r.parent}
              for r in ok.itertuples()]
    log = executa(connect(write=True), linhas, "rename", novo_arquivo("log_rename"))
    print(f"desfazer: python src\\rename.py --undo out\\{log.name}")