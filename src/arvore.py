"""Árvore completa de uma pasta (pastas + arquivos) com links: HTML recolhível + CSV, em out/.

Só leitura. Para pastas muito grandes, prefira rodar por edificação (ou limitar com --max-depth).

USO:
  python src/arvore.py --root <ID_PASTA>
  python src/arvore.py --root <ID_PASTA> --max-depth 3 --out out/arvore_reitoria
"""
import argparse
import html
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

from drive import connect, RAIZ

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
FIELDS = "id, name, mimeType, parents, webViewLink, size, modifiedTime, md5Checksum, shortcutDetails(targetId, targetMimeType)"
GAPPS = {
    "application/vnd.google-apps.document": "GDOC",
    "application/vnd.google-apps.spreadsheet": "GSHEET",
    "application/vnd.google-apps.presentation": "GSLIDES",
    "application/vnd.google-apps.form": "GFORM",
    "application/vnd.google-apps.drawing": "GDRAW",
    "application/vnd.google-apps.site": "GSITE",
    "application/vnd.google-apps.map": "GMAP",
    "application/vnd.google-apps.jam": "GJAM",
    "application/vnd.google-apps.script": "GSCRIPT",
    "application/vnd.google-apps.vid": "GVIDS",
    SHORTCUT: "ATALHO",
}
CORES = {  # rótulo -> classe de cor
    "PDF": "red", "DWG": "cad", "DXF": "cad", "RVT": "cad", "IFC": "cad", "SKP": "cad",
    "XLS": "green", "XLSX": "green", "CSV": "green", "GSHEET": "green",
    "DOC": "blue", "DOCX": "blue", "GDOC": "blue", "TXT": "blue",
    "JPG": "amber", "JPEG": "amber", "PNG": "amber", "TIF": "amber", "TIFF": "amber",
    "PPT": "orange", "PPTX": "orange", "GSLIDES": "orange", "ATALHO": "gray",
}


def list_children(drive, parent_ids):
    # Filhos (pastas e arquivos) de até 30 pastas numa só consulta, com paginação.
    q = "(" + " or ".join(f"'{p}' in parents" for p in parent_ids) + ") and trashed=false"
    files, token = [], None
    while True:
        resp = drive.files().list(
            q=q,
            fields=f"nextPageToken, files({FIELDS})",
            pageSize=1000,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            return files


def walk(drive, root_id, max_depth=None):
    # Desce nível por nível; atalhos são registrados, mas nunca seguidos.
    root = drive.files().get(fileId=root_id, fields=FIELDS, supportsAllDrives=True).execute()
    if root["mimeType"] == SHORTCUT:
        root_id = root["shortcutDetails"]["targetId"]
        root = drive.files().get(fileId=root_id, fields=FIELDS, supportsAllDrives=True).execute()
    root.update(parent=None, depth=0, path=root["name"])
    info = {root_id: root}
    atual, depth = [root_id], 0
    while atual and (max_depth is None or depth < max_depth):
        depth += 1
        proximo = []
        for i in range(0, len(atual), 30):
            for f in list_children(drive, atual[i:i + 30]):
                pai = next((p for p in f.get("parents", []) if p in info), None)
                if pai is None:
                    continue
                f.update(parent=pai, depth=depth, path=f"{info[pai]['path']}/{f['name']}")
                info[f["id"]] = f
                if f["mimeType"] == FOLDER:
                    proximo.append(f["id"])
        atual = proximo
        print(f"  nível {depth}: {len(info) - 1} itens, {len(proximo)} pastas a descer")
    return root_id, info


BRASILIA = timezone(timedelta(hours=-3), "Brasília")  # sem horário de verão desde 2019


def rotulo(f):
    # Extensão do arquivo; nativos do Google: GDOC, GSHEET...; sem extensão: nada.
    m = f["mimeType"]
    if m in GAPPS:
        return GAPPS[m]
    if m.startswith("application/vnd.google-apps."):
        return "G" + m.rsplit(".", 1)[-1].upper()[:5]
    nome = f["name"]
    return nome.rsplit(".", 1)[-1].upper()[:6] if "." in nome else ""


def tamanho(n):
    if not n:
        return ""
    n = float(n)
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def data(iso):
    # Só a data (no fuso de Brasília, para o dia não mudar perto da meia-noite).
    if not iso:
        return ""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BRASILIA)
    return dt.strftime("%d/%m/%Y")


