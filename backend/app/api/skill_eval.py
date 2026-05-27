"""Skill Evaluation API — 技能评估与优化"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core import get_db
from app.models import AIModelConfig, User
from app.models import Skill as DBSkill
from app.models.models import SkillEvalResult as DBSkillEvalResult
from app.models.models import SkillScope
from app.modules.agent.skills import get_skills_loader
from app.modules.llm.provider import SimpleLLMProvider
from app.services.skill_eval.benchmark_runner import BenchmarkRunner
from app.services.skill_eval.llm_evaluator import LLMEvaluator
from app.services.skill_eval.quick_validate import validate_skill as _quick_validate
from app.services.skill_eval.redflag_scanner import RedFlagScanner
from app.services.skill_eval.skill_optimizer import OptimizeRequest, SkillOptimizer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skill-eval", tags=["技能评估"])


class FileEntry(BaseModel):
    name: str
    path: str
    type: str  # "file" | "dir"
    size: int = 0
    children: Optional[list["FileEntry"]] = None


class SkillInfo(BaseModel):
    id: Optional[int] = None
    name: str
    display_name: str = ""
    description: str = ""
    source: str = ""  # "db" | "file"
    scope: str = ""
    enabled: bool = True
    skill_format: str = "inline"


BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".exe", ".dll", ".so", ".pyd", ".dylib",
    ".db", ".sqlite", ".sqlite3",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    ".bin", ".dat", ".pickle", ".pkl", ".pth",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
}


def _is_text_file(path: Path) -> bool:
    """判断是否为文本文件（排除二进制）"""
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return False
    # 无后缀或已知文本后缀直接放行
    text_extensions = {".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".vue",
                       ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
                       ".html", ".css", ".scss", ".less", ".xml", ".svg",
                       ".sh", ".bat", ".ps1", ".txt", ".rst", ".csv",
                       ".sql", ".go", ".rs", ".java", ".c", ".cpp", ".h",
                       ".rb", ".php", ".swift", ".kt", ".scala"}
    if path.suffix.lower() in text_extensions:
        return True
    # 无后缀或无明确类型：尝试读前 256 字节判断
    try:
        with open(path, "rb") as f:
            chunk = f.read(256)
        return b"\x00" not in chunk  # 二进制文件通常含空字节
    except (OSError, PermissionError):
        return False


def _walk_dir(root: Path, base: Path) -> list[FileEntry]:
    """递归遍历目录，返回文件树"""
    entries: list[FileEntry] = []
    try:
        items = sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except (OSError, PermissionError):
        return entries

    for item in items:
        if item.is_dir():
            rel = str(item.relative_to(base)).replace("\\", "/")
            entries.append(FileEntry(
                name=item.name,
                path=rel,
                type="dir",
                children=_walk_dir(item, base),
            ))
        elif _is_text_file(item):
            rel = str(item.relative_to(base)).replace("\\", "/")
            entries.append(FileEntry(
                name=item.name,
                path=rel,
                type="file",
                size=item.stat().st_size,
            ))
    return entries


@router.get("/skills", response_model=list[SkillInfo])
async def list_eval_skills(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """列出所有技能（DB + 文件系统），供评估页使用"""
    skills: list[SkillInfo] = []
    seen: set[str] = set()

    # 1. DB 技能
    conditions = [DBSkill.scope == SkillScope.SYSTEM.value]
    if current_user.organization_id:
        conditions.append(DBSkill.scope == SkillScope.ORG.value)
    conditions.append(
        (DBSkill.scope == SkillScope.USER.value) & (DBSkill.creator_id == current_user.id)
    )
    result = await db.execute(
        select(DBSkill).where(or_(*conditions)).order_by(DBSkill.name)
    )
    for s in result.scalars().all():
        skills.append(SkillInfo(
            id=s.id,
            name=s.name,
            display_name=s.display_name or s.name,
            description=s.description or "",
            source="db",
            scope=s.scope,
            enabled=s.is_active,
            skill_format=s.skill_format or "inline",
        ))
        seen.add(s.name)

    # 2. 文件系统技能（仅 workspace 用户技能，排除 builtin 和 openclaw）
    try:
        loader = get_skills_loader()
        for name, skill in loader.skills.items():
            if name in seen:
                continue
            if skill.source in ("openclaw", "builtin"):
                continue  # 不引入外部技能和内置技能
            skills.append(SkillInfo(
                name=name,
                display_name=skill.metadata.title or name,
                description=skill.metadata.description or "",
                source="file",
                scope="system",  # center 端 skills/ 即为系统级
                enabled=skill.enabled,
            ))
    except Exception:
        pass

    return skills


@router.get("/skills/{skill_name}/tree")
async def get_skill_tree(
    skill_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取技能的文件树和内容"""
    # 先尝试文件系统
    loader = get_skills_loader()
    if skill_name in loader.skills:
        skill = loader.skills[skill_name]
        skill_dir = skill.path.parent  # SKILL.md 所在目录
        tree = _walk_dir(skill_dir, skill_dir)
        return {
            "skill_name": skill_name,
            "display_name": skill.metadata.title or skill_name,
            "source": "file",
            "skill_dir": str(skill_dir),
            "tree": [FileEntry(
                name="SKILL.md",
                path="SKILL.md",
                type="file",
                size=skill.path.stat().st_size if skill.path.exists() else 0,
            )] + [f for f in tree if f.name != "SKILL.md"],
        }

    # 再尝试 DB
    conditions = [DBSkill.name == skill_name]
    result = await db.execute(select(DBSkill).where(or_(*conditions)))
    db_skill = result.scalar_one_or_none()

    if not db_skill:
        raise HTTPException(status_code=404, detail=f"技能 '{skill_name}' 不存在")

    # DB 技能只有 content 字段，虚拟为单个 SKILL.md 文件
    return {
        "skill_name": skill_name,
        "display_name": db_skill.display_name or skill_name,
        "source": "db",
        "skill_id": db_skill.id,
        "skill_dir": None,
        "tree": [
            FileEntry(name="SKILL.md", path="SKILL.md", type="file",
                      size=len(db_skill.content.encode()) if db_skill.content else 0),
        ],
        "content": db_skill.content or "",
    }


