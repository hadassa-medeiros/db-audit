"""Índice de pastas por edificação: HTML clicável (com ícones) + CSV, em out/.

Só lê pastas (não arquivos) e só desce até o nível das categorias, por isso é rápido.

USO:
  python src/indice.py --root <ID_PASTA_RAIZ> --nivel 2
  --nivel = posição da pasta da edificação no caminho, contando a raiz como 0
            ex.: raiz/01 Reitoria/01-1 Reitoria Sede  ->  --nivel 2
"""
import argparse
import html
import os
from datetime import datetime

import pandas as pd

from drive import connect, RAIZ

FOLDER = "application/vnd.google-apps.folder"
URL = "https://drive.google.com/drive/folders/{}"


def list_folders(drive, parent_ids):
    # Subpastas de até 30 pastas numa só consulta (com paginação).
    q = ("(" + " or ".join(f"'{p}' in parents" for p in parent_ids) + ")"
         f" and mimeType='{FOLDER}' and trashed=false")
    files, token = [], None
    while True:
        resp = drive.files().list(
            q=q,
            fields="nextPageToken, files(id, name, parents)",
            pageSize=1000,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            return files


def walk_folders(drive, root_id, nivel):
    # Desce nível por nível até as categorias (nivel + 1); cada pasta herda a edificação do pai.
    root = drive.files().get(fileId=root_id, fields="name", supportsAllDrives=True).execute()
    info = {root_id: {"id": root_id, "name": root["name"], "depth": 0,
                      "parent": None, "edif": root_id if nivel == 0 else None}}
    atual = [root_id]
    for depth in range(1, nivel + 2):
        proximo = []
        for i in range(0, len(atual), 30):
            for f in list_folders(drive, atual[i:i + 30]):
                pai = info[f["parents"][0]]
                info[f["id"]] = {"id": f["id"], "name": f["name"], "depth": depth, "parent": pai["id"],
                                 "edif": f["id"] if depth == nivel else pai["edif"]}
                proximo.append(f["id"])
        atual = proximo
        print(f"  nível {depth}: {len(proximo)} pastas")
    return pd.DataFrame(info.values()), info


def ancestrais(info, fid):
    # IDs das pastas entre a raiz e a edificação (sem a raiz), de cima para baixo.
    cadeia, p = [], info[fid]["parent"]
    while p and info[p]["depth"] > 0:
        cadeia.insert(0, p)
        p = info[p]["parent"]
    return cadeia


def build_index(df, info, nivel):
    edif = df[df["depth"] == nivel].copy()
    edif["grupo"] = edif["parent"].map(lambda p: info[p]["name"] if p else "")
    cats = df[df["depth"] == nivel + 1]
    piv = cats.pivot_table(index="edif", columns="name", values="id", aggfunc="first")
    idx = edif.set_index("id")[["grupo", "name"]].join(piv)
    categorias = sorted(piv.columns)
    # Um nível da hierarquia por coluna (nivel_1 ... nivel_{N-1}); a edificação é o último nível.
    for i in range(1, nivel):
        idx[f"nivel_{i}_id"] = [ancestrais(info, e)[i - 1] for e in idx.index]
        idx[f"nivel_{i}"] = idx[f"nivel_{i}_id"].map(lambda x: info[x]["name"])
    idx = idx.sort_values([f"nivel_{i}" for i in range(1, nivel)] + ["grupo", "name"])
    return idx, categorias


ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16'
        'a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"/></svg>')


def chip(folder_id, label, title=None):
    t = html.escape(title or label)
    return (f'<a class="chip" href="{URL.format(folder_id)}" target="_blank" rel="noopener" title="{t}">'
            f'{ICON}<span>{html.escape(label)}</span></a>')


def short(name):
    # "[01] Documentação Arquitetônica" -> "[01]"; sem colchetes, mantém o nome.
    return name.split("]")[0] + "]" if name.startswith("[") and "]" in name else name


def to_html(idx, categorias, root_name):
    head = "".join(f"<th>{html.escape(c)}</th>" for c in categorias)
    linhas = []
    for edif_id, r in idx.iterrows():
        cells = "".join(
            f"<td>{chip(r[c], short(c), c) if isinstance(r[c], str) else '<span class=vazio>—</span>'}</td>"
            for c in categorias)
        linhas.append(f"<tr><td class=grupo>{html.escape(r['grupo'])}</td>"
                      f"<td>{chip(edif_id, r['name'])}</td>{cells}</tr>")
    gerado = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Índice de pastas</title>
