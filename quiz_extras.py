"""Optional classroom features; uses the service's transaction and role checks."""
import csv
from datetime import datetime, timezone
import io


def csv_bytes(rows):
    def safe(value):
        value = str(value if value is not None else "")
        # Excel may strip leading whitespace before interpreting a formula.
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value
    output = io.StringIO(newline="")
    csv.writer(output).writerows([[safe(value) for value in row] for row in rows])
    return output.getvalue().encode("utf-8-sig")


class ExtraFeatures:
    def activity_csv(self, token, aid):
        from quiz_service import QuizError
        with self.lock:
            self._auth(token, "teacher")
            state = self.snapshot(token, aid)
            if state["phase"] != "results":
                raise QuizError(409, "請先結束活動再下載紀錄。")
            winners = {r["question_id"]: r["winner"] for r in state["results"]}
            rows = [["題號", "題組", "組別", "答案", "收件時間 UTC", "開始後秒數", "原始順位", "搶答成功"]]
            for question in state["questions"]:
                answers = [a for a in state["answers"] if a["question_id"] == question]
                if not answers:
                    rows.append([question, question, "", "無人作答", "", "", "", "否"])
                for rank, answer in enumerate(answers, 1):
                    winner = winners[question]
                    rows.append([question, question, answer["group_name"], answer["text"],
                                 datetime.fromtimestamp(answer["received_at"], timezone.utc).isoformat(),
                                 f"{answer['elapsed_ms']/1000:.3f}", rank,
                                 "是" if winner and winner["group_name"] == answer["group_name"] else "否"])
            return csv_bytes(rows)
