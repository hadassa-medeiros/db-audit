"""Antes x depois: compara um retrato antigo do Drive com o de hoje e conta arquivos por tipo.

Funciona com qualquer retrato que tenha uma coluna de ID do arquivo (CSV ou parquet). As colunas são
reconhecidas pelo nome (id/file_id, name/nome, path/full_path, mimeType/mime_type...).
O ID do Drive não muda quando o arquivo é movido ou renomeado, então é por ele que se compara.

Situação de cada arquivo:
  igual       mesmo nome, mesmo lugar
  movido      mesmo nome, outro lugar
  renomeado   outro nome (no mesmo lugar ou não)
  saiu        estava no retrato antigo e não está mais na pasta (quarentena, Arquivo, fora do escopo)
  novo        não existia no retrato antigo

USO:
  python src/comparar.py --antes snapshots/raw/<retrato_antigo>.parquet --depois out/arvore.csv
Opcional: no fim ele pergunta o link de uma planilha e cria nela uma aba nova com a tabela e o gráfico.
"""
import argparse
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from drive import RAIZ

PASTA = "application/vnd.google-apps.folder"
GAPPS = {"document": "GDOC", "spreadsheet": "GSHEET", "presentation": "GSLIDES", "form": "GFORM",
         "shortcut": "ATALHO"}
NOMES = {
    "id": ["id", "file_id", "fileid"],
    "nome": ["nome", "name", "title"],
    "caminho": ["path", "full_path", "caminho", "fullpath"],
    "mime": ["mimetype", "mime_type", "mime"],
    "lixeira": ["trashed", "lixeira"],
}


def carrega(arquivo):
    path = Path(arquivo) if Path(arquivo).is_absolute() else RAIZ / arquivo
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [str(c).lstrip("﻿") for c in df.columns]
    baixo = {c.lower(): c for c in df.columns}
    cols = {}
    for padrao, opcoes in NOMES.items():
        achada = next((baixo[o] for o in opcoes if o in baixo), None)
        if achada:
            cols[padrao] = achada
    if "id" not in cols or "nome" not in cols:
        raise SystemExit(f"{path.name}: não achei as colunas de ID e de nome. Colunas: {list(df.columns)}")
    out = pd.DataFrame({k: df[v].astype(str) for k, v in cols.items()})
    for falta in ["caminho", "mime", "lixeira"]:
        if falta not in out:
            out[falta] = ""
    out = out[~out["lixeira"].str.lower().isin(["true", "1"])]
    out = out[out["mime"] != PASTA]
    print(f"{path.name}: {len(out)} arquivos  (colunas usadas: {cols})")
    return out.drop_duplicates("id")


def tipo(row):
    m = row["mime"]
    if m.startswith("application/vnd.google-apps."):
        return GAPPS.get(m.rsplit(".", 1)[-1], "GOOGLE")
    nome = row["nome"]
    return nome.rsplit(".", 1)[-1].upper()[:8] if "." in nome else "SEM EXTENSÃO"


def pasta_de(caminho):
    return caminho.rstrip("/").rsplit("/", 1)[0] if "/" in caminho else ""


def no_escopo(antes, depois):
    # O retrato antigo pode cobrir o Drive inteiro: fica só com o que está sob a mesma pasta-raiz.
    raiz = depois["caminho"].str.split("/").str[0].mode()
    if raiz.empty or not raiz[0]:
        return antes
    r = re.escape(raiz[0])
    dentro = antes["caminho"].str.contains(rf"(?:^|/){r}(?:/|$)", regex=True) | antes["id"].isin(depois["id"])
    print(f"escopo: pasta '{raiz[0]}'  ->  {int(dentro.sum())} de {len(antes)} arquivos do retrato antigo")
    antes = antes[dentro].copy()
    # Caminhos no mesmo formato dos de hoje: começando na pasta-raiz (o retrato antigo pode ter mais níveis acima).
    antes["caminho"] = antes["caminho"].map(lambda c: corta(c, raiz[0]))
    return antes


def corta(caminho, raiz):
    partes = caminho.strip("/").split("/")
    return "/".join(partes[partes.index(raiz):]) if raiz in partes else caminho.strip("/")


def compara(antes, depois):
    j = antes.merge(depois, on="id", how="outer", suffixes=("_a", "_d"), indicator=True)

    def situacao(r):
        if r["_merge"] == "left_only":
            return "saiu"
        if r["_merge"] == "right_only":
            return "novo"
        if r["nome_a"] != r["nome_d"]:
            return "renomeado"
        return "igual" if pasta_de(r["caminho_a"]) == pasta_de(r["caminho_d"]) else "movido"

    j["situacao"] = j.apply(situacao, axis=1)
    return j


def por_tipo(antes, depois, maximo=12):
    a = antes.apply(tipo, axis=1).value_counts()
    d = depois.apply(tipo, axis=1).value_counts()
    t = pd.DataFrame({"antes": a, "depois": d}).fillna(0).astype(int)
    t = t.sort_values("antes", ascending=False)
    if len(t) > maximo:  # o gráfico fica legível: o resto vira "OUTROS"
        t = pd.concat([t.iloc[:maximo], t.iloc[maximo:].sum().to_frame("OUTROS").T])
    t.loc["TOTAL"] = t.sum()
    t["diferença"] = t["depois"] - t["antes"]
    t.index.name = "tipo"
    return t


