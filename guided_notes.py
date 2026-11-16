"""Layout-based Guided Notes parsing. Coordinates are discovered, never fixed."""
import hashlib
import io
import json
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from quiz_service import QuizError

SINGLE_TEMPLATE = "12uh5xhIx2wXFMy42KU8lN7rLFQ8GDugt9zfAFEvu-1E"
GROUP_TEMPLATE = "1PXXwWiBKJNpPkLRoJLMzZWsAh4Jzn2bThHTeRAiq3Hg"
PROTECTED_TEMPLATES = {SINGLE_TEMPLATE, GROUP_TEMPLATE}
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def spreadsheet_id(url):
    if not isinstance(url, str):
        raise QuizError(400, "請貼上 Google Sheets 連結。")
    match = re.fullmatch(r"https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{20,100})(?:/[^\s]*)?", url.strip())
    if not match:
        raise QuizError(400, "請使用 https://docs.google.com/spreadsheets/d/ 開頭的試算表連結。")
    return match[1]


def a1(row, col):
    result = ""
    col += 1
    while col:
        col, n = divmod(col - 1, 26)
        result = chr(65 + n) + result
    return f"{result}{row + 1}"


def position(value):
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", value)
    if not match:
        raise QuizError(400, "學習單含無效儲存格位置。")
    col = 0
    for ch in match[1]:
        col = col * 26 + ord(ch) - 64
    return int(match[2]) - 1, col - 1


def number(value):
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except InvalidOperation:
        return str(value)


@dataclass
class Grid:
    title: str
    cells: dict
    merges: list
    sheet_id: int | None = None

    def span(self, row, col):
        found = [m for m in self.merges if m[0] <= row < m[2] and m[1] <= col < m[3]]
        if len(found) > 1:
            raise QuizError(400, "合併儲存格範圍重疊，無法判定答案位置。")
        return found[0] if found else (row, col, row + 1, col + 1)

    def value(self, row, col):
        span = self.span(row, col)
        return self.cells.get((span[0], span[1]), "")


