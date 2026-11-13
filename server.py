"""本地 HTTP 入口。运行 python server.py --help 查看参数。"""

import argparse
import getpass
import json
import logging
import os
import re
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4
from weakref import WeakValueDictionary

from engine import MAX_RESUME_LENGTH, MIN_RESUME_LENGTH, interview_report, resume_report
from question_bank import ROLES
from deepseek import DeepSeekClient, DeepSeekError
from storage import Store
from local_config import read_api_key, save_api_key
from resume_files import ResumeFileError, extract_pdf
from progress import compare_versions, training_analytics


ROOT = Path(__file__).resolve().parent
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/features.js": ("features.js", "text/javascript; charset=utf-8"),
    "/icons.svg": ("icons.svg", "image/svg+xml"),
}
RECORD_PATH = re.compile(r"/api/records/([a-f0-9]{32})")
FINISH_PATH = re.compile(r"/api/interviews/([a-f0-9]{32})/finish")
BOOKMARK_PATH = re.compile(r"/api/bookmarks/([a-f0-9]{32})")
VERSION_PATH = re.compile(r"/api/versions/([a-f0-9]{32})")
TASK_PATH = re.compile(r"/api/tasks/([a-f0-9]{32})")
FINISH_LOCKS = WeakValueDictionary()
FINISH_LOCKS_GUARD = Lock()


