import copy
import unittest
from pathlib import Path
from guided_notes import Grid, a1, from_xlsx, from_google, parse_grid, prepare_export, spreadsheet_id
from quiz_service import QuizError

FIXTURES = Path(__file__).parent / "fixtures"


def single():
    return from_xlsx((FIXTURES / "single.xlsx").read_bytes())[0]


def payload(grid):
    """Encode fixture as a Sheets API response, including unrelated formatting."""
    rows = []
    for r in range(max(r for r,c in grid.cells) + 1):
        cells = []
        for c in range(max(c for r,c in grid.cells) + 1):
            cell = {"userEnteredFormat":{"backgroundColor":{"red":0.8}}, "note":"preserve"}
            if (r,c) in grid.cells:
                cell["userEnteredValue"] = {"stringValue":grid.cells[r,c]}
            cells.append(cell)
        rows.append({"values":cells})
    return {"spreadsheetId":"test-copy-spreadsheet-id-123", "sheets":[{
        "properties":{"title":grid.title, "sheetId":grid.sheet_id or 0, "sheetType":"GRID"},
        "merges":[dict(zip(("startRowIndex","startColumnIndex","endRowIndex","endColumnIndex"), m)) for m in grid.merges],
        "data":[{"rowData":rows}]}]}


class GuidedNotesTests(unittest.TestCase):
    def test_actual_single_and_grouped_templates(self):
        source = parse_grid(single())
        self.assertEqual([str(i) for i in range(1,7)], [t["question"] for t in source["targets"]])
        self.assertEqual(["G5","G7","G9","G11","G13","G15"], [t["cell"] for t in source["targets"]])
        grouped = from_xlsx((FIXTURES / "grouped.xlsx").read_bytes())[0]
        targets = parse_grid(grouped)["targets"]
        self.assertEqual(['1.1','1.2','2.1','2.2','3','4'], [t['question'] for t in targets])
        self.assertEqual(['1','1','2','2','3','4'], [t['unit'] for t in targets])
        self.assertEqual(['G5','G6','G8','G9','G11','G13'], [t['cell'] for t in targets])
        shifted = Grid(grouped.title, {(r+7,c+2):v for (r,c),v in grouped.cells.items()}, [(r+7,c+2,r2+7,c2+2) for r,c,r2,c2 in grouped.merges])
        self.assertEqual(['I12','I13','I15','I16','I18','I20'], [t['cell'] for t in parse_grid(shifted)['targets']])
        grouped.cells[(5,6)] = '(3)'
        with self.assertRaisesRegex(QuizError, '標記'): parse_grid(grouped)

    def test_moved_rows_columns_and_answer_column(self):
        g = single()
        shifted = Grid(g.title, {(r+8,c+3):v for (r,c),v in g.cells.items()},
                       [(r1+8,c1+3,r2+8,c2+3) for r1,c1,r2,c2 in g.merges])
        targets = parse_grid(shifted)["targets"]
        self.assertEqual(["J13","J15","J17","J19","J21","J23"], [t["cell"] for t in targets])
        # A different column order, unrelated to the official coordinates.
        alternate = Grid("別版", {(2,8):"題號", (2,6):"題目", (2,1):"答案", (4,8):"A", (4,6):"問題"}, [])
        self.assertEqual("B5", parse_grid(alternate)["targets"][0]["cell"])
        self.assertEqual('問題', parse_grid(alternate)['targets'][0]['prompt'])
        alternate.cells[(4,1)] = '{{Q:A}}'
        self.assertEqual('問題', parse_grid(alternate)['targets'][0]['prompt'])

    def test_invalid_layouts_do_not_silently_drop_questions(self):
        g = single(); g.cells[(6,1)] = "1"
        with self.assertRaisesRegex(QuizError, "重複"): parse_grid(g)
        g = single(); del g.cells[(6,1)]
        with self.assertRaisesRegex(QuizError, "沒有獨立題號"): parse_grid(g)
        g = single(); g.cells[(3,9)] = "答案"
        with self.assertRaisesRegex(QuizError, "表頭"): parse_grid(g)
        g = single(); g.cells[(4,6)] = "{{Q:1}}"
        with self.assertRaisesRegex(QuizError, "不一致"): parse_grid(g)

    def test_marker_layout_and_validation(self):
        grid = Grid("自訂", {(18,2):"{{Q:第一題}}", (2,15):"{{Q:第二題}}"}, [])
        self.assertEqual({"C19","P3"}, {t["cell"] for t in parse_grid(grid)["targets"]})
        for cells in [{(1,1):"prefix {{Q:1}}"}, {(1,1):"{{Q:1}}{{Q:2}}"}, {(1,1):"{{Q:1}}", (2,1):"{{Q:1}}"}]:
            with self.assertRaises(QuizError): parse_grid(Grid("自訂",cells,[]))

    def test_public_and_authenticated_representation_agree(self):
        g = single(); remote = from_google(payload(g))[0]
        self.assertEqual(parse_grid(g)["fingerprint"], parse_grid(remote)["fingerprint"])
        self.assertEqual(parse_grid(g)["targets"], parse_grid(remote)["targets"])

    def test_write_plan_preserves_format_and_uses_literal_text(self):
        g = single(); g.sheet_id = 42; source = parse_grid(g)
        requests, expected = prepare_export(source,g,{"1":"=SUM(A1:A2)","3":"答案"})
        self.assertEqual(2,len(requests)); self.assertEqual("=SUM(A1:A2)",expected["1"])
        self.assertEqual({"sheetId":42,"rowIndex":4,"columnIndex":6},requests[0]["updateCells"]["start"])
        self.assertEqual("userEnteredValue",requests[0]["updateCells"]["fields"])
        self.assertEqual({"stringValue":"=SUM(A1:A2)"}, requests[0]["updateCells"]["rows"][0]["values"][0]["userEnteredValue"])
        self.assertEqual(([],{}), prepare_export(source,g,{}))

    def test_source_conflicts_and_idempotent_retry(self):
        g = single(); g.sheet_id=0; source=parse_grid(g)
        for mutate in [lambda x:x.cells.update({(4,2):"changed question"}), lambda x:x.cells.update({(4,6):"manual answer"}), lambda x:x.merges.pop()]:
            changed=copy.deepcopy(g); mutate(changed)
            with self.assertRaises(QuizError): prepare_export(source,changed,{"1":"winner"})
        g.cells[(4,6)]="winner"
        self.assertEqual(0,len(prepare_export(source,g,{"1":"winner"})[0]))
        g.sheet_id=99
        with self.assertRaises(QuizError): prepare_export(source,g,{"1":"winner"})

    def test_untrusted_urls_and_malformed_files(self):
        for url in [None,"http://localhost/", "https://docs.google.com.evil.test/spreadsheets/d/12345678901234567890", "https://example.org/"]:
            with self.assertRaises(QuizError): spreadsheet_id(url)
        with self.assertRaises(QuizError): from_xlsx(b"not a workbook")
        self.assertEqual("AA1",a1(0,26))


if __name__ == "__main__": unittest.main()