def para_planilha(tabela, situacoes):
    import sys
    from drive import connect_sheets

    txt = input("\nLink da planilha para criar a aba com tabela e gráfico (Enter para pular): ").strip()
    if not txt:
        return
    m = re.search(r"/d/([\w-]+)", txt)
    sid_planilha = m.group(1) if m else txt
    sheets = connect_sheets()
    titulo = f"Antes x depois {datetime.now():%Y-%m-%d %Hh%M}"  # aba nova a cada rodada: nada é apagado
    resp = sheets.spreadsheets().batchUpdate(spreadsheetId=sid_planilha, body={"requests": [
        {"addSheet": {"properties": {"title": titulo}}}]}).execute()
    aba = resp["replies"][0]["addSheet"]["properties"]["sheetId"]

    corpo = tabela.drop(index="TOTAL").reset_index()
    def linha(vals, negrito=False):
        return {"values": [{"userEnteredValue": ({"numberValue": float(v)} if isinstance(v, (int, float)) and not isinstance(v, bool)
                                                 else {"stringValue": str(v)}),
                            "userEnteredFormat": {"textFormat": {"bold": negrito}}} for v in vals]}
    linhas = [linha(["Tipo", "Antes", "Depois", "Diferença"], True)]
    linhas += [linha([r.tipo, int(r.antes), int(r.depois), int(r.diferença)]) for r in corpo.itertuples()]
    tot = tabela.loc["TOTAL"]
    linhas.append(linha(["TOTAL", int(tot["antes"]), int(tot["depois"]), int(tot["diferença"])], True))
    linhas.append(linha([""]))
    linhas.append(linha(["Situação", "Arquivos"], True))
    linhas += [linha([s, int(n)]) for s, n in situacoes.items()]

    n = len(corpo)
    def faixa(c0, c1):
        return {"sourceRange": {"sources": [{"sheetId": aba, "startRowIndex": 0, "endRowIndex": n + 1,
                                             "startColumnIndex": c0, "endColumnIndex": c1}]}}
    grafico = {"addChart": {"chart": {
        "spec": {"title": "Arquivos por tipo — antes e depois",
                 "basicChart": {"chartType": "COLUMN", "legendPosition": "BOTTOM_LEGEND", "headerCount": 1,
                                "axis": [{"position": "BOTTOM_AXIS", "title": "Tipo de arquivo"},
                                         {"position": "LEFT_AXIS", "title": "Quantidade"}],
                                "domains": [{"domain": faixa(0, 1)}],
                                "series": [{"series": faixa(1, 2), "targetAxis": "LEFT_AXIS"},
                                           {"series": faixa(2, 3), "targetAxis": "LEFT_AXIS"}]}},
        "position": {"overlayPosition": {"anchorCell": {"sheetId": aba, "rowIndex": 0, "columnIndex": 5}}}}}}
    sheets.spreadsheets().batchUpdate(spreadsheetId=sid_planilha, body={"requests": [
        {"updateCells": {"rows": linhas, "fields": "*", "start": {"sheetId": aba, "rowIndex": 0, "columnIndex": 0}}},
        grafico]}).execute()
    print(f"aba criada: '{titulo}'  ->  https://docs.google.com/spreadsheets/d/{sid_planilha}")
    print("No Google Apresentações: Inserir > Gráfico > Do Planilhas > escolha essa planilha (fica vinculado).")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--antes", required=True, help="retrato antigo (CSV ou parquet)")
    p.add_argument("--depois", required=True, help="retrato de hoje, ex: out/arvore.csv")
    args = p.parse_args()

    depois = carrega(args.depois)
    antes = no_escopo(carrega(args.antes), depois)
    j = compara(antes, depois)
    situacoes = j["situacao"].value_counts().reindex(["igual", "movido", "renomeado", "saiu", "novo"], fill_value=0)
    tabela = por_tipo(antes, depois)

    print("\nPOR TIPO\n" + tabela.to_string())
    print("\nSITUAÇÃO DE CADA ARQUIVO\n" + situacoes.to_string())

    carimbo = f"{datetime.now():%Y%m%d_%H%M%S}"
    (RAIZ / "out").mkdir(exist_ok=True)
    tabela.to_csv(RAIZ / "out" / f"comparacao_tipos_{carimbo}.csv", encoding="utf-8-sig")
    j[["id", "situacao", "nome_a", "nome_d", "caminho_a", "caminho_d"]].rename(columns={
        "nome_a": "nome_antes", "nome_d": "nome_depois", "caminho_a": "caminho_antes", "caminho_d": "caminho_depois"
    }).to_csv(RAIZ / "out" / f"comparacao_arquivos_{carimbo}.csv", index=False, encoding="utf-8-sig")
    print(f"\nsalvo em out\\comparacao_tipos_{carimbo}.csv e out\\comparacao_arquivos_{carimbo}.csv")

    para_planilha(tabela, situacoes)