def interview_finish_lock(record_id):
    # 请求持有锁的强引用，最后一个请求结束后自动清理。
    with FINISH_LOCKS_GUARD:
        lock = FINISH_LOCKS.get(record_id)
        if lock is None:
            lock = Lock()
            FINISH_LOCKS[record_id] = lock
        return lock


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def validated_text(value, name, minimum, maximum):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ApiError(400, f"{name}需为 {minimum}–{maximum} 字符。")
    return value.strip()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_DELETE(self):
        self.handle_request("DELETE")

    def do_PATCH(self):
        self.handle_request("PATCH")

    def handle_request(self, method):
        path = urlsplit(self.path).path
        try:
            if method == "GET" and path in STATIC:
                filename, mime = STATIC[path]
                self.send_bytes(200, (ROOT / "public" / filename).read_bytes(), mime)
                return
            status, result = self.route(method, path)
        except ApiError as error:
            status, result = error.status, {"error": str(error)}
        except Exception:
            logging.exception("Request failed")
            status, result = 500, {"error": "服务器暂时无法处理请求，请重试。"}
        self.send_bytes(status, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def route(self, method, path):
        store = self.server.store
        deepseek = self.server.deepseek
        record_path = RECORD_PATH.fullmatch(path)
        finish_path = FINISH_PATH.fullmatch(path)
        bookmark_path = BOOKMARK_PATH.fullmatch(path)
        version_path = VERSION_PATH.fullmatch(path)
        task_path = TASK_PATH.fullmatch(path)
        if method == "GET" and path == "/api/analytics":
            return 200, training_analytics(store.completed_reports())
        if method == "GET" and path == "/api/versions":
            return 200, store.versions()
        if method == "POST" and path == "/api/versions":
            data = self.read_json()
            role = validated_text(data.get("role"), "岗位", 1, 40)
            if role not in ROLES:
                raise ApiError(400, "请选择有效岗位。")
            return 201, store.create_version(
                uuid4().hex, validated_text(data.get("title"), "版本名称", 1, 80), role,
                validated_text(data.get("resume"), "简历正文", MIN_RESUME_LENGTH, MAX_RESUME_LENGTH),
                validated_text(data.get("description", ""), "岗位描述", 0, 3000),
            )
        if method == "POST" and path == "/api/versions/compare":
            data = self.read_json()
            before_id = validated_text(data.get("before"), "旧版本编号", 32, 32)
            after_id = validated_text(data.get("after"), "新版本编号", 32, 32)
            before, after = store.get_version(before_id), store.get_version(after_id)
            if not before or not after:
                raise ApiError(404, "版本已不存在，请刷新版本列表。")
            return 200, compare_versions(before, after)
        if version_path and method == "GET":
            version = store.get_version(version_path[1])
            if not version:
                raise ApiError(404, "找不到该简历版本。")
            return 200, version
        if version_path and method == "DELETE":
            if not store.delete_version(version_path[1]):
                raise ApiError(404, "版本已不存在。")
            return 200, {"deleted": True}
        if method == "GET" and path == "/api/tasks":
            return 200, store.tasks()
        if method == "POST" and path == "/api/tasks":
            data = self.read_json()
            title = validated_text(data.get("title"), "计划内容", 1, 200)
            role = validated_text(data.get("role"), "岗位", 1, 40)
            if role not in ROLES:
                raise ApiError(400, "请选择有效岗位。")
            due_date = validated_text(data.get("due_date", ""), "计划日期", 0, 10)
            if due_date:
                try:
                    if date.fromisoformat(due_date).isoformat() != due_date:
                        raise ValueError()
                except ValueError:
                    raise ApiError(400, "日期需使用 YYYY-MM-DD 格式。") from None
            return 201, store.create_task(uuid4().hex, title, role, due_date)
        if task_path and method == "PATCH":
            done = self.read_json().get("done")
            if type(done) is not bool:
                raise ApiError(400, "完成状态必须为布尔值。")
            result = store.update_task(task_path[1], done)
            if not result:
                raise ApiError(404, "计划已不存在。")
            return 200, result
        if task_path and method == "DELETE":
            if not store.delete_task(task_path[1]):
                raise ApiError(404, "计划已不存在。")
            return 200, {"deleted": True}
        if bookmark_path and method == "PATCH":
            data = self.read_json()
            reviewed = data.get("reviewed")
            if type(reviewed) is not bool:
                raise ApiError(400, "复习状态必须为布尔值。")
            answer = validated_text(data.get("review_answer"), "复习回答", 10, 2500) if reviewed else None
            result = store.review_bookmark(bookmark_path[1], reviewed, answer)
            if not result:
                raise ApiError(404, "题目已不存在。")
            return 200, result
        if method == "GET" and path == "/api/bookmarks":
            return 200, store.bookmarks()
        if method == "POST" and path == "/api/bookmarks":
            data = self.read_json()
            role = data.get("role")
            if not isinstance(role, str) or role not in ROLES:
                raise ApiError(400, "请选择有效岗位。")
            question = validated_text(data.get("question"), "题目", 1, 500)
            answer = validated_text(data.get("answer", ""), "回答", 0, 2500)
            note = validated_text(data.get("note", ""), "复习建议", 0, 2000)
            return 201, store.bookmark(uuid4().hex, role, question, answer, note)
        if method == "DELETE" and bookmark_path:
            if store.delete_bookmark(bookmark_path[1]):
                return 200, {"deleted": True}
            raise ApiError(404, "收藏题目已不存在。")
        if method == "GET" and path == "/api/roles":
            return 200, [{"id": key, "label": value["label"]} for key, value in ROLES.items()]
        if method == "GET" and path == "/api/history":
            return 200, store.history()
        if method == "GET" and path == "/api/interviews/config":
            return 200, {"ai_available": deepseek is not None}
        if method == "POST" and path == "/api/resumes/import":
            if self.headers.get_content_type() != "application/pdf":
                raise ApiError(415, "请上传 PDF 文件。")
            length = self.headers.get("Content-Length", "")
            if not length.isascii() or not length.isdecimal() or len(length) > 8:
                raise ApiError(400, "文件长度无效。")
            if not 0 < int(length) <= 5 * 1024 * 1024:
                raise ApiError(413, "PDF 文件不能超过 5 MB。")
            try:
                return 200, extract_pdf(self.rfile.read(int(length)))
            except ResumeFileError as error:
                raise ApiError(400, str(error)) from None
        if record_path and method in {"GET", "DELETE"}:
            record_id = record_path[1]
            if method == "DELETE" and store.delete(record_id):
                return 200, {"deleted": True}
            if method == "GET":
                record = store.get(record_id)
                if record and record["report"] is not None:
                    return 200, record
            raise ApiError(404, "找不到这条记录。")
        if method == "POST" and path in {"/api/resumes", "/api/interviews"}:
            data = self.read_json()
            role = data.get("role")
            if not isinstance(role, str) or role not in ROLES:
                raise ApiError(400, "请选择有效的目标岗位。")
            record_id = uuid4().hex
            if path == "/api/resumes":
                resume = validated_text(data.get("resume"), "简历正文", MIN_RESUME_LENGTH, MAX_RESUME_LENGTH)
                description = validated_text(data.get("description", ""), "岗位描述", 0, 3000)
                use_ai = data.get("use_ai", False)
                if type(use_ai) is not bool:
                    raise ApiError(400, "简历优化模式参数无效。")
                report = resume_report(resume, role, description)
                report["description"] = description
                report["optimization"] = "local"
                if use_ai:
                    report["notice"] = "DeepSeek 优化暂不可用，本次使用本地整理稿与建议。"
                    if deepseek:
                        try:
                            optimized = deepseek.optimize_resume(ROLES[role]["label"], resume, description)
                            report.update(optimized, optimization="deepseek", model=deepseek.model)
                            report["notice"] = "改写稿由 DeepSeek 生成，请逐项核对经历、技能和数据后使用。"
                        except DeepSeekError as error:
                            logging.warning("DeepSeek 简历优化失败，使用本地整理：%s", error)
                store.create(record_id, "resume", role, {"description": description}, report)
                return 201, {"id": record_id, "report": report}
            count = data.get("count")
            if type(count) is not int or count not in (3, 5):
                raise ApiError(400, "面试题数请选择 3 或 5。")
            use_ai = data.get("use_ai", False)
            if type(use_ai) is not bool:
                raise ApiError(400, "面试模式参数无效。")
            difficulty = data.get("difficulty", "standard")
            if not isinstance(difficulty, str) or difficulty not in {"basic", "standard", "advanced"}:
                raise ApiError(400, "请选择有效的面试难度。")
            description = validated_text(data.get("description", ""), "岗位描述", 0, 3000)
            context = validated_text(data.get("context", ""), "个人经历", 0, 4000)
            profile = ROLES[role]
            questions = []
            for category, question, rubric in profile["questions"][:count]:
                if difficulty == "basic":
                    question += " 请先解释基本概念，再举一个简单例子。"
                elif difficulty == "advanced":
                    question += " 请比较两种可行方案，说明约束、失败场景及验证方式。"
                questions.append((category, question, rubric))
            source = "local"
            if use_ai and deepseek:
                try:
                    questions = deepseek.questions(profile["label"], profile["skills"], count,
                                                   difficulty, description, context)
                    source = "deepseek"
                except DeepSeekError as error:
                    logging.warning("DeepSeek 出题失败，使用本地题库：%s", error)
            store.create(record_id, "interview", role, {
                "questions": questions, "question_source": source, "use_ai": use_ai,
                "difficulty": difficulty, "description": description, "context": context,
            })
            return 201, {"id": record_id, "question_source": source, "questions": [
                {"category": category, "text": question} for category, question, _ in questions
            ]}
        if method == "POST" and finish_path:
            return 200, self.finish_interview(finish_path[1])
        raise ApiError(404, "找不到该页面或接口。")

    def finish_interview(self, record_id):
        store = self.server.store
        record = store.get(record_id)
        if not record or record["kind"] != "interview":
            raise ApiError(404, "找不到这场面试。")
        if record["report"] is not None:
            return record["report"]
        payload = record["payload"]
        questions = payload["questions"]
        answers = self.read_json().get("answers")
        if not isinstance(answers, list) or len(answers) != len(questions):
            raise ApiError(400, "请完成全部题目。")
        answers = [validated_text(answer, f"第 {index} 题回答", 10, 2500)
                   for index, answer in enumerate(answers, 1)]
        # 同一场面试的并发提交共享结果，避免重复调用付费接口。
        with interview_finish_lock(record_id):
            current = store.get(record_id)
            if not current:
                raise ApiError(404, "找不到这场面试。")
            if current["report"] is not None:
                return current["report"]
            report = self.evaluate_interview(record["role"], questions, answers, payload.get("use_ai", False))
            report["question_source"] = payload.get("question_source", "local")
            report["difficulty"] = payload.get("difficulty", "standard")
            saved = store.finish(record_id, report)
            if saved is None:
                raise ApiError(404, "找不到这场面试。")
            return saved

    def evaluate_interview(self, role, questions, answers, use_ai):
        deepseek = self.server.deepseek
        if use_ai and deepseek:
            try:
                return deepseek.report(ROLES[role]["label"], questions, answers)
            except DeepSeekError as error:
                logging.warning("DeepSeek 点评失败，使用本地规则：%s", error)
        report = interview_report(questions, answers)
        report["evaluation"] = "local"
        if use_ai:
            report["notice"] = "DeepSeek 点评暂不可用，本次报告使用本地规则评分。"
        return report

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ApiError(415, "请求正文必须使用 application/json。")
        length = self.headers.get("Content-Length", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 6:
            raise ApiError(400, "请求长度无效。")
        if not 0 < int(length) <= 256_000:
            raise ApiError(413, "请求正文超出大小限制。")
        try:
            data = json.loads(self.rfile.read(int(length)).decode("utf-8"))
            # JSON 转义也可能携带单独的 UTF-16 代理字符，SQLite 无法存储。
            json.dumps(data, ensure_ascii=False).encode("utf-8")
        except (ValueError, UnicodeError, RecursionError):
            raise ApiError(400, "请求正文必须是有效的 UTF-8 JSON。") from None
        if not isinstance(data, dict):
            raise ApiError(400, "请求正文必须是 JSON 对象。")
        return data

    def send_bytes(self, status, body, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="启动智能简历优化与模拟面试平台")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "career_lab.sqlite3")
    parser.add_argument("--configure-ai", action="store_true", help="启动时输入 DeepSeek API Key，仅在本次服务进程中使用")
    parser.add_argument("--save-api-key", action="store_true", help="输入并保存 DeepSeek API Key，之后启动自动读取")
    args = parser.parse_args()
    api_key = None
    if args.configure_ai or args.save_api_key:
        try:
            api_key = getpass.getpass("请输入 DeepSeek API Key（输入会隐藏，完成后按回车）: ").strip()
        except (EOFError, KeyboardInterrupt):
            parser.exit(1, "\n已取消启动。\n")
        if not api_key:
            parser.error("API Key 为空，请重新运行并粘贴密钥。")
    try:
        if api_key is None and not os.environ.get("DEEPSEEK_API_KEY", "").strip():
            api_key = read_api_key()
        deepseek = DeepSeekClient.from_env(api_key)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.store = Store(args.db)
        server.deepseek = deepseek
        if args.save_api_key:
            try:
                save_api_key(api_key)
            except OSError:
                parser.error("密钥保存失败，请检查项目目录的写入权限。")
            print("密钥已保存到 .local/deepseek.json。以后运行 python server.py 即可。", flush=True)
        print(f"智能简历优化与模拟面试平台  http://127.0.0.1:{server.server_port}", flush=True)
        print("DeepSeek 配置已读取，首次出题时验证接口连接。" if deepseek
              else "未读取到 DeepSeek API Key。可用 python server.py --save-api-key 输入并保存。", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
