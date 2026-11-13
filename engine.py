"""可解释的简历诊断和面试评估规则。"""

import re
from statistics import mean

from question_bank import ROLES


SECTIONS = {
    "教育背景": r"教育背景|教育经历|学历|education",
    "项目经历": r"项目经历|项目经验|科研经历|projects",
    "工作/实习经历": r"工作经历|工作经验|实习经历|实习经验|experience",
    "专业技能": r"专业技能|技术栈|技能|skills",
}
ACTION = r"负责|设计|实现|开发|构建|优化|重构|搭建|测试|分析|维护|交付|组织|推进|编写|部署|制定|集成"
METRIC = r"\d+(?:\.\d+)?\s*(?:%|％|ms\b|秒|毫秒|人|条|倍|万|次|个|小时|天|分钟|req/s)"
STOP_TERMS = {"岗位职责", "任职要求", "优先考虑", "工作内容", "能力要求", "加分项"}


def includes(text, term):
    pattern = re.escape(term)
    if term and term[0].isascii() and term[0].isalnum():
        pattern = r"(?<![A-Za-z0-9_])" + pattern
    if term and term[-1].isascii() and term[-1].isalnum():
        pattern += r"(?![A-Za-z0-9_])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def jd_terms(description):
    # 已知技能优先，再从 JD 补充显式条目和可识别的技术名词。
    known = [skill for role in ROLES.values() for skill in role["skills"] if includes(description, skill)]
    explicit = re.split(r"[、，,；;\n|]", description)
    explicit = [term.strip(" -*·。") for term in explicit]
    explicit = [term for term in explicit if re.fullmatch(r"[\u4e00-\u9fff]{2,7}", term) and term not in STOP_TERMS]
    english = re.findall(r"(?<![\w.])[A-Za-z][A-Za-z0-9+#.]{1,24}", description)
    terms = {}
    for term in known + explicit + english:
        if term.lower() in {"and", "or", "the", "with", "for", "job", "description", "must", "have"}:
            continue
        if any(includes(existing, term) for existing in terms.values()):
            continue
        terms.setdefault(term.casefold(), term)
    return list(terms.values())[:12]


def resume_report(resume, role, description):
    profile = ROLES[role]
    terms = jd_terms(description) if description else []
    custom_terms = bool(terms)
    terms = terms or profile["skills"]
    matched = [term for term in terms if includes(resume, term)]
    missing = [term for term in terms if term not in matched]
    lines = [line.strip() for line in resume.splitlines() if line.strip()]
    sections = [
        title for title, pattern in SECTIONS.items()
        if any(re.match(rf"^[#\s*·【\[\d.、-]*(?:{pattern})\s*(?:[：:】\]]|$)", line, re.I) for line in lines)
    ]
    evidence = [line for line in dict.fromkeys(lines) if re.search(ACTION, line)]
    quantified = [line for line in evidence if re.search(METRIC, line, re.I)]
    dimensions = [
        {"label": "岗位匹配", "score": round(100 * len(matched) / len(terms)),
         "detail": f"覆盖 {len(matched)} / {len(terms)} 个{'岗位描述' if custom_terms else '岗位预设'}关键词"},
        {"label": "结构完整", "score": 25 * len(sections),
         "detail": f"识别到 {len(sections)} / {len(SECTIONS)} 个标准章节"},
        {"label": "行动表达", "score": min(100, 25 * len(evidence)),
         "detail": f"{len(evidence)} 个不同的文本行包含行动动词"},
        {"label": "成果量化", "score": min(100, 34 * len(quantified)),
         "detail": f"{len(quantified)} 行同时包含行动和可识别的量化信息"},
    ]
    suggestions = []
    if missing:
        suggestions.append({"title": "补充真实的岗位证据",
                            "detail": f"可核对 { '、'.join(missing[:5]) }。如果确有相关经历，在对应项目中写明你的做法与产出。"})
    absent = [name for name in SECTIONS if name not in sections]
    if absent:
        suggestions.append({"title": "整理简历章节",
                            "detail": f"检查是否需要添加或改名为 { '、'.join(absent) }。标题单独占一行，便于识别。"})
    if len(evidence) < 4:
        suggestions.append({"title": "说清楚你做了什么", "detail": "从真实经历中挑选关键任务，用设计、实现或优化等动词写清个人贡献。"})
    if len(quantified) < 3:
        suggestions.append({"title": "补充可以核实的成果", "detail": "为关键经历补充有来源的耗时、处理规模或测试数据。也可写明实际交付物或验收结果。"})
    if not suggestions:
        suggestions.append({"title": "优先呈现代表项目", "detail": "把与目标岗位最相关的经历排在前面，并核对数字、时间和技术名称。"})
    return {
        "score": round(sum(item["score"] * weight for item, weight in zip(dimensions, (0.4, 0.2, 0.2, 0.2)))),
        "dimensions": dimensions, "matched": matched, "missing": missing, "suggestions": suggestions,
        "draft": rewrite_draft(lines),
    }


def rewrite_draft(lines):
    cleaned = []
    for line in lines:
        action = re.match(r"^(?:[-*•·]\s*)?(?:本人\s*|我\s*)?(?=" + ACTION + r")", line)
        if action:
            line = "- " + line[action.end():]
        cleaned.append(line)
    return "\n".join(cleaned)


def interview_report(questions, answers):
    feedback = []
    for (category, question, rubric), answer in zip(questions, answers):
        hits = [any(includes(answer, cue) for cue in cues) for _, cues in rubric]
        coverage = round(100 * sum(hits) / len(hits))
        length = len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", answer))
        detail = min(100, round(100 * length / 85))
        has_evidence = bool(re.search(METRIC, answer, re.I)
                            or re.search(r"日志|对照组|执行计划|测试用例|压测|验收|复盘|实验", answer))
        evidence = 100 if has_evidence else 0
        feedback.append({
            "category": category, "question": question, "answer": answer,
            "score": round(0.6 * coverage + 0.25 * detail + 0.15 * evidence),
            "coverage": coverage, "detail": detail, "evidence": evidence,
            "rubric": [{"label": criterion, "covered": hit} for (criterion, _), hit in zip(rubric, hits)],
        })
    return {
        "score": round(mean(item["score"] for item in feedback)),
        "dimensions": [
            {"label": label, "score": round(mean(item[key] for item in feedback)), "detail": description}
            for label, key, description in (
                ("要点覆盖", "coverage", "逐题检查三个回答角度的关键词"),
                ("展开程度", "detail", "根据回答中的汉字和英文词数量估算"),
                ("证据表达", "evidence", "检查量化信息或验证方式"),
            )
        ],
        "feedback": feedback,
    }
