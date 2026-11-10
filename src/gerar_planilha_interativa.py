"""Joga o índice (out/indice.csv, gerado pelo indice.py) numa planilha Google, com chips de pasta.

Pede o link de uma planilha que você já criou (pode estar vazia). Apaga o conteúdo da primeira aba
e escreve: Nível 1 | Nível 2 | ... | Edificação | [01] ... [07] [99] (títulos fixos).
- Um nível da hierarquia por coluna; o nome de um nível só aparece na primeira linha do seu grupo
  (as linhas seguintes ficam em branco), para a indentação ficar visível.
- Cada pasta é reconhecida pelo código no início do nome ("[01] ...") e vai sempre para a coluna dele.
- Pasta que deveria existir e não existe: "Ausente".
- Pasta sem código ou com código fora da lista: fica de fora da planilha.
Cada célula com pasta é um chip que abre a pasta. Se o Google recusar os chips, usa links comuns.

USO:
  python src/gerar_planilha_interativa.py
  python src/gerar_planilha_interativa.py --csv out/indice_ccs.csv
"""
import argparse
import re
import sys

import pandas as pd
from googleapiclient.errors import HttpError

from drive import RAIZ, connect_sheets

CODIGOS = ["01", "02", "03", "04", "05", "06", "07", "99"]
PADRAO = {"01": "[01] Documentação Arquitetônica", "02": "[02] Documentação Legal", "03": "[03] Fotos",
          "04": "[04] Inventário", "05": "[05] Cessão de Área", "06": "[06] Projetos Recebidos",
          "07": "[07] Original", "99": "[99] Arquivo"}  # títulos fixos das colunas
COD = re.compile(r"^\s*\[(\d+)\]")
NIVEL = re.compile(r"^nivel_(\d+)$")
BASE = ("grupo", "edificacao", "edificacao_url")
VERDE = {"red": 0.24, "green": 0.35, "blue": 0.28}
BRANCO = {"red": 1, "green": 1, "blue": 1}


def pede_planilha():
    txt = input("Link da planilha: ").strip()
    m = re.search(r"/d/([\w-]+)", txt)
    return m.group(1) if m else txt


def texto(v):
    return {"userEnteredValue": {"stringValue": v}}


def chip(url):
    return {"userEnteredValue": {"stringValue": "@"},
            "chipRuns": [{"startIndex": 0, "chip": {"richLinkProperties": {"uri": url}}}]}


def link(url, rotulo):
    return {"userEnteredValue": {"stringValue": rotulo},
            "textFormatRuns": [{"startIndex": 0, "format": {"link": {"uri": url}}}]}


def celula(url, rotulo, usar_chip):
    return chip(url) if usar_chip else link(url, rotulo)


def organiza(df, codigos):
    # Agrupa as colunas do CSV (uma por nome de pasta) pelo código; o resto vai para "fora do padrão".
    por_cod, fora = {c: [] for c in codigos}, []
    for col in df.columns:
        if col in BASE or col.startswith("nivel_"):
            continue
        m = COD.match(col)
        (por_cod[m.group(1)] if m and m.group(1) in por_cod else fora).append(col)
    # Título da coluna: o nome mais usado para aquele código.
    titulos = {c: PADRAO.get(c, f"[{c}]") for c in por_cod}
    return por_cod, fora, titulos


def niveis(df):
    return sorted(int(m.group(1)) for c in df.columns if (m := NIVEL.match(c)))


def monta_linhas(df, codigos, usar_chip):
    por_cod, fora, titulos = organiza(df, codigos)
    nv = niveis(df)
    hierarquia = [f"Nível {i}" for i in nv] if nv else ["Grupo"]
    cab = hierarquia + ["Edificação"] + [titulos[c] for c in codigos]
    linhas = [{"values": [{**texto(c), "userEnteredFormat": {
        "backgroundColor": VERDE, "textFormat": {"bold": True, "foregroundColor": BRANCO}}} for c in cab]}]
    anterior = []
    for d in df.to_dict("records"):  # dict, não itertuples: nomes como "[01] ..." viram _2, _3 em tuplas
        if nv:
            atual = [d[f"nivel_{i}"] for i in nv]
            vals = []
            for k, i in enumerate(nv):
                mesmo_grupo = anterior[:k + 1] == atual[:k + 1]  # nível repetido: célula em branco
                vals.append(texto("") if mesmo_grupo else
                            celula(d[f"nivel_{i}_url"], d[f"nivel_{i}"], usar_chip))
            anterior = atual
        else:
            vals = [texto(d["grupo"])]
        vals.append(celula(d["edificacao_url"], d["edificacao"], usar_chip))
        for c in codigos:
            achadas = [col for col in por_cod[c] if d[col]]
            vals.append(celula(d[achadas[0]], achadas[0], usar_chip) if achadas else texto("Ausente"))
        linhas.append({"values": vals})
    return linhas


def requests(sheet_id, linhas, n_cols, n_fixas):
    return [
        {"updateCells": {"range": {"sheetId": sheet_id}, "fields": "*"}},  # limpa a aba inteira
        {"updateCells": {"rows": linhas, "fields": "*",
                         "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0}}},
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id,
                                                  "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": n_fixas}},
                                   "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
        {"autoResizeDimensions": {"dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                                                 "startIndex": 0, "endIndex": n_cols}}},
    ]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="out/indice.csv", help="CSV do indice.py (padrão: out/indice.csv)")
    args = p.parse_args()

    df = pd.read_csv(RAIZ / args.csv, dtype=str, keep_default_na=False)
    df.columns = [c.lstrip("\ufeff") for c in df.columns]
    _, fora, _ = organiza(df, CODIGOS)
    print(f"{len(df)} edificações  ({args.csv})")
    if fora:
        print(f"(fora da planilha, sem código da lista: {', '.join(fora)})")

    planilha_id = pede_planilha()
    sheets = connect_sheets()
    meta = sheets.spreadsheets().get(spreadsheetId=planilha_id, fields="properties.title,sheets.properties").execute()
    aba = meta["sheets"][0]["properties"]
    print(f"planilha: {meta['properties']['title']}  |  aba: {aba['title']}")
    if input("Apagar o conteúdo dessa aba e escrever o índice? Digite SIM: ").strip() != "SIM":
        sys.exit("Cancelado. Nada foi alterado.")

    nv = niveis(df)
    if nv:
        df = df.sort_values([f"nivel_{i}" for i in nv] + ["edificacao"])
    n_fixas = (len(nv) or 1) + 1
    n_cols = n_fixas + len(CODIGOS)
    for usar_chip in (True, False):
        try:
            body = {"requests": requests(aba["sheetId"], monta_linhas(df, CODIGOS, usar_chip), n_cols, n_fixas)}
            sheets.spreadsheets().batchUpdate(spreadsheetId=planilha_id, body=body).execute()
            print("pronto, com chips." if usar_chip else "pronto, com links comuns (o Google recusou os chips).")
            break
        except HttpError as e:
            if not usar_chip:
                raise
            print(f"chips recusados ({e.resp.status}); tentando com links comuns...")
    print(f"https://docs.google.com/spreadsheets/d/{planilha_id}")
