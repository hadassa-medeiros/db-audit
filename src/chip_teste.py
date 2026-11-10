import argparse
from drive import connect_sheets


def chip_cell(folder_id):
    return {
        "userEnteredValue": {"stringValue": "@"},
        "chipRuns": [{
            "startIndex": 0,
            "chip": {"richLinkProperties": {"uri": f"https://drive.google.com/drive/folders/{folder_id}"}},
        }],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sheet", required=True, help="ID da planilha")
    p.add_argument("--folder", required=True, help="ID de uma pasta para testar")
    args = p.parse_args()

    sheets = connect_sheets()
    body = {"requests": [{"updateCells": {
        "rows": [
            title_row := {"values": [{"userEnteredValue": {"stringValue": "Teste de chip"}}]},
            {"values": [chip_cell(args.folder)]
             }],
        "fields": "userEnteredValue,chipRuns",
        "start": {"sheetId": 0, "rowIndex": 1, "columnIndex": 0},
    }}]}
    sheets.spreadsheets().batchUpdate(spreadsheetId=args.sheet, body=body).execute()
    print("ok: veja a célula A1")