ICON_PASTA = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16'
              'a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"/></svg>')


def render(node_id, info, filhos, contagem, aberto=False):
    f = info[node_id]
    nome = html.escape(f["name"])
    link = html.escape(f.get("webViewLink", ""))
    if f["mimeType"] != FOLDER:
        lab = rotulo(f)
        meta = " · ".join(x for x in [tamanho(f.get("size")), data(f.get("modifiedTime"))] if x)
        selo = f'<span class="ext {CORES.get(lab, "gray")}">{lab}</span>' if lab else '<span class="ext vazio"></span>'
        return (f'<li><div class="row"><a class="node" href="{link}" target="_blank" rel="noopener">'
                f'{selo}<span class="nm">{nome}</span></a>'
                f'<span class="meta">{meta}</span></div></li>')
    kids = sorted(filhos.get(node_id, []),
                  key=lambda k: (info[k]["mimeType"] != FOLDER, info[k]["name"].lower()))
    inner = "".join(render(k, info, filhos, contagem) for k in kids)
    n = contagem[node_id]
    meta = f"{n} arquivo{'s' if n != 1 else ''}"
    return (f'<li><details{" open" if aberto else ""}><summary>'
            f'<a class="node" href="{link}" target="_blank" rel="noopener">{ICON_PASTA}'
            f'<span class="nm{" hl" if "[01]" in f["name"] else ""}">{nome}</span></a>'
            f'<span class="meta">{meta}</span></summary><ul>{inner}</ul></details></li>')


def to_html(root_id, info):
    filhos = {}
    for fid, f in info.items():
        if f["parent"]:
            filhos.setdefault(f["parent"], []).append(fid)
    contagem = {}

    def conta(fid):
        if info[fid]["mimeType"] != FOLDER:
            return 1
        contagem[fid] = sum(conta(k) for k in filhos.get(fid, []))
        return contagem[fid]

    total = conta(root_id)
    pastas = sum(1 for f in info.values() if f["mimeType"] == FOLDER)
    gerado = datetime.now(BRASILIA).strftime("%d/%m/%Y")
    arvore = render(root_id, info, filhos, contagem, aberto=True)
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Árvore de pastas</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#faf9f7; --fg:#1f1f1f; --muted:#8a8580; --line:#e6e2dc; --hover:#f0ede8; --icon:#5f6368;
  --red:#b3261e; --cad:#7a4b8c; --green:#1e7e45; --blue:#1a5fb4; --amber:#a86400; --orange:#c24e00; --gray:#6f6a64; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1b1b1a; --fg:#ece9e4; --muted:#8f8a84; --line:#33312e; --hover:#262523; --icon:#b5b1aa;
  --red:#f2867e; --cad:#c79ad8; --green:#6fcf97; --blue:#8ab4f8; --amber:#f2b55c; --orange:#f5a06a; --gray:#a8a39c; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg); font:15px/1.5 "Lora", Georgia, "Times New Roman", serif; }}
