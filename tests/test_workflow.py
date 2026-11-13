"""使用临时 SQLite 数据库验证 HTTP 主流程和面试提交状态。"""

import json
import os
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import MagicMock, Mock, patch
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from deepseek import DeepSeekClient
from question_bank import ROLES
from server import Handler
from storage import Store
import server
from local_config import read_api_key, save_api_key


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "test.sqlite3"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(self.server.server_close)
        self.server.store = Store(self.db_path)
        self.server.deepseek = None
        worker = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            binary = isinstance(payload, bytes)
            body = payload if binary else (json.dumps(payload).encode("utf-8") if payload is not None else None)
            connection.request(method, path, body=body, headers={
                "Content-Type": "application/pdf" if binary else "application/json"})
            response = connection.getresponse()
            content = response.read()
            if response.headers.get_content_type() == "application/json":
                content = json.loads(content)
            return response.status, content
        finally:
            connection.close()

    def test_resume_report_and_history(self):
        status, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("简历优化".encode("utf-8"), html)
        status, result = self.request("POST", "/api/resumes", {
            "role": "backend", "description": "Python、Redis、SQL",
            "resume": "项目经历\n我实现 Python 查询接口，使用 MySQL 处理 2000 条记录。",
        })
        self.assertEqual(status, 201)
        report = result["report"]
        self.assertEqual(report["matched"], ["Python"])
        self.assertEqual(report["missing"], ["SQL", "Redis"])
        self.assertIn("- 实现 Python", report["draft"])
        self.assertIn("2000 条", report["draft"])
        self.assertEqual(len(report["dimensions"]), 4)
        history = Store(self.db_path).history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["score"], report["score"])
        path = "/api/records/" + result["id"]
        self.assertEqual(self.request("GET", path)[1]["report"], report)
        self.assertEqual(self.request("DELETE", path)[0], 200)
        self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("GET", "/api/history"), (200, []))

    def test_interview_submit_is_idempotent(self):
        status, interview = self.request("POST", "/api/interviews", {"role": "frontend", "count": 3})
        self.assertEqual(status, 201)
        self.assertEqual(len(interview["questions"]), 3)
        self.assertEqual(set(interview["questions"][0]), {"category", "text"})
        self.assertEqual(self.request("GET", "/api/history"), (200, []))
        path = "/api/interviews/" + interview["id"] + "/finish"
        self.assertEqual(self.request("POST", path, {"answers": ["太短"] * 3})[0], 400)

        answers = [
            ["负责组件拆分，处理接口异常，再运行测试用例完成验收。"] * 3,
            ["我会逐项记录我的做法，然后说明所观察到的结果。"] * 3,
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda value: self.request("POST", path, {"answers": value}), answers))
        self.assertEqual(results[0], results[1])
        status, report = results[0]
        self.assertEqual(status, 200)
        self.assertEqual(len(report["feedback"]), 3)
        self.assertIn([item["answer"] for item in report["feedback"]], answers)
        self.assertEqual(len(self.request("GET", "/api/history")[1]), 1)

    def test_invalid_requests_do_not_create_history(self):
        self.assertEqual(self.request("POST", "/api/resumes", {"role": []})[0], 400)
        self.assertEqual(self.request("POST", "/api/resumes", {"role": "backend", "resume": "太短"})[0], 400)
        self.assertEqual(self.request("POST", "/api/interviews", {"role": "backend", "count": "3"})[0], 400)
        self.assertEqual(self.request("GET", "/api/history"), (200, []))

    def test_different_interviews_can_finish_concurrently(self):
        slow_id = "a" * 32
        fast_id = "a" + "b" * 31
        for record_id, role in [(slow_id, "backend"), (fast_id, "frontend")]:
            questions = ROLES[role]["questions"][:3]
            self.server.store.create(record_id, "interview", role, {"questions": questions, "use_ai": True})

        slow_started = Event()
        release_slow = Event()

        def report(role, questions, answers):
            if role == ROLES["backend"]["label"]:
                slow_started.set()
                if not release_slow.wait(timeout=5):
                    raise TimeoutError("等待释放第一场面试点评超时")
            return server.interview_report(questions, answers)

        self.server.deepseek = Mock()
        self.server.deepseek.report.side_effect = report
        payload = {"answers": ["我会运行测试用例并核对实际验收结果。"] * 3}
        with ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(self.request, "POST", f"/api/interviews/{slow_id}/finish", payload)
            try:
                self.assertTrue(slow_started.wait(timeout=2))
                fast = pool.submit(self.request, "POST", f"/api/interviews/{fast_id}/finish", payload)
                self.assertEqual(fast.result(timeout=2)[0], 200)
                self.assertFalse(slow.done())
            finally:
                release_slow.set()
            self.assertEqual(slow.result()[0], 200)

    def configure_deepseek(self, responses):
        client = DeepSeekClient("test-key")
        client.opener = Mock()
        client.opener.open.side_effect = [
            BytesIO(json.dumps({"choices": [{
                "finish_reason": "stop", "message": {"content": json.dumps(response)},
            }]}).encode("utf-8"))
            for response in responses
        ]
        self.server.deepseek = client
        return client.opener.open

    @staticmethod
    def generated_questions():
        return {"questions": [{
            "category": "系统设计",
            "text": f"如何为第 {index} 类报名活动设计防止超卖的机制？",
            "rubric": [
                {"label": "识别并发问题", "cues": ["并发", "一致性"]},
                {"label": "说明扣减机制", "cues": ["事务", "原子"]},
                {"label": "验证结果", "cues": ["压测", "测试"]},
            ],
        } for index in range(1, 4)]}

    def test_deepseek_question_and_report_flow(self):
        upstream = self.configure_deepseek([self.generated_questions(), {"feedback": [{
            "number": index, "relevance": 80, "accuracy": 90, "specificity": 60,
            "comment": "事务方案合理，但缺少压测细节。",
            "strength": "说明了并发扣减的边界。",
            "improvement": "给出并发量及预期库存结果。",
        } for index in range(1, 4)]}])
        self.assertEqual(self.request("GET", "/api/interviews/config"), (200, {"ai_available": True}))
        status, interview = self.request("POST", "/api/interviews", {
            "role": "backend", "count": 3, "use_ai": True, "difficulty": "advanced",
            "description": "Python API development", "context": "Built a course enrollment API.",
        })
        self.assertEqual(status, 201)
        self.assertEqual(interview["question_source"], "deepseek")
        self.assertEqual(set(interview["questions"][0]), {"category", "text"})
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        request_payload = json.loads(request.data)
        self.assertEqual(request_payload["response_format"], {"type": "json_object"})
        self.assertEqual(request_payload["thinking"], {"type": "disabled"})
        self.assertEqual(request_payload["model"], "deepseek-flash")
        self.assertNotIn("enable_thinking", request_payload)
        question_context = json.loads(request_payload["messages"][1]["content"])
        self.assertEqual(question_context["difficulty"], "advanced")
        self.assertEqual(question_context["description"], "Python API development")
        self.assertEqual(question_context["context"], "Built a course enrollment API.")

        path = "/api/interviews/" + interview["id"] + "/finish"
        answers = ["通过事务执行原子扣减，防止并发修改造成超卖。"] * 3
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.request, "POST", path, {"answers": answers}) for _ in range(2)]
            results = [future.result() for future in futures]
        self.assertEqual(results[0], results[1])
        status, report = results[0]
        self.assertEqual(status, 200)
        self.assertEqual(report["evaluation"], "deepseek")
        self.assertEqual(report["difficulty"], "advanced")
        self.assertEqual(report["score"], 79)
        self.assertEqual(report["feedback"][0]["comment"], "事务方案合理，但缺少压测细节。")
        self.assertEqual(upstream.call_count, 2)
        review_request = json.loads(upstream.call_args.args[0].data)
        review_items = json.loads(review_request["messages"][1]["content"])["items"]
        self.assertEqual(review_items[0]["question"], interview["questions"][0]["text"])
        self.assertEqual(review_items[0]["answer"], answers[0])
        self.assertEqual(self.request("GET", "/api/records/" + interview["id"])[1]["report"], report)

    def test_deepseek_invalid_feedback_preserves_generated_questions_and_answers(self):
        self.configure_deepseek([self.generated_questions(), {"feedback": []}])
        _, interview = self.request("POST", "/api/interviews", {"role": "backend", "count": 3, "use_ai": True})
        path = "/api/interviews/" + interview["id"] + "/finish"
        answer = "用事务实现原子扣减库存，并通过压测验证并发一致性。"
        status, report = self.request("POST", path, {"answers": [answer] * 3})
        self.assertEqual(status, 200)
        self.assertEqual(report["question_source"], "deepseek")
        self.assertEqual(report["evaluation"], "local")
        self.assertIn("本地规则", report["notice"])
        self.assertEqual(report["feedback"][0]["question"], interview["questions"][0]["text"])
        self.assertEqual(report["feedback"][0]["answer"], answer)

    def test_deepseek_question_timeout_falls_back_to_local_bank(self):
        upstream = self.configure_deepseek([])
        upstream.side_effect = TimeoutError()
        status, interview = self.request("POST", "/api/interviews", {"role": "backend", "count": 5, "use_ai": True})
        self.assertEqual(status, 201)
        self.assertEqual(interview["question_source"], "local")
        self.assertEqual(len(interview["questions"]), 5)

    def test_deepseek_configuration_uses_its_own_key(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "old-provider-key", "DEEPSEEK_API_KEY": "",
                                    "DEEPSEEK_BASE_URL": "", "DEEPSEEK_MODEL": ""}):
            self.assertIsNone(DeepSeekClient.from_env())
            client = DeepSeekClient.from_env(" new-provider-key ")
            self.assertEqual(client.api_key, "new-provider-key")
            self.assertEqual(client.url, "https://api.deepseek.com/chat/completions")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "new-provider-key",
                                    "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1"}):
            self.assertEqual(DeepSeekClient.from_env().url, "https://api.deepseek.com/v1/chat/completions")

    @staticmethod
    def pdf_fixture(text=None, encrypted=False):
        writer = PdfWriter()
        page = writer.add_blank_page(595, 842)
        if text:
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
            })
            content = DecodedStreamObject()
            content.set_data(("BT /F1 12 Tf 40 780 Td (" + text + ") Tj ET").encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(content)
        if encrypted:
            writer.encrypt("test-password")
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def test_pdf_import_and_resume_diagnosis(self):
        pdf = self.pdf_fixture("Project: built Python REST API with SQL and 18 unit tests.")
        status, parsed = self.request("POST", "/api/resumes/import", pdf)
        self.assertEqual(status, 200)
        self.assertEqual(parsed["pages"], 1)
        self.assertIn("Python REST API", parsed["text"])
        status, report = self.request("POST", "/api/resumes", {"role": "backend", "resume": parsed["text"]})
        self.assertEqual(status, 201)
        self.assertIn("Python", report["report"]["matched"])
        self.assertEqual(len(self.request("GET", "/api/history")[1]), 1)

    def test_pdf_invalid_empty_and_password_protected(self):
        for pdf in (b"not a PDF", b"%PDF-broken", self.pdf_fixture(),
                    self.pdf_fixture("A private resume document.", encrypted=True)):
            with self.subTest(size=len(pdf)):
                status, result = self.request("POST", "/api/resumes/import", pdf)
                self.assertEqual(status, 400)
                self.assertIn("error", result)
        self.assertEqual(self.request("GET", "/api/history"), (200, []))

    def test_expanded_roles_and_local_difficulty(self):
        status, roles = self.request("GET", "/api/roles")
        self.assertEqual(status, 200)
        self.assertEqual(len(roles), 10)
        for role in ("qa", "devops", "algorithm", "mobile", "security", "embedded"):
            status, interview = self.request("POST", "/api/interviews", {
                "role": role, "count": 5, "difficulty": "advanced"})
            self.assertEqual(status, 201)
            self.assertEqual(len(interview["questions"]), 5)
            self.assertEqual(len({q["text"] for q in interview["questions"]}), 5)
            self.assertIn("失败场景", interview["questions"][0]["text"])
        self.assertEqual(self.request("POST", "/api/interviews",
                                     {"role": "qa", "count": 3, "difficulty": []})[0], 400)

    def test_bookmarks_upsert_persistence_and_delete(self):
        data = {"role": "backend", "question": "如何设计一个并发接口？",
                "answer": "使用事务保证原子性，再进行压力测试。", "note": "补充验证数据。"}
        status, first = self.request("POST", "/api/bookmarks", data)
        self.assertEqual(status, 201)
        data["note"] = "检查边界和失败场景。"
        _, second = self.request("POST", "/api/bookmarks", data)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(Store(self.db_path).bookmarks()), 1)
        self.assertEqual(self.request("GET", "/api/bookmarks")[1][0]["note"], data["note"])
        self.assertEqual(self.request("DELETE", "/api/bookmarks/" + first["id"])[0], 200)
        self.assertEqual(self.request("GET", "/api/bookmarks"), (200, []))

    def test_deepseek_resume_optimization_and_history(self):
        upstream = self.configure_deepseek([{
            "draft": "项目经历\n实现 Python 查询接口，使用 SQL 处理数据并完成 18 个测试。",
            "suggestions": [
                {"title": "突出接口贡献", "detail": "将自己实现的查询接口放在项目描述开头。"},
                {"title": "补充验证方式", "detail": "核对测试范围，并补充真实的验收结果。"},
            ],
        }])
        original = "项目经历\n我实现 Python 查询接口，使用 SQL 处理数据，编写了 18 个测试。"
        status, result = self.request("POST", "/api/resumes", {
            "role": "backend", "resume": original, "description": "Python、SQL", "use_ai": True})
        self.assertEqual(status, 201)
        report = result["report"]
        self.assertEqual(report["optimization"], "deepseek")
        self.assertIn("18 个测试", report["draft"])
        self.assertEqual(len(report["dimensions"]), 4)
        sent = json.loads(json.loads(upstream.call_args.args[0].data)["messages"][1]["content"])
        self.assertEqual(sent["resume"], original)
        self.assertEqual(sent["description"], "Python、SQL")
        self.assertEqual(self.request("GET", "/api/records/" + result["id"])[1]["report"], report)

    def test_deepseek_resume_failure_preserves_local_draft(self):
        self.configure_deepseek([{"draft": "", "suggestions": []}])
        status, result = self.request("POST", "/api/resumes", {
            "role": "backend", "resume": "项目经历\n我负责 Python 接口开发并执行 18 个测试。", "use_ai": True})
        self.assertEqual(status, 201)
        self.assertEqual(result["report"]["optimization"], "local")
        self.assertIn("18 个测试", result["report"]["draft"])
        self.assertIn("本地整理稿", result["report"]["notice"])

    def test_saved_api_key_is_reused_after_restart(self):
        config_path = self.db_path.parent / ".local" / "deepseek.json"
        fake_server = MagicMock()
        fake_server.__enter__.return_value = fake_server
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "DEEPSEEK_BASE_URL": "", "DEEPSEEK_MODEL": ""}), \
             patch.object(server, "Store"), \
             patch.object(server, "ThreadingHTTPServer", return_value=fake_server), \
             patch.object(server, "read_api_key", side_effect=lambda: read_api_key(config_path)), \
             patch.object(server, "save_api_key", side_effect=lambda key: save_api_key(key, config_path)), \
             patch("builtins.print"), \
             patch.object(server.getpass, "getpass", return_value=" saved-test-key ") as prompt:
            with patch("sys.argv", ["server.py", "--save-api-key"]):
                server.main()
            self.assertEqual(read_api_key(config_path), "saved-test-key")
            prompt.reset_mock()
            with patch("sys.argv", ["server.py"]):
                server.main()
            prompt.assert_not_called()
            self.assertEqual(fake_server.deepseek.api_key, "saved-test-key")
        save_api_key("replacement-test-key", config_path)
        self.assertEqual(read_api_key(config_path), "replacement-test-key")
        self.assertEqual(len(list(config_path.parent.iterdir())), 1)
        config_path.write_text("invalid json", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_api_key(config_path)

    def test_resume_version_compare_restore_and_delete(self):
        original = {"title": "初稿", "role": "frontend", "resume": "项目经历\n我负责一个课程项目，完成了用户列表。",
                    "description": "Vue、CSS"}
        updated = {"title": "后端版", "role": "backend",
                   "resume": "项目经历\n设计 Python REST API，使用 SQL 并编写 18 个单元测试。",
                   "description": "Python、SQL"}
        _, first = self.request("POST", "/api/versions", original)
        _, second = self.request("POST", "/api/versions", updated)
        self.assertEqual(self.request("GET", "/api/versions/" + first["id"])[1]["resume"], original["resume"])
        status, compared = self.request("POST", "/api/versions/compare",
                                        {"before": first["id"], "after": second["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(compared["role"], "backend")
        self.assertEqual(compared["description"], "Python、SQL")
        self.assertGreater(compared["after_score"], compared["before_score"])
        self.assertEqual({item["type"] for item in compared["lines"]}, {" ", "-", "+"})
        self.assertEqual(len(Store(self.db_path).versions()), 2)
        self.assertEqual(self.request("DELETE", "/api/versions/" + first["id"])[0], 200)
        self.assertEqual(self.request("POST", "/api/versions/compare",
                                      {"before": first["id"], "after": second["id"]})[0], 404)

    def test_plan_status_validation_and_persistence(self):
        status, task = self.request("POST", "/api/tasks", {
            "title": "补充性能测试结果", "role": "backend", "due_date": "2026-11-12"})
        self.assertEqual(status, 201)
        path = "/api/tasks/" + task["id"]
        self.assertEqual(self.request("PATCH", path, {"done": "true"})[0], 400)
        self.assertEqual(self.request("PATCH", path, {"done": True})[1]["done"], 1)
        self.assertEqual(Store(self.db_path).tasks()[0]["done"], 1)
        self.assertEqual(self.request("PATCH", path, {"done": False})[1]["done"], 0)
        self.assertEqual(self.request("POST", "/api/tasks", {
            "title": "检查日期", "role": "backend", "due_date": "2026-02-30"})[0], 400)
        self.assertEqual(self.request("DELETE", path)[0], 200)
        self.assertEqual(self.request("GET", "/api/tasks"), (200, []))

    def test_bookmark_review_migrates_existing_database(self):
        legacy_path = self.db_path.parent / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as db:
            db.executescript("""
                CREATE TABLE bookmarks (
                    id TEXT PRIMARY KEY, role TEXT NOT NULL, question TEXT NOT NULL,
                    answer TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(role, question));
                INSERT INTO bookmarks VALUES ('old', 'backend', '旧题目', '原回答', '原建议', '2026-11-01');
            """)
        db.close()
        migrated = Store(legacy_path)
        self.assertEqual(migrated.bookmarks()[0]["reviewed"], 0)
        self.assertEqual(Store(legacy_path).bookmarks()[0]["answer"], "原回答")
        _, item = self.request("POST", "/api/bookmarks",
                               {"role": "backend", "question": "如何测试并发？", "answer": "原来的回答。"})
        path = "/api/bookmarks/" + item["id"]
        self.assertEqual(self.request("PATCH", path, {"reviewed": True, "review_answer": "太短"})[0], 400)
        answer = "我会准备并发负载，运行测试并核对预期库存。"
        reviewed = self.request("PATCH", path, {"reviewed": True, "review_answer": answer})[1]
        self.assertEqual(reviewed["review_answer"], answer)
        self.assertEqual(reviewed["reviewed"], 1)
        reset = self.request("PATCH", path, {"reviewed": False})[1]
        self.assertEqual(reset["reviewed"], 0)
        self.assertEqual(reset["review_answer"], answer)

    def test_analytics_separates_scoring_conditions(self):
        for index, (role, method, difficulty, score) in enumerate([
            ("backend", "local", "standard", 40), ("backend", "local", "standard", 80),
            ("backend", "deepseek", "standard", 90), ("frontend", "local", "standard", 70),
            ("backend", "local", "advanced", 60),
        ]):
            record_id = str(index).zfill(32)
            self.server.store.create(record_id, "interview", role, {}, {
                "score": score, "evaluation": method, "difficulty": difficulty,
                "dimensions": [{"label": "准确性", "score": score}],
            })
            with self.server.store.connect() as db:
                db.execute("UPDATE records SET created_at = ? WHERE id = ?",
                           (f"2026-11-0{index+1}T00:00:00Z", record_id))
        status, analytics = self.request("GET", "/api/analytics")
        self.assertEqual(status, 200)
        self.assertEqual(analytics["total"], 5)
        self.assertEqual(len(analytics["groups"]), 4)
        group = next(item for item in analytics["groups"] if item["count"] == 2)
        self.assertEqual(group["average"], 60)
        self.assertEqual(group["change"], 40)
        self.assertEqual([item["score"] for item in group["series"]], [40, 80])

    def test_resume_analytics_does_not_turn_jd_changes_into_progress(self):
        # 同一正文只换 JD 会改变规则分，不能把它解释为训练进步或退步。
        resume = "项目经历\n我负责 Python 接口开发并执行18个测试。"
        record_ids = []
        scores = []
        for index, description in enumerate(["Python", "Redis", "Python"]):
            status, result = self.request("POST", "/api/resumes", {
                "role": "backend", "resume": resume, "description": description,
            })
            self.assertEqual(status, 201)
            record_ids.append(result["id"])
            scores.append(result["report"]["score"])
            with self.server.store.connect() as db:
                db.execute("UPDATE records SET created_at = ? WHERE id = ?",
                           (f"2026-11-0{index+1}T00:00:00Z", result["id"]))
        self.assertNotEqual(scores[0], scores[1])
        status, analytics = self.request("GET", "/api/analytics")
        self.assertEqual(status, 200)
        self.assertEqual(analytics["total"], 3)
        self.assertEqual(len(analytics["groups"]), 2)
        groups = {group["description"]: group for group in analytics["groups"]}
        self.assertEqual(groups["Python"]["count"], 2)
        self.assertEqual(groups["Python"]["change"], 0)
        self.assertEqual([point["id"] for point in groups["Python"]["series"]],
                         [record_ids[0], record_ids[2]])
        self.assertEqual(groups["Redis"]["count"], 1)
        self.assertIsNone(groups["Redis"]["change"])

    def test_resume_analytics_keeps_legacy_default_reports_readable(self):
        # 未保存 JD 的旧格式报告仍可与空 JD 报告统计，不要求用户删库。
        for index, metadata in enumerate([{}, {"description": ""}, {"description": "Python"}]):
            self.server.store.create(str(index).zfill(32), "resume", "backend", {}, {
                "score": 50, "dimensions": [{"label": "岗位匹配", "score": 50}], **metadata,
            })
        status, analytics = self.request("GET", "/api/analytics")
        self.assertEqual(status, 200)
        self.assertEqual(len(analytics["groups"]), 2)
        group = next(item for item in analytics["groups"] if item["description"] == "")
        self.assertEqual(group["description"], "")
        self.assertEqual(group["count"], 2)
        self.assertEqual(group["change"], 0)
