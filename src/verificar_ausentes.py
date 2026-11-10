"""Confere cada "Ausente" do índice contra o retrato antigo: a ausência já existia antes do trabalho?

Para cada edificação e cada categoria marcada como Ausente hoje, procura a MESMA edificação no retrato
antigo (não pelo ID: a pasta da edificação pode ter sido recriada durante o trabalho). Uma pasta antiga
é considerada a mesma edificação se tiver pelo menos um destes sinais:
  - mesmo código numérico no início do nome (ex.: "01-1" = "1.1"; "07" = "7") ou mesmo nome
  - nome muito parecido, ou metade das palavras em comum (o nome pode ter mudado em parte)
  - mesma SIGLA (identificador em maiúsculas, ex.: "SED") no nome dela, da mãe ou dos itens dentro
  - sigla de hoje = iniciais do nome antigo por extenso (ex.: CCS = Centro de Ciências da Saúde), ou o contrário
  - abreviatura (ex.: "REIT SED" = "Reitoria Sede"), nos dois sentidos
O primeiro nível (ex.: o campus) também precisa bater, quando existir. A coluna "como_pareou" diz qual
sinal foi usado em cada caso, para você conferir. Depois olha as pastas que estavam dentro delas:
  CONFIRMADO   no retrato antigo também não havia pasta com esse código: a ausência é anterior
  ALERTA       havia uma pasta com esse código antes: mostra quantos arquivos tinha e onde ela está hoje
  VERIFICAR    não havia pasta com o código, mas havia pastas sem código (ex.: "Fotos"): olhar à mão
  SEM RETRATO  nenhuma pasta antiga com algum desses sinais
Só leitura: não altera nada no Drive.

USO:
  python src/verificar_ausentes.py --antes <retrato_antigo.parquet|.csv|.xlsx> --indice out/indice.csv
"""
import argparse
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from googleapiclient.errors import HttpError

from drive import RAIZ, connect
from ops import get

CODIGOS = ["01", "02", "03", "04", "05", "06", "07", "99"]
COD = re.compile(r"^\s*\[(\d+)\]")
PASTA = "application/vnd.google-apps.folder"
NOMES = {
    "id": ["id", "file_id", "fileid"],
    "nome": ["nome", "name", "title"],
    "parent": ["parent_id", "parent", "parents", "pai"],
    "mime": ["mimetype", "mime_type", "mime"],
}


def sem_acento(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(t)) if unicodedata.category(c) != "Mn")


def normaliza(t):
    return re.sub(r"\s+", " ", sem_acento(t).lower()).strip()


def chave(nome):
    # "01-1 Reitoria Sede", "1-1 ...", "01.1 ...", "1.1 ..." -> "1-1"; "07 Biblioteca" -> "7".
    # Zero à esquerda e separador não importam. Sem número no início, a chave é o nome normalizado.
    m = re.match(r"\s*(\d+(?:\s*[-.]\s*\d+)*)(?!\d)", str(nome))
    if not m:
        return normaliza(nome)
    return "-".join(str(int(n)) for n in re.split(r"\s*[-.]\s*", m.group(1)))


STOP = {"LEV", "QA", "QI", "REL", "DWG", "DXF", "PDF", "XLSX", "XLS", "DOC", "DOCX", "RVT", "IFC", "JPG",
        "JPEG", "PNG", "TIF", "ARQ", "REV", "CAD", "BIM", "UFPE", "CSV", "TXT", "ZIP", "RAR", "NA", "OK"}
SIGLA = re.compile(r"(?<![A-Za-z])[A-Z]{2,8}(?![A-Za-z])")


def siglas(nome, ignorar):
    return {t for t in SIGLA.findall(sem_acento(nome)) if t not in ignorar}


VAZIAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "na", "no"}


def palavras(nome):
    return [w for w in re.findall(r"[a-z]+", normaliza(nome)) if w not in VAZIAS and len(w) >= 2]


def iniciais(nome):
    ws = palavras(nome)
    return "".join(w[0] for w in ws).upper() if len(ws) >= 2 else ""


def parte_do_nome(a, b):
    # Mais da metade das palavras em comum (contando as dos dois nomes juntos).
    pa, pb = set(palavras(a)), set(palavras(b))
    if not pa or not pb:
        return False
    return len(pa & pb) / len(pa | pb) > 0.5