header {{ display:flex; flex-wrap:wrap; gap:12px; align-items:baseline; justify-content:space-between; margin-bottom:16px; }}
h1 {{ font-size:18px; font-weight:600; margin:0; }}
.sub {{ color:var(--muted); font-size:12px; }}
.tools {{ display:flex; gap:8px; flex-wrap:wrap; }}
input, button {{ padding:7px 12px; border:1px solid var(--line); border-radius:8px; background:transparent; color:var(--fg); font:inherit; }}
input {{ width:min(300px,100%); }}
button {{ cursor:pointer; }} button:hover {{ background:var(--hover); }}
ul {{ list-style:none; margin:0; padding-left:20px; border-left:1px solid var(--line); }}
#tree > ul {{ padding-left:0; border-left:none; }}
summary {{ cursor:pointer; list-style:none; }}
summary::-webkit-details-marker {{ display:none; }}
summary, .row {{ display:flex; align-items:center; gap:10px; padding:3px 6px; border-radius:6px; }}
summary:hover, .row:hover {{ background:var(--hover); }}
summary::before {{ content:"▸"; color:var(--muted); width:10px; flex:none; transition:transform .12s; }}
details[open] > summary::before {{ transform:rotate(90deg); }}
.row {{ padding-left:22px; }}
.node {{ display:inline-flex; align-items:center; gap:7px; color:var(--fg); text-decoration:none; min-width:0; }}
.node:hover .nm {{ text-decoration:underline; }}
.nm {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.nm.hl {{ background:#ADFFCC; color:#1f1f1f; padding:0 4px; }}
.node svg {{ width:16px; height:16px; fill:var(--icon); flex:none; }}
.ext {{ font-size:10px; font-weight:600; letter-spacing:.02em; padding:1px 5px; border-radius:4px; border:1px solid currentColor; flex:none; min-width:38px; text-align:center; }}
.ext.vazio {{ border-color:transparent; }}
.red {{ color:var(--red); }} .cad {{ color:var(--cad); }} .green {{ color:var(--green); }} .blue {{ color:var(--blue); }}
.amber {{ color:var(--amber); }} .orange {{ color:var(--orange); }} .gray {{ color:var(--gray); }}
.meta {{ color:var(--muted); font-size:12px; margin-left:auto; white-space:nowrap; padding-left:12px; }}
</style></head><body>
<header>
  <div><h1>{html.escape(info[root_id]["name"])}</h1>
  <div class="sub">{total} arquivos · {pastas - 1} subpastas · gerado em {gerado}</div></div>
  <div class="tools">
    <input id="f" type="search" placeholder="Filtrar por nome…" autocomplete="off">
    <button id="abrir">Expandir tudo</button><button id="fechar">Recolher</button>
  </div>
</header>
<div id="tree"><ul>{arvore}</ul></div>
<script>
const tree = document.getElementById("tree");
const items = [...tree.querySelectorAll("li")];
const own = li => li.querySelector(":scope > .row, :scope > details > summary");
document.getElementById("abrir").onclick = () => tree.querySelectorAll("details").forEach(d => d.open = true);
document.getElementById("fechar").onclick = () => tree.querySelectorAll("details").forEach((d, i) => d.open = i === 0);
let t;
document.getElementById("f").addEventListener("input", e => {{
  clearTimeout(t);
  t = setTimeout(() => {{
    const q = e.target.value.trim().toLowerCase();
    if (!q) {{ items.forEach(li => li.hidden = false); return; }}
    items.forEach(li => li.hidden = true);
    for (const li of items) {{
      if (!own(li).textContent.toLowerCase().includes(q)) continue;
      for (let el = li; el && el !== tree; el = el.parentElement) {{
        if (el.tagName === "LI") el.hidden = false;
        if (el.tagName === "DETAILS" && el !== li.firstElementChild) el.open = true;
      }}
    }}
  }}, 200);
}});
</script>
</body></html>"""


def to_csv(info, path):
    rows = [{
        "path": f["path"], "nome": f["name"], "tipo": "pasta" if f["mimeType"] == FOLDER else rotulo(f),
        "url": f.get("webViewLink", ""), "tamanho_bytes": f.get("size", ""), "modificado": f.get("modifiedTime", ""),
        "md5": f.get("md5Checksum", ""), "id": fid, "parent": f["parent"] or "", "mimeType": f["mimeType"],
        "atalho_para": (f.get("shortcutDetails") or {}).get("targetId", ""),
    } for fid, f in info.items()]
    pd.DataFrame(rows).sort_values("path").to_csv(path, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, help="ID da pasta raiz (aceita ID de atalho)")
    p.add_argument("--max-depth", type=int, default=None, help="profundidade máxima (padrão: tudo)")
    p.add_argument("--out", default="out/arvore", help="caminho de saída sem extensão (padrão: out/arvore)")
    args = p.parse_args()

    drive = connect()
    root_id, info = walk(drive, args.root, args.max_depth)

    base = RAIZ / args.out
    base.parent.mkdir(parents=True, exist_ok=True)
    html_path, csv_path = base.with_suffix(".html"), base.with_suffix(".csv")
    html_path.write_text(to_html(root_id, info), encoding="utf-8")
    to_csv(info, csv_path)
    print(f"{len(info) - 1} itens")
    print(f"  {html_path}\n  {csv_path}")
    if hasattr(os, "startfile"):
        os.startfile(str(html_path))