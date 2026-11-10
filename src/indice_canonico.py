"""Índice das pastas canônicas [0N], com o rastro de links desde a raiz.

Algoritmo:
  - parte da pasta raiz (pedida na hora; aceita ID ou link)
  - entra em cada subpasta cujo nome começa com número, e repete isso para dentro
  - dentro delas, procura pastas que começam com "[0" ([01] ... [08]); "Laudo de Avaliação..." vale
    como [04] quando a [04] de verdade não existe
  - cada pasta que tem filhas [0N] vira uma linha:
      Raiz | Nível 1 | Nível 2 | ... (rastro até a pasta-mãe) | [01] | [02] | ... | [07] (| [08])
  - código que não existe naquela pasta-mãe: "Ausente"
  - na planilha, um nível igual ao da linha de cima fica em branco (a indentação fica visível);
    o CSV guarda o rastro completo em todas as linhas
  - pergunta o número do nível da raiz na sua numeração (ex.: 2 -> as colunas viram Nível 2, 3, 4...)
Só lê o Drive. Salva um CSV em out/ e, se você der o link de uma planilha, cria nela uma ABA NOVA
com chips clicáveis (nada é apagado).

USO:
  python src/indice_canonico.py
"""
import re
import sys
from collections import Counter
from datetime import datetime

import pandas as pd
from googleapiclient.errors import HttpError

from drive import RAIZ, connect, connect_sheets

PASTA = "application/vnd.google-apps.folder"
URL = "https://drive.google.com/drive/folders/{}"
CANONICA = re.compile(r"^\s*\[(0\d)\]")
# Pastas sem o código no nome que também valem para uma coluna (comparação sem acentos/maiúsculas).
# Se a pasta-mãe tiver a [0N] de verdade, ela tem preferência.
APELIDOS = {"laudo de avaliacao": "04"}
FIXOS = ["01", "02", "03", "04", "05", "06", "07"]
TITULOS = {"01": "[01] Documentação Arquitetônica", "02": "[02] Documentação Legal", "03": "[03] Fotos",
           "04": "[04] Inventário", "05": "[05] Cessão de Área", "06": "[06] Projetos Recebidos",
           "07": "[07] Original"}
VERDE = {"red": 0.24, "green": 0.35, "blue": 0.28}
BRANCO = {"red": 1, "green": 1, "blue": 1}


def pede_id(pergunta, padrao):
    txt = input(pergunta).strip()
    m = re.search(padrao, txt)
    return m.group(1) if m else txt