<style>
:root {{ --bg:#faf9f7; --fg:#1f1f1f; --muted:#8a8580; --line:#e6e2dc; --chip:#efece7; --chip-h:#e3ded6; --icon:#5f6368; --head:#3d5a47; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1b1b1a; --fg:#ece9e4; --muted:#8f8a84; --line:#33312e; --chip:#2a2926; --chip-h:#36342f; --icon:#b5b1aa; --head:#2f4638; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg); font:14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }}
header {{ display:flex; flex-wrap:wrap; gap:12px; align-items:baseline; justify-content:space-between; margin-bottom:16px; }}
h1 {{ font-size:18px; font-weight:600; margin:0; }}
.meta {{ color:var(--muted); font-size:12px; }}
input {{ width:min(320px,100%); padding:8px 12px; border:1px solid var(--line); border-radius:8px; background:transparent; color:var(--fg); font:inherit; }}
.wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; }}
table {{ border-collapse:collapse; width:100%; }}
th {{ position:sticky; top:0; background:var(--head); color:#fff; font-weight:500; text-align:left; padding:10px 12px; white-space:nowrap; }}
td {{ padding:6px 12px; border-top:1px solid var(--line); white-space:nowrap; }}
td.grupo {{ color:var(--muted); }}
.chip {{ display:inline-flex; align-items:center; gap:6px; padding:3px 10px 3px 7px; border-radius:999px; background:var(--chip); color:var(--fg); text-decoration:none; }}
.chip:hover {{ background:var(--chip-h); }}
.chip svg {{ width:15px; height:15px; fill:var(--icon); flex:none; }}
.vazio {{ color:var(--muted); }}
</style></head><body>
<header>
  <div><h1>{html.escape(root_name)}</h1><div class="meta">{len(idx)} edificações · {len(categorias)} categorias · gerado em {gerado}</div></div>
  <input id="f" type="search" placeholder="Filtrar edificação…" autocomplete="off">
</header>
<div class="wrap"><table>
<thead><tr><th>Grupo</th><th>Edificação</th>{head}</tr></thead>
<tbody id="t">{"".join(linhas)}</tbody>
</table></div>
<script>
document.getElementById("f").addEventListener("input", e => {{
  const q = e.target.value.toLowerCase();
  for (const tr of document.getElementById("t").rows) tr.hidden = !tr.textContent.toLowerCase().includes(q);
}});
</script>
</body></html>"""


def to_csv(idx, categorias, path, nivel):
    out = pd.DataFrame(index=idx.index)
    for i in range(1, nivel):
        out[f"nivel_{i}"] = idx[f"nivel_{i}"]
        out[f"nivel_{i}_url"] = idx[f"nivel_{i}_id"].map(URL.format)
    out["grupo"] = idx["grupo"]
    out["edificacao"] = idx["name"]
    out["edificacao_url"] = [URL.format(i) for i in idx.index]
    for c in categorias:
        out[c] = idx[c].map(lambda v: URL.format(v) if isinstance(v, str) else "")
    out.to_csv(path, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, help="ID da pasta raiz")
    p.add_argument("--nivel", type=int, required=True, help="posição da pasta da edificação no caminho (raiz = 0)")
    p.add_argument("--out", default="out/indice", help="caminho de saída sem extensão (padrão: out/indice)")
    args = p.parse_args()

    drive = connect()
    df, info = walk_folders(drive, args.root, args.nivel)
    idx, categorias = build_index(df, info, args.nivel)

    base = RAIZ / args.out
    base.parent.mkdir(parents=True, exist_ok=True)
    html_path, csv_path = base.with_suffix(".html"), base.with_suffix(".csv")
    html_path.write_text(to_html(idx, categorias, info[args.root]["name"]), encoding="utf-8")
    to_csv(idx, categorias, csv_path, args.nivel)
    print(f"{len(idx)} edificações x {len(categorias)} categorias")
    print(f"  {html_path}\n  {csv_path}")
    if hasattr(os, "startfile"):
        os.startfile(str(html_path))
