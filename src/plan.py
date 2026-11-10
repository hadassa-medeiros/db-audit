"""Plano de dedup A x B. Só pandas: não toca no Drive.

Duplicata = mesmo md5 + mesmo tamanho. A cópia em B fica; a de A vai para o plano de quarentena.
Arquivos nativos do Google (Docs/Sheets/...) e atalhos não têm md5: ficam fora do match
automático e vão para uma lista de revisão manual.

USO:
  python src/plan.py --a out/inv_A.csv --b out/inv_B.csv --out out/plano.csv
"""
import argparse
import sys

import pandas as pd

from drive import RAIZ

GAPPS = "application/vnd.google-apps."
FOLDER = GAPPS + "folder"
# aceita tanto o CSV do inventory.py quanto o do arvore.py
RENOMEAR = {"md5Checksum": "md5", "tamanho_bytes": "size", "nome": "name"}


def load(path):
    df = pd.read_csv(path, dtype=str).rename(columns=RENOMEAR)
    df["md5"] = df["md5"].fillna("").str.strip()
    df["size"] = df["size"].fillna("").str.strip()
    return df


def candidatos(df):
    # Só arquivos binários com md5. Sem isso, vazios casariam com vazios (o bug do incidente).
    nativo = df["mimeType"].str.startswith(GAPPS)
    return df[~nativo & (df["md5"] != "")]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True, help="inventário do conjunto A (de onde sai)")
    p.add_argument("--b", required=True, help="inventário do conjunto B (onde fica)")
    p.add_argument("--out", required=True, help="CSV do plano, ex: out/plano.csv")
    args = p.parse_args()

    a, b = load(RAIZ / args.a), load(RAIZ / args.b)

    comum = set(a["id"]) & set(b["id"])
    if comum:
        sys.exit(f"ABORTADO: {len(comum)} itens aparecem em A e em B. As pastas se sobrepõem?")

    ca, cb = candidatos(a), candidatos(b)
    chave_b = (cb.drop_duplicates(["md5", "size"])[["md5", "size", "id", "path"]]
                 .rename(columns={"id": "match_id_b", "path": "path_b"}))
    plano = ca.merge(chave_b, on=["md5", "size"], how="inner")
    plano = (plano.assign(op="quarantine")
                  [["op", "id", "name", "path", "parent", "md5", "size", "match_id_b", "path_b"]]
                  .rename(columns={"id": "file_id", "path": "path_a", "parent": "src_parent"})
                  .sort_values("path_a"))

    out = RAIZ / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    plano.to_csv(out, index=False, encoding="utf-8-sig")

    nativos = a[a["mimeType"].str.startswith(GAPPS) & (a["mimeType"] != FOLDER)]
    revisao = out.with_name(out.stem + "_revisao_manual.csv")
    nativos[["name", "path", "mimeType", "id"]].to_csv(revisao, index=False, encoding="utf-8-sig")

    arquivos_a = int((a["mimeType"] != FOLDER).sum())
    print(f"A: {arquivos_a} arquivos | candidatos com md5: {len(ca)}")
    print(f"B: {len(cb)} candidatos com md5")
    print(f"duplicatas A->B (vão para quarentena): {len(plano)}")
    print(f"nativos do Google em A (revisão manual): {len(nativos)}")
    print(f"  plano:   {out}\n  revisão: {revisao}")