@router.get("/skills/{skill_name}/file")
async def get_skill_file(
    skill_name: str,
    path: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """读取技能目录下的某个文件内容"""
    loader = get_skills_loader()

    if skill_name in loader.skills:
        skill = loader.skills[skill_name]
        skill_dir = skill.path.parent

        # 安全检查：防止路径遍历
        target = (skill_dir / path).resolve()
        if not str(target).startswith(str(skill_dir.resolve())):
            raise HTTPException(status_code=403, detail="路径越权")

        if not target.exists():
            raise HTTPException(status_code=404, detail="文件不存在")

        if target.is_dir():
            raise HTTPException(status_code=400, detail="不能读取目录")

        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "path": path or "SKILL.md",
            "content": content,
            "size": target.stat().st_size,
        }

    # DB 技能
    conditions = [DBSkill.name == skill_name]
    result = await db.execute(select(DBSkill).where(or_(*conditions)))
    db_skill = result.scalar_one_or_none()

    if not db_skill:
        raise HTTPException(status_code=404, detail=f"技能 '{skill_name}' 不存在")

    return {
        "path": "SKILL.md",
        "content": db_skill.content or "",
        "size": len(db_skill.content.encode()) if db_skill.content else 0,
    }


# ---------------------------------------------------------------------------
# Evaluate schemas
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    content: str  # SKILL.md 全文
    safety_score: int = 0   # 用于 /evaluate-llm 计算 overall_score
    structure_score: int = 0


class RuleResultOut(BaseModel):
    rule_id: str         # "RF01"
    description: str     # "curl/wget 管道到 shell"
    severity: str        # "CRITICAL" | "HIGH"
    passed: bool         # True = 未命中
    line: int = 0        # 命中行号
    snippet: str = ""    # 命中片段


class StructureCheckOut(BaseModel):
    check: str           # e.g. "description 含 WHAT+WHEN"
    passed: bool
    score: int = 0      # 得分
    max_score: int = 0  # 满分
    detail: str          # 通过/失败原因


class PlaceholderDimOut(BaseModel):
    key: str
    label: str
    icon: str


class EvaluateResponse(BaseModel):
    overall_score: int
    summary: str
    safety_score: int
    safety_hits: int                          # 命中数
    safety_rules: list[RuleResultOut]          # 14 条逐项
    structure_score: int
    structure_checks: list[StructureCheckOut]  # 逐项校验
    placeholder_dims: list[PlaceholderDimOut]  # 6 个占位维度
    suggestions: list[dict] = []
    optimized_content: str = ""
    llm_pending: bool = False


# ---------------------------------------------------------------------------
# POST /evaluate
# ---------------------------------------------------------------------------

PLACEHOLDER_DIMS = [
    PlaceholderDimOut(key="clarity", label="清晰度", icon="💡"),
    PlaceholderDimOut(key="completeness", label="完整性", icon="📋"),
    PlaceholderDimOut(key="conciseness", label="简洁度", icon="✂️"),
    PlaceholderDimOut(key="trigger_specificity", label="触发精准", icon="🎯"),
    PlaceholderDimOut(key="dependencies", label="依赖声明", icon="🔗"),
    PlaceholderDimOut(key="config", label="配置合理性", icon="⚙️"),
]