def abreviatura(tokens, nome):
    # Cada sigla de 3+ letras é o começo de uma palavra do outro nome (ex.: REIT SED -> Reitoria Sede).
    toks = [t for t in tokens if len(t) >= 3]
    ws = palavras(nome)
    casadas = [t for t in toks if any(w.startswith(t.lower()) and len(w) > len(t) for w in ws)]
    return bool(toks) and len(casadas) == len(toks) and (len(casadas) >= 2 or len(casadas[0]) >= 4)


def parecido(a, b):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, normaliza(a), normaliza(b)).ratio() >= 0.85


def codigo(nome):
    m = COD.match(str(nome))
    return m.group(1) if m else None


def le_tabela(arquivo):
    path = Path(arquivo) if Path(arquivo).is_absolute() else RAIZ / arquivo
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    elif path.suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [str(c).lstrip("﻿") for c in df.columns]
    return df.fillna("").astype(str), path.name


def carrega_antes(arquivo):
    df, nome_arq = le_tabela(arquivo)
    baixo = {c.lower(): c for c in df.columns}
    cols = {k: next((baixo[o] for o in ops if o in baixo), None) for k, ops in NOMES.items()}
    if not (cols["id"] and cols["nome"] and cols["parent"]):
        raise SystemExit(f"{nome_arq}: preciso das colunas de ID, nome e pasta-mãe. Colunas: {list(df.columns)}")
    antes = pd.DataFrame({
        "id": df[cols["id"]],
        "nome": df[cols["nome"]],
        "parent": df[cols["parent"]].str.strip("[]'\" "),  # aceita "['abc']" de listas salvas como texto
        "mime": df[cols["mime"]] if cols["mime"] else "",
    }).drop_duplicates("id")
    pais = set(antes["parent"])
    antes["pasta"] = (antes["mime"] == PASTA) | antes["id"].isin(pais)
    print(f"{nome_arq}: {len(antes)} itens no retrato antigo  (colunas: {cols})")
    return antes


