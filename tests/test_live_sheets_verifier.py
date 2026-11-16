"""Verify the acceptance oracle cannot hide unrelated changes; no cloud access."""
import copy
import unittest
from run_live_sheets import normalized


class SnapshotOracleTests(unittest.TestCase):
    def setUp(self):
        self.before = {"spreadsheetId": "synthetic-test-id", "sheets": [
            {"properties": {"sheetId": 7, "title": "Test"}, "data": [
                {"rowData": [{"values": [
                    {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    {"userEnteredValue": {"stringValue": "keep"}}
                ]}], "rowMetadata": [{"pixelSize": 30}]}]}]}

    def test_allow_only_expected_answer_value(self):
        after = copy.deepcopy(self.before)
        after["sheets"][0]["data"][0]["rowData"][0]["values"][0]["userEnteredValue"] = {"stringValue": "answer"}
        self.assertEqual(normalized(self.before, [(7, 0, 0)]), normalized(after, [(7, 0, 0)]))
        self.assertNotEqual(normalized(self.before), normalized(after))

    def test_detect_format_content_identity_and_dimension_changes(self):
        for change in ("format", "unanswered", "identity", "dimensions", "new_cell", "merge"):
            with self.subTest(change=change):
                after = copy.deepcopy(self.before)
                sheet = after["sheets"][0]
                block = sheet["data"][0]
                values = block["rowData"][0]["values"]
                if change == "format": values[0]["userEnteredFormat"] = {}
                if change == "unanswered": values[1]["userEnteredValue"] = {"stringValue": "changed"}
                if change == "identity": sheet["properties"]["sheetId"] = 8
                if change == "dimensions": block["rowMetadata"][0]["pixelSize"] = 40
                if change == "new_cell": values.append({"userEnteredValue": {"stringValue": "unexpected"}})
                if change == "merge": sheet["merges"] = [{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 2}]
                self.assertNotEqual(normalized(self.before, [(7, 0, 0)]), normalized(after, [(7, 0, 0)]))


if __name__ == "__main__":
    unittest.main()