def _parse_skill_md(skill_dir: Path):
    """读取 SKILL.md，返回 (content, frontmatter_dict, body_text) 或 None"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception:
        return None

    fm: dict = {}
    body = content
    if content.startswith("---"):
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if match:
            try:
                parsed = yaml.safe_load(match.group(1))
                if isinstance(parsed, dict):
                    fm = parsed
            except Exception:
                pass
            body = content[match.end():]

    return content, fm, body


# 模糊 name 词（来自 SkillScore）
_VAGUE_NAMES = frozenset({
    "helper", "utils", "tools", "misc", "stuff", "things", "tmp", "test",
})
_RESERVED_WORDS = frozenset({"anthropic", "claude"})

# WHAT 动作动词
_WHAT_VERBS = re.compile(
    r"\b(creates?|generates?|analy[sz]es?|evaluates?|deploys?|monitors?|"
    r"validates?|formats?|converts?|transforms?|checks?|builds?|tests?|"
    r"integrates?|processes?|parses?|searches?|automates?|extracts?|"
    r"optimizes?|reviews?|tracks?|manages?|edits?|designs?|scans?|"
    r"创建|生成|分析|评估|部署|监控|验证|格式化|转换|检查|构建|测试|"
    r"集成|处理|解析|搜索|自动化|提取|优化|审查|跟踪|管理|编辑|设计|扫描)\b",
    re.IGNORECASE,
)

# WHEN 触发信号词
_WHEN_SIGNALS = re.compile(
    r"\b(when|if|trigger|upon|after|before|during)\b|"
    r"use\s+when|use\s+this\s+when|triggered\s+(?:when|by)|"
    r"激活|触发|需要.*时|当.*时",
    re.IGNORECASE,
)

# 负面路由
_NEGATIVE_ROUTE = re.compile(
    r"don'?t\s+use|do\s+not\s+use|not\s+for|don'?t\s+call|"
    r"instead\s+use|not\s+when|when\s+not\s+to|avoid\s+using|"
    r"不该用|不要用|不适合|应改用|不应使用|避免使用",
    re.IGNORECASE,
)


def _mk_check(check: str, passed: bool, score: int, max_score: int, detail: str) -> StructureCheckOut:
    return StructureCheckOut(check=check, passed=passed, score=score if passed else 0, max_score=max_score, detail=detail)


def _run_structure_checks(skill_dir: Path | None) -> tuple[int, list[StructureCheckOut]]:
    """10 项静态检查（来自 static-checks.md），满分 100。"""
    checks: list[StructureCheckOut] = []

    if skill_dir is None:
        return 0, [StructureCheckOut(check="技能目录", passed=False, score=0, max_score=100, detail="无法定位技能目录")]

    parsed = _parse_skill_md(skill_dir)
    if parsed is None:
        return 0, [StructureCheckOut(check="SKILL.md", passed=False, score=0, max_score=100, detail="无法读取 SKILL.md")]

    content, fm, body_text = parsed
    body_lines = [ln for ln in body_text.split("\n") if ln.strip()]
    body_line_count = len(body_lines)

    name_val = fm.get("name", "")
    if not isinstance(name_val, str):
        name_val = ""
    name_val = name_val.strip()

    desc_val = fm.get("description", "")
    if not isinstance(desc_val, str):
        desc_val = ""
    desc_val = desc_val.strip()

    # ── Check 1: SKILL.md 存在（5 分）──
    checks.append(_mk_check("SKILL.md 存在", True, 5, 5, "通过"))

    # ── Check 2: body ≤ 500 行（5 分）──
    if body_line_count <= 500:
        checks.append(_mk_check("body ≤ 500 行", True, 5, 5, f"{body_line_count} 行"))
    elif body_line_count <= 750:
        checks.append(_mk_check("body ≤ 500 行", False, 0, 5, f"{body_line_count} 行（建议拆分）"))
    else:
        checks.append(_mk_check("body ≤ 500 行", False, 0, 5, f"{body_line_count} 行（必须拆分）"))

    # ── Check 3: name（10 分）──
    name_score = 0
    name_details: list[str] = []
    if not name_val:
        name_details.append("缺失")
    else:
        # (a) 存在且非空
        name_details.append("✓ 存在")
        # (b) lowercase-hyphen
        if re.match(r"^[a-z0-9][a-z0-9-]*$", name_val):
            name_details.append("✓ 格式")
        else:
            name_details.append(f"✗ 格式: {name_val}")
        # (c) ≤64
        if len(name_val) <= 64:
            name_details.append("✓ ≤64")
        else:
            name_details.append(f"✗ 超长({len(name_val)}字符)")
        # (d) 不模糊
        is_vague = name_val.lower() in _VAGUE_NAMES or any(
            name_val.lower().endswith(f"-{v}") for v in _VAGUE_NAMES
        )
        if not is_vague:
            name_details.append("✓ 不模糊")
        else:
            name_details.append("✗ 模糊词")
        # (e) 不含保留词
        if not any(r in name_val.lower() for r in _RESERVED_WORDS):
            name_details.append("✓ 无保留词")
        else:
            name_details.append("✗ 含保留词")

    # 计分：5 项全满 = 10，缺一项扣 2（但缺 (a) 是 0）
    if not name_val:
        name_score = 0
    else:
        sub_ok = sum(1 for d in name_details if d.startswith("✓"))
        name_score = min(10, sub_ok * 2)  # 5 项各 2 分 = 10

    checks.append(_mk_check("name", name_score == 10, name_score, 10, "; ".join(name_details)))

    # ── Check 4: description 存在 + ≤1024（10 分）──
    if not desc_val:
        checks.append(_mk_check("description 存在且 ≤1024", False, 0, 10, "缺失"))
    elif len(desc_val) > 1024:
        checks.append(_mk_check("description 存在且 ≤1024", False, 0, 10, f"超长: {len(desc_val)}/1024"))
    else:
        checks.append(_mk_check("description 存在且 ≤1024", True, 10, 10, f"✓ ({len(desc_val)}字符)"))

    # ── Check 5: description 含 WHAT + WHEN（20 分）──
    has_what = bool(_WHAT_VERBS.search(desc_val))
    has_when = bool(_WHEN_SIGNALS.search(desc_val))
    if has_what and has_when:
        checks.append(_mk_check("description 含 WHAT+WHEN", True, 20, 20, "WHAT ✓ · WHEN ✓"))
    elif has_what:
        checks.append(_mk_check("description 含 WHAT+WHEN", False, 0, 20, "缺 WHEN（触发时机）"))
    elif has_when:
        checks.append(_mk_check("description 含 WHAT+WHEN", False, 0, 20, "缺 WHAT（做什么）"))
    else:
        checks.append(_mk_check("description 含 WHAT+WHEN", False, 0, 20, "缺 WHAT+WHEN"))

    # ── Check 6: 有工作流步骤（15 分）──
    has_numbered = bool(re.search(r"(?:^\d+\.\s|第[一二三四五六七八九十\d]+步|Step\s*\d+|STEP\s*\d+)", body_text, re.MULTILINE | re.IGNORECASE))
    has_checklist = bool(re.search(r"^- \[[ x]\]", body_text, re.MULTILINE))
    if has_numbered or has_checklist:
        kind = "编号步骤" if has_numbered else "checklist"
        checks.append(_mk_check("有工作流步骤", True, 15, 15, f"{kind} ✓"))
    else:
        checks.append(_mk_check("有工作流步骤", False, 0, 15, "缺编号步骤或 checklist"))

    # ── Check 7: 有示例（15 分）──
    code_blocks = len(re.findall(r"```", body_text)) // 2
    has_example_label = bool(re.search(r"Input:|Output:|输入|输出|示例|Example", body_text, re.IGNORECASE))
    if code_blocks >= 1 or has_example_label:
        detail_parts = []
        if code_blocks >= 1:
            detail_parts.append(f"{code_blocks} 个代码块")
        if has_example_label:
            detail_parts.append("示例标记 ✓")
        checks.append(_mk_check("有示例", True, 15, 15, "; ".join(detail_parts)))
    else:
        checks.append(_mk_check("有示例", False, 0, 15, "缺代码块和示例"))

    # ── Check 8: 有负面路由（10 分）──
    has_negative = bool(_NEGATIVE_ROUTE.search(body_text))
    if has_negative:
        checks.append(_mk_check("有负面路由", True, 10, 10, "✓"))
    else:
        checks.append(_mk_check("有负面路由", False, 0, 10, "缺（near-miss 可能误触发）"))

    # ── Check 9: 无硬编码绝对路径（5 分）──
    # 排除 URL 和 API 路径
    hits: list[str] = []
    for m in re.finditer(
        r"[A-Za-z]:\\[^\s]*|\\\\[a-zA-Z][^\s]*|/(?:home|Users|usr|opt|etc|var|tmp|bin|sbin)/[^\s]*",
        body_text, re.IGNORECASE,
    ):
        p = m.group()
        if not p.startswith("http") and "/api/" not in p:
            hits.append(p)
    if not hits:
        checks.append(_mk_check("无硬编码绝对路径", True, 5, 5, "✓"))
    else:
        checks.append(_mk_check("无硬编码绝对路径", False, 0, 5, hits[0][:60]))

    # ── Check 10: 无时间敏感信息（5 分）──
    time_sensitive = re.search(
        r"as of (january|february|march|april|may|june|july|august|"
        r"september|october|november|december|\d{4})|"
        r"\b20\d{2}-\d{2}-\d{2}\b|"
        r"pinned to version|current version is|latest version",
        body_text, re.IGNORECASE,
    )
    if not time_sensitive:
        checks.append(_mk_check("无时间敏感信息", True, 5, 5, "✓"))
    else:
        checks.append(_mk_check("无时间敏感信息", False, 0, 5, time_sensitive.group()[:50]))

    # ── Check 11-16: frontmatter 规范验证（来自 skill-creator）──
    if skill_dir is not None:
        try:
            qv_passed, qv_msg, qv_checks = _quick_validate(skill_dir)
            for qc in qv_checks:
                checks.append(StructureCheckOut(
                    check=qc["check"],
                    passed=qc["passed"],
                    score=qc["score"],
                    max_score=qc["max_score"],
                    detail=qc["detail"],
                ))
        except Exception as e:
            checks.append(StructureCheckOut(
                check="frontmatter 规范验证",
                passed=False, score=0, max_score=5,
                detail=f"验证异常: {e}",
            ))

    # 总分归一化到 0-100
    total_score = sum(c.score for c in checks)
    total_max = sum(c.max_score for c in checks)
    normalized = round(total_score / total_max * 100) if total_max > 0 else 0
    return normalized, checks


@router.post("/skills/{skill_name}/evaluate", response_model=EvaluateResponse)
async def evaluate_skill(
    skill_name: str,
    request: EvaluateRequest,
    current_user: User = Depends(get_current_active_user),
):
    """评估技能：安全红线扫描(14项逐条) + 结构校验(逐项)"""

    # 1. 安全红线 — 逐条检测
    scanner = RedFlagScanner()
    safety_rules = scanner.scan_detail(request.content)
    safety_hits = sum(1 for r in safety_rules if not r.passed)
    critical_hits = sum(1 for r in safety_rules if not r.passed and r.severity == "CRITICAL")

    if critical_hits > 0:
        safety_score = 0
    else:
        safety_score = max(0, 100 - safety_hits * 15)

    # 2. 结构校验 — 逐项检测
    try:
        loader = get_skills_loader()
    except Exception:
        loader = None

    skill_dir = None
    if loader and skill_name in loader.skills:
        skill_dir = loader.skills[skill_name].path.parent

    structure_score, structure_checks = _run_structure_checks(skill_dir)

    # 3. 综合分
    valid_scores = [s for s in (safety_score, structure_score) if s > 0]
    overall = sum(valid_scores) // len(valid_scores) if valid_scores else 0

    # 生成自然语言摘要
    summary_parts: list[str] = []

    # 安全部分
    if safety_hits == 0:
        summary_parts.append("安全性检测全部通过，未命中任何安全红线")
    else:
        critical_rules = [r for r in safety_rules if not r.passed and r.severity == "CRITICAL"]
        high_rules = [r for r in safety_rules if not r.passed and r.severity == "HIGH"]
        if critical_rules:
            names = "、".join(r.description for r in critical_rules[:3])
            summary_parts.append(f"存在严重安全风险：{names}等{len(critical_rules)}条致命红线命中")
        if high_rules:
            names = "、".join(r.description for r in high_rules[:2])
            summary_parts.append(f"{names}等{len(high_rules)}条高危红线命中")

    # 结构部分
    failed_checks = [c for c in structure_checks if not c.passed]
    if not failed_checks:
        summary_parts.append("结构规范检查全部通过")
    else:
        names = "、".join(c.check for c in failed_checks[:3])
        summary_parts.append(f"结构方面{names}不合规")

    if not summary_parts:
        summary_parts.append("该技能通过所有基础检查")

    return EvaluateResponse(
        overall_score=overall,
        summary="；".join(summary_parts) + "。其余维度待深度评测。",
        safety_score=safety_score,
        safety_hits=safety_hits,
        safety_rules=[RuleResultOut(
            rule_id=r.rule_id, description=r.description,
            severity=r.severity, passed=r.passed,
            line=r.line, snippet=r.snippet,
        ) for r in safety_rules],
        structure_score=structure_score,
        structure_checks=structure_checks,
        placeholder_dims=list(PLACEHOLDER_DIMS),
        suggestions=[],
        optimized_content=request.content,
        llm_pending=True,
    )


# ── Helpers ────────────────────────────────────────────────────────────────

async def _get_llm_provider(db: AsyncSession, model_config_id: Optional[int] = None) -> Optional[SimpleLLMProvider]:
    """Get LLM provider from DB config. Returns None if no config found."""
    config = None
    if model_config_id:
        result = await db.execute(select(AIModelConfig).where(AIModelConfig.id == model_config_id))
        config = result.scalar_one_or_none()
    else:
        for where in [
            (AIModelConfig.is_active, AIModelConfig.is_default),
            (AIModelConfig.is_active,),
            (AIModelConfig.is_default,),
        ]:
            if config:
                break
            result = await db.execute(select(AIModelConfig).where(*where).limit(1))
            config = result.scalar_one_or_none()
        if not config:
            result = await db.execute(select(AIModelConfig).limit(1))
            config = result.scalar_one_or_none()
    if config:
        return SimpleLLMProvider(config=config)
    return None


# ── Additional schemas ─────────────────────────────────────────────────────

class LlmDimensionOut(BaseModel):
    key: str
    label: str
    score: int
    comment: str


class LlmEvaluateResponse(BaseModel):
    dimensions: list[LlmDimensionOut]
    suggestions: list[dict]
    summary: str
    overall_delta: int = 0
    overall_score: int = 0  # 后端统一计算的 7 维加权总分
    raw_response: str = ""   # LLM 原始响应，用于调试


class OptimizeRequestIn(BaseModel):
    content: str
    suggestions: list[dict] = []
    target_dimensions: list[str] | None = None
    benchmark: dict | None = None


class BenchmarkRequestIn(BaseModel):
    test_prompts: list = []  # list[str] or list[dict] with prompt+expected


class RubricScoreOut(BaseModel):
    content: float = 0.0
    structure: float = 0.0
    overall: float = 0.0


class BenchmarkRunOut(BaseModel):
    prompt: str
    with_skill_output: str = ""
    baseline_output: str = ""
    passed: bool = False
    reasoning: str = ""
    rubric: RubricScoreOut = RubricScoreOut()


class BenchmarkOut(BaseModel):
    pass_rate: float = 0.0
    delta: str = ""
    runs: list[BenchmarkRunOut] = []
    summary: str = ""
    score: int = 0
    avg_rubric: RubricScoreOut = RubricScoreOut()


@router.post("/skills/{skill_name}/evaluate-llm")
async def evaluate_llm(
    skill_name: str,
    request: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """LLM 深度评估：5 维主观评分（异步调用，耗时较长）"""
    MAX_CONTENT_LEN = 50 * 1024  # 50KB
    if len(request.content) > MAX_CONTENT_LEN:
        raise HTTPException(
            status_code=413,
            detail=f"SKILL.md 内容过长（{len(request.content)} 字节），上限 {MAX_CONTENT_LEN} 字节，请精简后重试",
        )
    provider = await _get_llm_provider(db)
    if not provider:
        raise HTTPException(status_code=503, detail="LLM 服务不可用")

    evaluator = LLMEvaluator(provider)
    try:
        llm_result = await evaluator.evaluate(request.content)
    except Exception as e:
        logger.error(f"LLM evaluation exception: {e}")
        raise HTTPException(status_code=500, detail="LLM 评估执行失败")

    dim_labels = {
        "clarity": "清晰度",
        "completeness": "完整性",
        "conciseness": "简洁度",
        "trigger": "触发精准",
        "dependencies": "依赖声明",
    }

    dimensions = [
        LlmDimensionOut(key=d.key, label=dim_labels.get(d.key, d.key), score=d.score, comment=d.comment)
        for d in llm_result.dimensions
    ]

    suggestions = [
        {"title": s.title, "detail": s.detail, "severity": s.severity,
         "category": s.category, "impact": s.impact}
        for s in llm_result.suggestions
    ]

    # 加权计算 LLM 部分得分 (总权重 55%)
    weights = {
        "clarity": 0.15,
        "completeness": 0.12,
        "conciseness": 0.08,
        "trigger": 0.15,
        "dependencies": 0.05,
    }
    llm_weighted_score = sum(d.score * weights.get(d.key, 0) for d in llm_result.dimensions)
    overall_delta = int(llm_weighted_score)

    # 统一计算 overall_score（7 维加权）
    safety = request.safety_score * 0.20
    structure = request.structure_score * 0.10
    total_weight = 0.55 + (0.20 if request.safety_score > 0 else 0) + (0.10 if request.structure_score > 0 else 0)
    overall_score = overall_delta
    if total_weight > 0:
        overall_score = min(100, round((safety + structure + llm_weighted_score) / total_weight))

    return {
        "dimensions": [d.model_dump() for d in dimensions],
        "suggestions": suggestions,
        "summary": llm_result.summary,
        "overall_delta": overall_delta,
        "overall_score": overall_score,
        "raw_response": (llm_result.raw_response[:500] if llm_result.raw_response else ""),
    }


@router.post("/skills/{skill_name}/optimize")
async def optimize_skill(
    skill_name: str,
    request: OptimizeRequestIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """根据评估建议优化 SKILL.md"""
    provider = await _get_llm_provider(db)
    if not provider:
        raise HTTPException(status_code=503, detail="LLM 服务不可用，无法优化")

    optimizer = SkillOptimizer(provider)
    opt_request = OptimizeRequest(
        content=request.content,
        suggestions=request.suggestions,
        target_dimensions=request.target_dimensions,
        benchmark_context=request.benchmark,
    )
    try:
        optimized = await optimizer.optimize(opt_request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化失败: {e}")

    return {"optimized_content": optimized}


@router.post("/skills/{skill_name}/benchmark")
async def benchmark_skill(
    skill_name: str,
    request: BenchmarkRequestIn,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """实测：with/without skill 对比"""
    if not request.test_prompts:
        raise HTTPException(status_code=400, detail="test_prompts 不能为空")

    provider = await _get_llm_provider(db)
    if not provider:
        raise HTTPException(status_code=503, detail="没有可用的 AI 模型配置，无法实测。请在 AI 管理页面添加模型配置")

    # 获取 SKILL.md 内容
    loader = get_skills_loader()
    content = ""
    if skill_name in loader.skills:
        content = loader.skills[skill_name].path.read_text(encoding="utf-8")
    else:
        result = await db.execute(select(DBSkill).where(DBSkill.name == skill_name))
        db_skill = result.scalar_one_or_none()
        if db_skill:
            content = db_skill.content or ""
    if not content:
        raise HTTPException(status_code=404, detail=f"技能 '{skill_name}' 内容为空")

    # Pass auth token for internal subagent API calls
    auth_header = req.headers.get("Authorization", "")
    runner = BenchmarkRunner(provider, auth_token=auth_header.replace("Bearer ", ""))
    dict_prompts = [{"prompt": p, "expected": ""} for p in request.test_prompts]
    # If test_prompts are dicts with expected, use those
    if request.test_prompts and isinstance(request.test_prompts[0], dict):
        dict_prompts = request.test_prompts
    try:
        result = await runner.run(content, dict_prompts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"实测执行失败: {e}")

    return {
        "pass_rate": result.pass_rate,
        "delta": result.delta,
        "score": result.score,
        "summary": result.summary,
        "avg_rubric": {
            "content": result.avg_rubric.content,
            "structure": result.avg_rubric.structure,
            "overall": result.avg_rubric.overall,
        },
        "assertion_summary": {
            "total": result.assertion_total,
            "with_skill_passed": result.assertion_with_passed,
            "baseline_passed": result.assertion_baseline_passed,
        },
        "stats": result.stats,
        "runs": [
            {
                "prompt": r.prompt,
                "with_skill_output": r.with_skill_output,
                "baseline_output": r.baseline_output,
                "passed": r.passed,
                "reasoning": r.reasoning,
                "rubric": {
                    "content": r.rubric.content,
                    "structure": r.rubric.structure,
                    "overall": r.rubric.overall,
                },
                "with_skill_assertions": r.with_skill_assertions,
                "baseline_assertions": r.baseline_assertions,
                "with_skill_time": r.with_skill_time,
                "baseline_time": r.baseline_time,
                "with_skill_tokens": r.with_skill_tokens,
                "baseline_tokens": r.baseline_tokens,
            }
            for r in result.runs
        ],
    }


@router.post("/skills/{skill_name}/benchmark-stream")
async def benchmark_skill_stream(
    skill_name: str,
    request: BenchmarkRequestIn,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Stream benchmark results via SSE as each prompt pair completes.

    Yields progress events, result events, and a final summary event.
    """
    if not request.test_prompts:
        raise HTTPException(status_code=400, detail="test_prompts 不能为空")

    provider = await _get_llm_provider(db)
    if not provider:
        raise HTTPException(status_code=503, detail="没有可用的 AI 模型配置，无法实测。请在 AI 管理页面添加模型配置")

    # Get SKILL.md content
    loader = get_skills_loader()
    content = ""
    if skill_name in loader.skills:
        content = loader.skills[skill_name].path.read_text(encoding="utf-8")
    else:
        result = await db.execute(select(DBSkill).where(DBSkill.name == skill_name))
        db_skill = result.scalar_one_or_none()
        if db_skill:
            content = db_skill.content or ""
    if not content:
        raise HTTPException(status_code=404, detail=f"技能 '{skill_name}' 内容为空")

    # Pass auth token for internal subagent API calls
    auth_header = req.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "")
    runner = BenchmarkRunner(provider, auth_token=token)

    dict_prompts = [{"prompt": p, "expected": ""} for p in request.test_prompts]
    # If test_prompts are dicts with expected, use those
    if request.test_prompts and isinstance(request.test_prompts[0], dict):
        dict_prompts = request.test_prompts

    return StreamingResponse(
        runner.run_stream(content, dict_prompts),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /skills/{skill_name}/report
# ---------------------------------------------------------------------------

@router.get("/skills/{skill_name}/report")
async def get_skill_report(
    skill_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """生成评估报告 HTML"""
    import tempfile

    content = ""
    loader = get_skills_loader()
    if skill_name in loader.skills:
        sk = loader.skills[skill_name]
        if sk.path.exists():
            content = sk.path.read_text(encoding="utf-8")

    # Run a quick static evaluation to get data
    scanner = RedFlagScanner()
    redflag = scanner.scan_detail(content)

    redflag_hits = []
    failed = 0
    for r in redflag:
        redflag_hits.append({
            "rule_id": r.rule_id, "severity": r.severity,
            "description": r.description, "passed": r.passed,
            "line": r.line, "snippet": r.snippet,
        })
        if not r.passed:
            failed += 1

    # Structure checks
    with tempfile.TemporaryDirectory() as td:
        sf = Path(td) / "SKILL.md"
        sf.write_text(content, encoding="utf-8")
        _, _, checks = _quick_validate(Path(td))

    safety_score = max(0, 100 - failed * 15)
    struct_passed = sum(1 for c in checks if c["passed"])
    struct_score = int(struct_passed / len(checks) * 100) if checks else 0

    overall = int(struct_score * 0.4 + safety_score * 0.6)
    import html as _html

    parts = [f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Skill 评估报告 - {_html.escape(skill_name)}</title>
<style>
:root{{--bg:#0a0e1a;--surface:#161b2e;--border:#2a2a4a;--primary:#00d4ff;--text:#e8eaf0;--muted:#7a7e92;--green:#00e5a0;--red:#ff4d6a;--amber:#ff8c42;--radius:10px}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);max-width:800px;margin:0 auto;padding:24px 20px;line-height:1.6}}
h1{{font-size:1.4em;margin-bottom:4px}}h2{{font-size:1em;margin:24px 0 12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;margin-bottom:12px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75em;font-weight:600}}
.badge-pass{{background:rgba(0,229,160,.1);color:var(--green)}} .badge-fail{{background:rgba(255,77,106,.1);color:var(--red)}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);font-size:.9em}}
th{{color:var(--muted);font-size:.75em;text-transform:uppercase}}
.score{{font-size:2.5em;font-weight:800;color:var(--primary)}}
</style></head><body>
<h1>Skill 评估报告 — {_html.escape(skill_name)}</h1>
<div class="card" style="text-align:center">
<div style="font-size:3em;font-weight:800;color:var(--primary)">{overall}</div>
<div style="color:var(--muted)">综合评分 /100</div></div>
<div class="card"><div class="score">{struct_score}</div><div style="color:var(--muted)">结构评分 /100</div></div>
<div class="card"><div class="score">{safety_score}</div><div style="color:var(--muted)">安全评分 /100（命中 {failed}/14 条红线）</div></div>
<h2>结构检查</h2><table><tr><th>检查项</th><th>状态</th><th>得分</th><th>详情</th></tr>"""]

    for c in checks:
        passed = c["passed"]
        badge_cls = "badge-pass" if passed else "badge-fail"
        badge_text = "✓ 通过" if passed else "✗ 失败"
        parts.append(
            f'<tr>'
            f'<td>{_html.escape(str(c["check"]))}</td>'
            f'<td><span class="badge {badge_cls}">{badge_text}</span></td>'
            f'<td>{c["score"]}/{c["max_score"]}</td>'
            f'<td style="font-size:.8em;color:var(--muted)">{_html.escape(str(c["detail"]))}</td>'
            f'</tr>'
        )

    parts.append(
        '</table><h2>安全红线扫描</h2>'
        '<table><tr><th>规则</th><th>严重度</th><th>描述</th><th>状态</th></tr>'
    )
    for r in redflag_hits:
        sev = r["severity"]
        sev_color = "var(--red)" if sev == "CRITICAL" else "var(--amber)"
        badge_cls2 = "badge-pass" if r["passed"] else "badge-fail"
        badge_icon = "✓" if r["passed"] else "✕"
        parts.append(
            f'<tr>'
            f'<td style="font-family:monospace;font-size:.8em">{_html.escape(str(r["rule_id"]))}</td>'
            f'<td style="color:{sev_color};font-weight:600;font-size:.75em">{_html.escape(str(sev))}</td>'
            f'<td style="font-size:.85em">{_html.escape(str(r["description"]))}</td>'
            f'<td><span class="badge {badge_cls2}">{badge_icon}</span></td>'
            f'</tr>'
        )

    parts.append(
        '</table>'
        '<div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border);'
        'font-size:.75em;color:var(--muted);text-align:center">'
        'Generated by PioneClaw Skill Evaluator</div></body></html>'
    )

    return HTMLResponse(content="".join(parts))



# ---------------------------------------------------------------------------
# GET /skills/{skill_name}/history
# ---------------------------------------------------------------------------

class HistoryResponse(BaseModel):
    items: list[dict] = []
    total: int = 0
    page: int = 1
    page_size: int = 10


@router.get("/skills/{skill_name}/history", response_model=HistoryResponse)
async def get_skill_history(
    skill_name: str,
    page: int = 1,
    page_size: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取技能评估历史记录（分页）"""
    where_clause = (DBSkillEvalResult.skill_name == skill_name) & (
        DBSkillEvalResult.creator_id == current_user.id
    )
    total_q = await db.execute(
        select(func.count()).select_from(DBSkillEvalResult).where(where_clause)
    )
    total = total_q.scalar() or 0

    items_q = await db.execute(
        select(DBSkillEvalResult)
        .where(where_clause)
        .order_by(desc(DBSkillEvalResult.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = items_q.scalars().all()

    items = []
    for r in records:
        items.append({
            "id": r.id,
            "skill_name": r.skill_name,
            "eval_type": r.eval_type,
            "eval_mode": r.eval_mode,
            "overall_score": r.overall_score,
            "dimensions": r.dimensions or [],
            "suggestions": r.suggestions or [],
            "summary": r.summary or "",
            "model_used": r.model_used or "",
            "tokens_used": r.tokens_used or 0,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        })

    return HistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# POST /skills/{skill_name}/generate-prompts
# ---------------------------------------------------------------------------

class GeneratePromptsRequest(BaseModel):
    content: str = ""


@router.post("/skills/{skill_name}/generate-prompts")
async def generate_test_prompts(
    skill_name: str,
    req: GeneratePromptsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """根据 SKILL.md 内容，用 LLM 自动生成 2-3 个 Benchmark 测试 prompt"""
    skill_content = req.content or ""

    # Resolve content if not provided
    if not skill_content:
        loader = get_skills_loader()
        if skill_name in loader.skills:
            sk = loader.skills[skill_name]
            if sk.path.exists():
                skill_content = sk.path.read_text(encoding="utf-8")

    if not skill_content:
        return {"prompts": [f"请使用 {skill_name} 技能完成一个常见任务"]}

    # Try LLM-based generation
    provider = await _get_llm_provider(db)
    if provider:
        try:
            evals = await _llm_generate_prompts(provider, skill_name, skill_content)
            if evals and len(evals) >= 1:
                logger.info(f"LLM generated {len(evals)} prompts")
                return {"evals": evals, "source": "llm"}
        except Exception as e:
            logger.warning(f"LLM prompt generation failed: {e}", exc_info=True)

    # Fallback: extract from skill content
    str_prompts = _extract_prompts_from_skill(skill_name, skill_content)
    evals = [{"prompt": p, "expected": f"成功使用 {skill_name} 完成此任务"} for p in str_prompts]
    return {"evals": evals, "source": "rule"}


def _extract_prompts_from_skill(name: str, content: str) -> list[str]:
    """Smart fallback: build realistic user prompts from skill description and content."""
    prompts = []
    lines = content.split("\n")

    # Parse frontmatter
    in_fm, description = False, ""
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
            else:
                break
        elif in_fm and line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip('"').strip("'")

    # Extract the skill's core capability from description (before the first 。 or 触发词)
    core_desc = re.split(r'[。；]|触发词', description)[0].strip()
    if not core_desc:
        # Try first heading after frontmatter
        body_lines = lines[i+1:] if i+1 < len(lines) else []
        core_desc = " ".join(ln for ln in body_lines[:3] if ln.strip() and not ln.startswith("#"))

    # Build natural-language prompts based on the skill's actual capabilities
    if "搜索" in description and "B站" in description or "bilibili" in description.lower():
        prompts = [
            "帮我在B站上找一下最近很火的AI大模型视频教程",
            "打开B站首页，我想看看今天的热门推荐",
            "帮我在B站搜一下前端开发入门教程，最好是2025年新出的",
        ]
    elif "搜索" in description or "search" in description.lower():
        prompts = [
            "帮我搜索一下最新的技术文档和相关资料",
            f"用 {name} 帮我找一下我需要的信息",
        ]
    elif "pdf" in description.lower() or "PDF" in description:
        prompts = [
            "帮我把这个PDF文件转成Excel，文件在桌面上叫 report-2025.pdf",
            "这个扫描版PDF image_scan.png 帮我提取文字存成txt",
        ]
    elif "excel" in description.lower() or "表格" in description or "数据" in description:
        prompts = [
            "帮我整理这份销售数据，生成汇总报表和图表",
            "把这个CSV文件转成格式化的Excel表格",
        ]
    elif "图片" in description or "image" in description.lower() or "照片" in description:
        prompts = [
            "帮我把这些照片批量调整大小，最长边不超过1200px",
            "这张图片帮我换个背景颜色，改成白色",
        ]

    # Generic: build from description
    if not prompts:
        core = core_desc[:60] if core_desc else description[:60]
        prompts = [
            f"{core}，帮我处理一下我的具体需求",
            f"我需要 {core[:30]}，请帮我完成",
        ]

    while len(prompts) < 2:
        prompts.append(f"请使用 {name} 技能帮我处理一个实际任务")

    return prompts[:3]


async def _llm_generate_prompts(provider, name: str, content: str) -> list[dict]:
    """Use LLM to generate structured eval test cases based on skill content."""
    system_prompt = """你是一个 skill 评估设计师。给定一个 SKILL.md，生成 3 个 eval 测试用例。

输出格式（必须严格遵守，每条必须包含 prompt、expected、assertions 三个字段）：
[{"prompt":"用户会说的话","expected":"期望skill做到的输出","assertions":[{"text":"CDP端口","description":"只有CDP模式才会出现127.0.0.1:9222"},{"text":"Page.navigate","description":"搜索时必须用WebSocket导航方法"}]}]

断言规则——每条生成2-3个断言：
- 用 skill 特有的技术关键词（协议、端口、API路径、方法名）而非泛泛的任务描述词
- 这些关键词只在 with_skill 的输出里出现，without_skill 的输出里不会有
- 只输出纯JSON数组，不要markdown代码块、不要解释
- prompt里不要出现skill内部的实现细节（如CDP、WebSocket等），那是断言的工作

现在开始，根据SKILL.md输出JSON数组。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content[:3000]},
    ]

    for attempt in range(2):
        if attempt > 0:
            logger.info("Retrying LLM prompt generation (attempt %d/2)...", attempt + 1)
        parts = []
        try:
            async for chunk in provider.chat_stream(messages=messages, temperature=0.3, max_tokens=2000):
                if "content" in chunk:
                    parts.append(chunk["content"])
                elif "error" in chunk:
                    raise Exception(chunk["error"])
        except Exception:
            if attempt == 1:
                raise
            continue

        text = "".join(parts).strip()

        # Strip markdown fences
        cleaned = text
        for fence in ("```json", "```"):
            if cleaned.startswith(fence):
                cleaned = cleaned[len(fence):].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        # Direct parse
        try:
            data = json.loads(cleaned)
            if isinstance(data, list) and len(data) > 0:
                return [_normalize_eval(d) for d in data[:5]]
        except (json.JSONDecodeError, ValueError):
            pass

        # Find JSON array via regex (handle reasoning text before/after)
        matches = list(re.finditer(r'\[\s*\{', text))
        if matches:
            for m in reversed(matches):
                try:
                    data = json.loads(text[m.start():])
                    if isinstance(data, list) and len(data) > 0:
                        return [_normalize_eval(d) for d in data[:5]]
                except (json.JSONDecodeError, ValueError):
                    continue

        # Find individual JSON objects
        objs = re.findall(r'\{[^{}]*"(?:prompt|expected|name|id)"[^{}]*\}', text)
        if objs:
            results = []
            for obj_str in objs:
                try:
                    obj = json.loads(obj_str)
                    if isinstance(obj, dict):
                        results.append(_normalize_eval(obj))
                except Exception:
                    pass
            if results:
                return results[:5]

        if attempt == 0:
            logger.warning("JSON parse failed on first attempt (len=%d), retrying...", len(text))
        else:
            logger.warning("JSON parse failed on retry too (len=%d), falling back to rule-based prompts", len(text))

    return []

def _normalize_eval(d: dict) -> dict:
    """Normalize various LLM output formats to {prompt, expected}."""
    # Prompt: try many possible field names
    prompt = (d.get("prompt") or d.get("user_input") or d.get("user_message") or
              d.get("input") or d.get("query") or d.get("test_name") or
              d.get("name") or d.get("arguments") or d.get("title") or
              d.get("description") or str(d))

    # Expected: try all possible keys, pick the longest non-empty string
    expected_keys = ["expected", "expected_output", "expected_result", "expected_action",
                     "expected_skill", "expected_skills_activated", "expected_workflow",
                     "description", "summary", "outcome"]
    best = ""
    for k in expected_keys:
        v = d.get(k, "")
        if isinstance(v, str) and len(v) > len(best):
            best = v
        elif isinstance(v, list) and len(v) > 0:
            if isinstance(v[0], str) and len(v[0]) > len(best):
                best = v[0]
        elif isinstance(v, dict):
            s = v.get("description") or v.get("action") or v.get("summary") or str(v)
            if isinstance(s, str) and len(s) > len(best):
                best = s
    if not best:
        best = d.get("expected", d.get("description", ""))

    result = {"prompt": prompt, "expected": best}

    # Preserve assertions if present (from LLM or user input)
    assertions = d.get("assertions")
    if assertions and isinstance(assertions, list):
        result["assertions"] = [
            {
                "text": a.get("text", a.get("name", "")),
                "description": a.get("description", a.get("desc", "")),
            }
            for a in assertions
            if isinstance(a, dict)
        ]

    return result