def onde_esta(drive, fid, cache):
    # Caminho atual de um item no Drive (ou se foi para a lixeira / não existe mais).
    if fid in cache:
        return cache[fid]
    try:
        f = get(drive, fid, "name, parents, trashed")
        if f.get("trashed"):
            cache[fid] = "NA LIXEIRA"
            return cache[fid]
        nomes, p = [f["name"]], (f.get("parents") or [None])[0]
        for _ in range(8):
            if not p:
                break
            g = get(drive, p, "name, parents")
            nomes.insert(0, g["name"])
            p = (g.get("parents") or [None])[0]
        cache[fid] = "/".join(nomes)
    except HttpError as e:
        cache[fid] = "NÃO ENCONTRADO (excluído ou sem acesso)" if e.resp.status == 404 else f"ERRO {e.resp.status}"
    return cache[fid]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--antes", required=True, help="retrato antigo (parquet, CSV ou XLSX) com ID, nome e pasta-mãe")
    p.add_argument("--indice", default="out/indice.csv", help="CSV do indice.py (padrão: out/indice.csv)")
    p.add_argument("--depois", help="opcional: CSV do arvore.py de hoje, para ler as siglas nos nomes dos arquivos")
    p.add_argument("--ignorar", default="", help='siglas a ignorar, separadas por vírgula (ex.: "CJA,CCS")')
    args = p.parse_args()

    idx, _ = le_tabela(args.indice)
    antes = carrega_antes(args.antes)
    por_id = antes.set_index("id")
    filhos = defaultdict(list)
    for r in antes.itertuples():
        filhos[r.parent].append(r.id)

    def ancestrais(fid):
        nomes, p = [], por_id.at[fid, "parent"]
        for _ in range(20):
            if p not in por_id.index:
                break
            nomes.append(normaliza(por_id.at[p, "nome"]))
            p = por_id.at[p, "parent"]
        return nomes

    def ids_acima(fid):
        ids, p = set(), por_id.at[fid, "parent"]
        for _ in range(20):
            if p not in por_id.index:
                break
            ids.add(p)
            p = por_id.at[p, "parent"]
        return ids

    def caminho_antigo(fid):
        return "/".join(reversed([por_id.at[fid, "nome"]] + [n for n in ancestrais_raw(fid)]))

    def ancestrais_raw(fid):
        nomes, p = [], por_id.at[fid, "parent"]
        for _ in range(20):
            if p not in por_id.index:
                break
            nomes.append(por_id.at[p, "nome"])
            p = por_id.at[p, "parent"]
        return nomes

    ignorar = STOP | {t.strip().upper() for t in args.ignorar.split(",") if t.strip()}

    def siglas_da_pasta(fid, nome_de, pai_de, filhos_de):
        # Siglas no nome da pasta e da mãe; nos itens de dentro (2 níveis), só as que se repetem.
        proprias = siglas(nome_de(fid), ignorar) | siglas(nome_de(pai_de(fid)) if pai_de(fid) else "", ignorar)
        contagem = defaultdict(int)
        for k in filhos_de(fid):
            for t in siglas(nome_de(k), ignorar):
                contagem[t] += 1
            for n in filhos_de(k):
                for t in siglas(nome_de(n), ignorar):
                    contagem[t] += 1
        return proprias | {t for t, n in contagem.items() if n >= 2}

    nome_a = lambda x: por_id.at[x, "nome"] if x in por_id.index else ""
    pai_a = lambda x: por_id.at[x, "parent"] if por_id.at[x, "parent"] in por_id.index else None
    filhos_a = lambda x: filhos.get(x, [])
    pastas_antigas = [r.id for r in antes[antes["pasta"]].itertuples() if codigo(r.nome) is None]

    # Índices das pastas antigas, para não comparar cada edificação com todas as pastas.
    por_chave, por_sigla, por_palavra, por_inicial, por_prefixo, sigla_prefixo = (defaultdict(set) for _ in range(6))
    toks_antigos, toks_proprios = {}, {}
    for x in pastas_antigas:
        n = nome_a(x)
        por_chave[chave(n)].add(x)
        toks_antigos[x] = siglas_da_pasta(x, nome_a, pai_a, filhos_a)
        toks_proprios[x] = siglas(n, ignorar)
        for t in toks_antigos[x]:
            por_sigla[t].add(x)
            sigla_prefixo[t[:3]].add(x)
        for w in palavras(n):
            por_palavra[w].add(x)
            por_prefixo[w[:3]].add(x)
        if iniciais(n):
            por_inicial[iniciais(n)].add(x)

    # Lado de hoje (opcional): siglas nos nomes dos itens dentro de cada edificação.
    if args.depois:
        dep, _ = le_tabela(args.depois)
        col_nome = "nome" if "nome" in dep else "name"
        dep_nome = dict(zip(dep["id"], dep[col_nome]))
        dep_filhos = defaultdict(list)
        for i, pai in zip(dep["id"], dep["parent"]):
            dep_filhos[pai].append(i)
    else:
        dep_nome, dep_filhos = {}, defaultdict(list)

    def pareia(edif, bid, topo):
        # Devolve {pasta_antiga: [motivos]} para a edificação de hoje.
        meus = siglas(edif, ignorar)
        if bid in dep_filhos:
            meus |= siglas_da_pasta(bid, lambda i: dep_nome.get(i, ""), lambda i: None, lambda i: dep_filhos.get(i, []))
        if topo:
            meus -= siglas(topo, set())  # a sigla do campus não identifica a edificação
        minhas_palavras, minhas_iniciais = palavras(edif), iniciais(edif)

        candidatas = set(por_chave.get(chave(edif), set()))
        for w in minhas_palavras:
            candidatas |= por_palavra.get(w, set()) | sigla_prefixo.get(w[:3].upper(), set())
        for t in meus:
            candidatas |= (por_sigla.get(t, set()) | por_inicial.get(t, set())
                           | por_prefixo.get(t[:3].lower(), set()))
        if minhas_iniciais:
            candidatas |= por_sigla.get(minhas_iniciais, set())

        motivos = defaultdict(list)
        for x in candidatas:
            n = nome_a(x)
            if chave(n) == chave(edif):
                motivos[x].append(f"código {chave(edif)}" if re.match(r"\d", chave(edif)) else "mesmo nome")
            elif parecido(n, edif):
                motivos[x].append("nome parecido")
            elif parte_do_nome(n, edif):
                motivos[x].append("parte do nome")
            for t in meus & toks_antigos[x]:
                motivos[x].append(f"sigla {t}")
            for t in meus:
                if t == iniciais(n):
                    motivos[x].append(f"sigla {t} = iniciais de '{n}'")
            if minhas_iniciais and minhas_iniciais in toks_proprios[x]:
                motivos[x].append(f"iniciais de hoje = sigla antiga {minhas_iniciais}")
            if abreviatura(meus, n):
                motivos[x].append("abreviatura de hoje do nome antigo")
            elif abreviatura(toks_proprios[x], edif):
                motivos[x].append("abreviatura antiga do nome de hoje")
        return {x: m for x, m in motivos.items() if m}

    def conta_arquivos(fid):
        total, fila = 0, list(filhos.get(fid, []))
        while fila:
            x = fila.pop()
            if por_id.at[x, "pasta"]:
                fila += filhos.get(x, [])
            else:
                total += 1
        return total

    cols_cod = defaultdict(list)
    for c in idx.columns:
        if codigo(c):
            cols_cod[codigo(c)].append(c)
    cols_nivel = sorted([c for c in idx.columns if re.fullmatch(r"nivel_\d+", c)], key=lambda c: int(c[6:]))

    drive, cache, saida = connect(), {}, []
    for row in idx.to_dict("records"):
        ausentes = [c for c in CODIGOS if not any(row[col] for col in cols_cod.get(c, []))]
        if not ausentes:
            continue
        base = {**{c: row[c] for c in cols_nivel}, "edificacao": row["edificacao"]}
        bid = row["edificacao_url"].rstrip("/").rsplit("/", 1)[-1]
        topo = row[cols_nivel[0]] if cols_nivel else ""
        motivos = pareia(row["edificacao"], bid, topo)
        cands = list(motivos)
        if topo and cands:  # mesmo sinal em outro campus não conta
            cands = [x for x in cands if normaliza(topo) in ancestrais(x)] or cands
        # Uma pasta-mãe de outra candidata (ex.: "01 Reitoria" acima de "REIT SED") não é a edificação.
        cands = [x for x in cands if not any(x in ids_acima(y) for y in cands if y != x)]
        if len(cands) > 3:  # muitos candidatos: fica com os que têm mais sinais
            melhor = max(len(set(motivos[x])) for x in cands)
            cands = [x for x in cands if len(set(motivos[x])) == melhor]
        if not cands:
            saida += [{**base, "categoria": f"[{c}]", "veredito": "SEM RETRATO",
                       "detalhe": "nenhuma pasta antiga com código, nome, sigla ou abreviatura em comum"} for c in ausentes]
            continue
        base["edificacao_antes"] = " | ".join(caminho_antigo(x) for x in cands)
        base["como_pareou"] = " | ".join(", ".join(sorted(set(motivos[x]))) for x in cands)
        sub = [x for b in cands for x in filhos.get(b, []) if por_id.at[x, "pasta"]]
        for c in ausentes:
            antigas = [x for x in sub if codigo(por_id.at[x, "nome"]) == c]
            sem_cod = [por_id.at[x, "nome"] for x in sub if codigo(por_id.at[x, "nome"]) is None]
            if antigas:
                for x in antigas:
                    saida.append({**base, "categoria": f"[{c}]", "veredito": "ALERTA",
                                  "detalhe": f"existia antes: '{por_id.at[x, 'nome']}'",
                                  "arquivos_antes": conta_arquivos(x), "onde_esta_agora": onde_esta(drive, x, cache),
                                  "pasta_antes_url": f"https://drive.google.com/drive/folders/{x}"})
            elif sem_cod:
                saida.append({**base, "categoria": f"[{c}]", "veredito": "VERIFICAR",
                              "detalhe": "pastas sem código antes: " + "; ".join(sem_cod)})
            else:
                saida.append({**base, "categoria": f"[{c}]", "veredito": "CONFIRMADO",
                              "detalhe": "já ausente no retrato antigo"})

    res = pd.DataFrame(saida)
    if res.empty:
        raise SystemExit("Nenhum Ausente no índice. Nada a conferir.")
    if "arquivos_antes" in res:
        res["arquivos_antes"] = res["arquivos_antes"].astype("Int64")
    out = RAIZ / "out" / f"verificacao_ausentes_{datetime.now():%Y%m%d_%H%M%S}.csv"
    out.parent.mkdir(exist_ok=True)
    res.to_csv(out, index=False, encoding="utf-8-sig")

    print("\nRESULTADO\n" + res["veredito"].value_counts().to_string())
    alertas = res[res["veredito"] == "ALERTA"]
    if not alertas.empty:
        print("\nALERTAS (pasta existia antes):")
        print(alertas[["edificacao", "categoria", "detalhe", "arquivos_antes", "onde_esta_agora"]]
              .to_string(index=False, max_rows=40))
    print(f"\nsalvo em {out}")