def from_xlsx(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if sum(i.file_size for i in z.infolist()) > 30_000_000:
            raise QuizError(413, "學習單過大，請縮小為課堂使用的工作表。")
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = ["".join(si.itertext()) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        result = []
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).findall("s:sheets/s:sheet", NS):
            target = rels[sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            if not target.startswith("xl/worksheets/"):
                raise QuizError(400, "學習單格式不支援。")
            root = ET.fromstring(z.read(target))
            cells = {}
            for c in root.findall("s:sheetData/s:row/s:c", NS):
                raw, formula = c.find("s:v", NS), c.find("s:f", NS)
                value = ""
                if formula is not None:
                    value = "=" + (formula.text or "")
                elif c.get("t") == "inlineStr":
                    value = "".join(c.find("s:is", NS).itertext())
                elif raw is not None:
                    value = strings[int(raw.text)] if c.get("t") == "s" else number(raw.text)
                if value != "":
                    cells[position(c.get("r"))] = value
            merges = []
            for merge in root.findall("s:mergeCells/s:mergeCell", NS):
                first, last = merge.get("ref").split(":")
                r1, c1 = position(first); r2, c2 = position(last)
                merges.append((r1, c1, r2 + 1, c2 + 1))
            result.append(Grid(sheet.get("name"), cells, merges))
        return result
    except (zipfile.BadZipFile, ET.ParseError, KeyError, IndexError, ValueError, AttributeError):
        raise QuizError(400, "無法讀取此學習單；請確認工作表可供讀取且為有效 Google Sheets。") from None


def from_google(payload):
    result = []
    for sheet in payload.get("sheets", []):
        properties = sheet["properties"]
        if properties.get("sheetType", "GRID") != "GRID":
            continue
        cells = {}
        for block in sheet.get("data", []):
            for r, row in enumerate(block.get("rowData", []), block.get("startRow", 0)):
                for c, cell in enumerate(row.get("values", []), block.get("startColumn", 0)):
                    value = cell.get("userEnteredValue", {})
                    if "formulaValue" in value:
                        raw = value["formulaValue"]
                    elif "stringValue" in value:
                        raw = value["stringValue"]
                    elif "numberValue" in value:
                        raw = number(value["numberValue"])
                    elif "boolValue" in value:
                        raw = "1" if value["boolValue"] else "0"
                    else:
                        raw = ""
                    if raw != "":
                        cells[(r, c)] = raw
        merges = [(m.get("startRowIndex", 0), m.get("startColumnIndex", 0), m["endRowIndex"], m["endColumnIndex"]) for m in sheet.get("merges", [])]
        result.append(Grid(properties["title"], cells, merges, properties["sheetId"]))
    return result


def fingerprint(grid, targets):
    excluded = {(t["row"], t["col"]) for t in targets}
    contents = [(r, c, value) for (r, c), value in sorted(grid.cells.items()) if (r, c) not in excluded and value != ""]
    data = {"cells": contents, "merges": sorted(grid.merges), "targets": sorted(excluded)}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def parse_grid(grid):
    targets = []
    marker_cells = [(rc, value) for rc, value in sorted(grid.cells.items()) if "{{Q:" in value]
    if marker_cells:
        for (row, col), value in marker_cells:
            match = re.fullmatch(r"\{\{Q:([^{}\n]{1,40})\}\}", value.strip())
            if not match or not match[1].strip():
                raise QuizError(400, f"{a1(row,col)} 的標記不完整；每格只能放一個完整的 {{{{Q:題號}}}}。")
            if grid.span(row, col)[:2] != (row, col):
                raise QuizError(400, "答案標記必須位於合併儲存格的左上角。")
            targets.append({"question": match[1].strip(), "row": row, "col": col})
        if any(value.strip() == "題號" for value in grid.cells.values()):
            clean = Grid(grid.title, {rc:v for rc,v in grid.cells.items() if "{{Q:" not in v}, grid.merges, grid.sheet_id)
            table_targets = parse_grid(clean)["targets"]
            expected = {(t["question"],t["row"],t["col"]) for t in table_targets}
            actual = {(t["question"],t["row"],t["col"]) for t in targets}
            if actual != expected:
                raise QuizError(400, "佔位符與題號表格不一致；請每題標記正確答案格，或全部使用原表頭定位。")
            for target, table_target in zip(targets, table_targets):
                target["unit"] = table_target["unit"]
    else:
        headers = []
        for (row, col), value in grid.cells.items():
            if value.strip() == "題號":
                question_cols = [c for (r,c),v in grid.cells.items() if r == row and v.strip() == "題目"]
                answer_cols = [c for (r,c),v in grid.cells.items() if r == row and v.strip() in ("作答", "答案")]
                if len(question_cols) == len(answer_cols) == 1:
                    headers.append((row, col, question_cols[0], answer_cols[0]))
        if len(headers) != 1:
            raise QuizError(400, "無法唯一找到「題號／題目／作答」表頭。請確認版面，或在答案格加入 {{Q:題號}}。")
        header, qcol, contentcol, acol = headers[0]
        parent_ids = set()
        for (row, col), value in sorted(grid.cells.items()):
            if col != qcol or row <= header or not value.strip():
                continue
            question = value.strip()
            if question in parent_ids: raise QuizError(400, "學習單題號重複。")
            parent_ids.add(question)
            if not grid.value(row, contentcol).strip():
                raise QuizError(400, f"題號 {question} 沒有可辨識的題目列。")
            parent = grid.span(row, col)
            if parent[:2] != (row, col): raise QuizError(400, "題號不在合併格起點。")
            if parent[2] - row > 1:
                if parent[2] - row > 100: raise QuizError(400, "題組子題數超過 100。")
                children = list(range(row, parent[2]))
                markers = [re.fullmatch(r"[（(](\d+)[）)]", grid.value(r, acol).strip()) for r in children]
                if any(markers) and any(not m or int(m[1]) != i+1 for i,m in enumerate(markers)):
                    raise QuizError(400, "題組子題標記缺漏、重複或順序不完整。")
                for i, r in enumerate(children, 1):
                    span = grid.span(r, acol)
                    if not grid.value(r, contentcol).strip() or grid.span(r, contentcol)[0] != r:
                        raise QuizError(400, "題組包含無法辨識的子題列。")
                    if span[0] != r or span[2] != r+1 or any(span[1] <= c < span[3] for c in (qcol, contentcol)):
                        raise QuizError(400, "題組答案格無法唯一定位。")
                    targets.append({"question":f"{question}.{i}", "unit":question, "row":r, "col":span[1]})
                continue
            span = grid.span(row, acol)
            if span[0] != row or span[2] != row + 1:
                raise QuizError(400, f"題號 {question} 的答案區跨列，無法唯一定位。")
            if any(span[1] <= c < span[3] for c in (qcol, contentcol)):
                raise QuizError(400, "答案區與題號或題目重疊，無法安全寫回。")
            if re.fullmatch(r"[（(]\d+[）)]", grid.value(row, acol).strip()):
                raise QuizError(400, "子題標記缺少跨列題組題號。")
            targets.append({"question": question, "row": row, "col": span[1]})
        target_rows = {t["row"] for t in targets}
        for (r,c), value in grid.cells.items():
            if r > header and c == contentcol and value.strip() and r not in target_rows:
                raise QuizError(400, "有題目列沒有獨立題號，可能是題組；請確認學習單。")
    if not 1 <= len(targets) <= 100:
        raise QuizError(400, "學習單必須包含 1～100 個可辨識的答案格。")
    ids = [t["question"] for t in targets]
    if len(set(ids)) != len(ids) or any(len(q) > 40 for q in ids):
        raise QuizError(400, "學習單題號重複或超過 40 字元。")
    if len({(t["row"],t["col"]) for t in targets}) != len(targets):
        raise QuizError(400, "多個題號對應相同答案格。")
    for target in targets:
        target.setdefault("unit", target["question"])
        target["cell"] = a1(target["row"], target["col"])
        target["original"] = grid.cells.get((target["row"], target["col"]), "")
    return {"sheet_title": grid.title, "sheet_id": grid.sheet_id, "targets": targets,
            "fingerprint": fingerprint(grid, targets)}


def prepare_export(source, grid, winners):
    if grid.title != source["sheet_title"] or (source.get("sheet_id") is not None and grid.sheet_id != source["sheet_id"]):
        raise QuizError(409, "來源工作表已變更，請重新匯入。")
    if fingerprint(grid, source["targets"]) != source["fingerprint"]:
        raise QuizError(409, "來源題目、位置或合併格已改動，已停止寫回。請重新匯入。")
    requests, expected = [], {}
    for target in source["targets"]:
        q, row, col = target["question"], target["row"], target["col"]
        value = grid.cells.get((row,col), "")
        winner = winners.get(q)
        # Restore only our own previous export when its winner is disqualified.
        if winner is None and q in source.get("last_export", {}):
            winner = target["original"]
        previous = source.get("last_export", {}).get(q, target["original"])
        if value != previous and (winner is None or value != winner):
            raise QuizError(409, f"{target['cell']} 已被修改，已停止寫回以保留原內容。")
        if winner is None:
            continue
        expected[q] = winner
        requests.append({"updateCells": {"start": {"sheetId": grid.sheet_id, "rowIndex": row, "columnIndex": col},
                        "rows": [{"values": [{"userEnteredValue": {"stringValue": winner}}]}], "fields": "userEnteredValue"}})
    return requests, expected
