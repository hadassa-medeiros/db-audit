import pandas as pd
from drive import connect, RAIZ
from argparse import ArgumentParser
from pathlib import Path

FOLDER = "application/vnd.google-apps.folder"

drive = connect(write=True)

def whoami(svc):
    user = svc.about().get(fields="user(emailAddress)").execute()["user"]
    print("Autenticada como:", user["emailAddress"])

def list_children(svc, folder_id):
    response = svc.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, mimeType)",
        pageSize=100,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    for f in response.get("files", []):
        print(f"{f['name']} ({f['id']}) - {f['mimeType']}")

def list_all(svc, folder_id):
    files, token = [], None
    while True:
        resp = svc.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, md5Checksum, size, modifiedTime)",
            pageSize=1000,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            return files

def walk(svc, root_id):
    root = svc.files().get(fileId=root_id, fields="name", supportsAllDrives=True).execute()
    rows = []
    fila = [(root_id, root["name"])]
    while fila:
        folder_id, path = fila.pop(0)
        for f in list_all(svc, folder_id):
            f["parent"] = folder_id
            f["path"] = f"{path}/{f['name']}"
            rows.append(f)
            if f["mimeType"] == FOLDER:
                fila.append((f["id"], f["path"]))
        print(f"  {len(rows)} itens, {len(fila)} pastas na fila", end="\r")
    print()
    return rows

if __name__ == "__main__":
    p = ArgumentParser()
    p.add_argument("--root", required=False, help="ID do diretório raiz")
    p.add_argument("--out", required=False, help="CSV de saida, ex: out/inv_A.csv")

    args = p.parse_args()
    
    RAIZ = Path(__file__).resolve().parent.parent
    svc = drive
    df = pd.DataFrame(walk(svc, args.root))
    df.to_csv(args.out, index=False)