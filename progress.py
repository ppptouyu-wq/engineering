"""简历版本差异与同类训练记录统计。"""

from collections import defaultdict
from difflib import SequenceMatcher
from statistics import mean

from engine import resume_report


def compare_versions(before, after):
    # 两份简历采用右侧版本的岗位及 JD，避免切换评分条件造成虚假的提升。
    role = after["role"]
    description = after["description"]
    before_report = resume_report(before["resume"], role, description)
    after_report = resume_report(after["resume"], role, description)
    before_lines = before["resume"].splitlines()
    after_lines = after["resume"].splitlines()
    matcher = SequenceMatcher(None, before_lines, after_lines, autojunk=False)
    lines = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            lines.extend({"type": " ", "text": line} for line in before_lines[old_start:old_end])
        if tag in {"delete", "replace"}:
            lines.extend({"type": "-", "text": line} for line in before_lines[old_start:old_end])
        if tag in {"insert", "replace"}:
            lines.extend({"type": "+", "text": line} for line in after_lines[new_start:new_end])
    return {
        "role": role, "description": description,
        "before": before, "after": after,
        "before_score": before_report["score"], "after_score": after_report["score"],
        "dimensions": [
            {"label": left["label"], "before": left["score"], "after": right["score"]}
            for left, right in zip(before_report["dimensions"], after_report["dimensions"])
        ],
        "lines": lines,
    }


def training_analytics(records):
    grouped = defaultdict(list)
    for record in records:
        report = record["report"]
        method = report.get("evaluation", "local") if record["kind"] == "interview" else "local"
        difficulty = report.get("difficulty", "standard") if record["kind"] == "interview" else ""
        # 同一正文更换 JD 就会改变规则分，简历趋势必须隔离评分条件。
        description = report.get("description", "") if record["kind"] == "resume" else ""
        grouped[(record["kind"], record["role"], method, difficulty, description)].append(record)
    groups = []
    for (kind, role, method, difficulty, description), items in grouped.items():
        dimensions = defaultdict(list)
        for item in items:
            for dimension in item["report"]["dimensions"]:
                dimensions[dimension["label"]].append(dimension["score"])
        scores = [item["report"]["score"] for item in items]
        groups.append({
            "kind": kind, "role": role, "method": method, "difficulty": difficulty,
            "description": description,
            "count": len(items), "average": round(mean(scores)), "latest": scores[-1],
            "change": scores[-1] - scores[0] if len(scores) > 1 else None,
            "dimensions": [{"label": label, "score": round(mean(values))} for label, values in dimensions.items()],
            "series": [{"id": item["id"], "created_at": item["created_at"], "score": item["report"]["score"]}
                       for item in items[-10:]],
        })
    return {"total": len(records), "groups": groups}