def sem_acento_min(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


def apelido(nome):
    n = sem_acento_min(nome)
    return next((cod for inicio, cod in APELIDOS.items() if n.startswith(inicio)), None)


def subpastas(drive, ids):
    # Pastas filhas de até 30 pastas numa só consulta, com paginação.
    q = "(" + " or ".join(f"'{i}' in parents" for i in ids) + f") and mimeType='{PASTA}' and trashed=false"
    out, token = [], None
    while True:
        r = drive.files().list(q=q, fields="nextPageToken, files(id, name, parents)", pageSize=1000,
                               pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        out += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            return out


def varre(drive, root_id):
    root = drive.files().get(fileId=root_id, fields="name", supportsAllDrives=True).execute()
    info = {root_id: {"nome": root["name"], "pai": None}}
    maes, repetidas = {}, []
    frente, nivel = [root_id], 0
    while frente:
        nivel += 1
        prox = []
        for i in range(0, len(frente), 30):
            for f in subpastas(drive, frente[i:i + 30]):
                pai = next((p for p in f.get("parents", []) if p in info), None)
                if pai is None:
                    continue
                nome = f["name"].strip()
                m = CANONICA.match(nome)
                cod, oficial = (m.group(1), True) if m else (apelido(nome), False)
                if cod:  # pasta canônica (ou apelido): guarda o link na pasta-mãe
                    codigos = maes.setdefault(pai, {})
                    atual = codigos.get(cod)
                    if atual is None or (oficial and not atual[2]):
                        codigos[cod] = (f["id"], nome, oficial)
                    elif oficial == atual[2]:
                        repetidas.append(f"{info[pai]['nome']} / {nome}")
                elif nome[:1].isdigit():  # começa com número: entra nela
                    info[f["id"]] = {"nome": nome, "pai": pai}
                    prox.append(f["id"])
        frente = prox
        print(f"  nível {nivel}: {len(prox)} pastas numeradas | {len(maes)} pastas com canônicas até agora")
    return info, maes, repetidas


def rastro(info, fid):
    ids = []
    while fid:
        ids.insert(0, fid)
        fid = info[fid]["pai"]
    return ids  # [raiz, nível 1, ..., pasta-mãe]


def monta(info, maes):
    codigos = FIXOS + sorted({c for cs in maes.values() for c in cs} - set(FIXOS))
    linhas = []
    for mae, cs in maes.items():
        ids = rastro(info, mae)
        linhas.append({"ids": ids, "nomes": [info[i]["nome"] for i in ids], "cods": cs})
    linhas.sort(key=lambda r: [n.lower() for n in r["nomes"]])
    profundidade = max(len(r["ids"]) for r in linhas)  # raiz + níveis
    nomes_extra = Counter(n for r in linhas for c, (_, n, _o) in r["cods"].items() if c not in TITULOS)
    titulos = {c: TITULOS.get(c) or next((n for n, _ in nomes_extra.most_common() if n.startswith(f"[{c}]")), f"[{c}]")
               for c in codigos}
    return linhas, codigos, titulos, profundidade


def nome_nivel(k, base):
    if base is None:
        return "Raiz" if k == 0 else f"Nível {k}"
    return f"Nível {base + k}"


def salva_csv(linhas, codigos, titulos, prof, base):
    rows = []
    for r in linhas:
        d = {}
        for k in range(prof):
            col = nome_nivel(k, base)
            d[col] = r["nomes"][k] if k < len(r["ids"]) else ""
            d[col + " (link)"] = URL.format(r["ids"][k]) if k < len(r["ids"]) else ""
        for c in codigos:
            d[titulos[c]] = URL.format(r["cods"][c][0]) if c in r["cods"] else "Ausente"
        rows.append(d)
    path = RAIZ / "out" / f"indice_canonico_{datetime.now():%Y%m%d_%H%M%S}.csv"
    path.parent.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def texto(v, negrito=False, cabecalho=False):
    c = {"userEnteredValue": {"stringValue": v}}
    if cabecalho:
        c["userEnteredFormat"] = {"backgroundColor": VERDE, "textFormat": {"bold": True, "foregroundColor": BRANCO}}
    return c


def celula(fid, rotulo, usar_chip):
    url = URL.format(fid)
    if usar_chip:
        return {"userEnteredValue": {"stringValue": "@"},
                "chipRuns": [{"startIndex": 0, "chip": {"richLinkProperties": {"uri": url}}}]}
    return {"userEnteredValue": {"stringValue": rotulo},
            "textFormatRuns": [{"startIndex": 0, "format": {"link": {"uri": url}}}]}


def para_planilha(linhas, codigos, titulos, prof, base):
    planilha = pede_id("\nLink da planilha para criar a aba (Enter para pular): ", r"/d/([\w-]+)")
    if not planilha:
        return
    sheets = connect_sheets()
    titulo = f"Índice {datetime.now():%Y-%m-%d %Hh%M}"  # aba nova a cada rodada: nada é apagado
    resp = sheets.spreadsheets().batchUpdate(spreadsheetId=planilha, body={"requests": [
        {"addSheet": {"properties": {"title": titulo, "gridProperties": {"frozenRowCount": 1,
                                                                          "frozenColumnCount": prof}}}}]}).execute()
    aba = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    cab = [nome_nivel(k, base) for k in range(prof)] + [titulos[c] for c in codigos]
    n_cols = len(cab)

    for usar_chip in (True, False):
        corpo = [{"values": [texto(c, cabecalho=True) for c in cab]}]
        anterior = []
        for r in linhas:
            ids, vals = r["ids"], []
            for k in range(prof):
                repetido = k < len(ids) - 1 and anterior[:k + 1] == ids[:k + 1]  # a pasta-mãe sempre aparece
                vals.append(celula(ids[k], r["nomes"][k], usar_chip) if k < len(ids) and not repetido
                            else texto(""))
            anterior = ids
            vals += [celula(r["cods"][c][0], r["cods"][c][1], usar_chip) if c in r["cods"] else texto("Ausente")
                     for c in codigos]
            corpo.append({"values": vals})
        try:
            sheets.spreadsheets().batchUpdate(spreadsheetId=planilha, body={"requests": [
                {"updateCells": {"rows": corpo, "fields": "*",
                                 "start": {"sheetId": aba, "rowIndex": 0, "columnIndex": 0}}},
                {"autoResizeDimensions": {"dimensions": {"sheetId": aba, "dimension": "COLUMNS",
                                                         "startIndex": 0, "endIndex": n_cols}}}]}).execute()
            print(f"aba '{titulo}' criada" + ("" if usar_chip else " (com links comuns: o Google recusou os chips)"))
            break
        except HttpError as e:
            if not usar_chip:
                raise
            print(f"chips recusados ({e.resp.status}); tentando com links comuns...")
    print(f"https://docs.google.com/spreadsheets/d/{planilha}")


if __name__ == "__main__":
    root_id = pede_id("ID ou link da pasta raiz: ", r"/folders/([\w-]+)")
    info, maes, repetidas = varre(connect(), root_id)
    if not maes:
        sys.exit("Nenhuma pasta [0N] encontrada dentro das pastas numeradas.")
    linhas, codigos, titulos, prof = monta(info, maes)
    txt = input("Número do nível da raiz na sua planilha (Enter = Raiz, Nível 1, 2...): ").strip()
    base = int(txt) if txt.isdigit() else None
    print(f"\n{len(linhas)} linhas (pastas-mãe com canônicas) | rastro de até {prof - 1} níveis abaixo da raiz")
    if repetidas:
        print(f"atenção: {len(repetidas)} canônicas repetidas na mesma pasta (ficou a primeira):")
        for x in repetidas[:15]:
            print("   ", x)
    print(f"CSV: {salva_csv(linhas, codigos, titulos, prof, base)}")
    para_planilha(linhas, codigos, titulos, prof, base)
