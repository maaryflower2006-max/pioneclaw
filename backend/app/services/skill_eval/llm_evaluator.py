"""LLM-based skill evaluator — evaluates SKILL.md across 5 subjective dimensions.

Uses a single LLM call with concise prompt to minimize latency.
Enables provider fast_mode when available (e.g. disables DeepSeek reasoning).
"""

import json
import logging
import re
from dataclasses import dataclass, field

from app.modules.llm.provider import SimpleLLMProvider

logger = logging.getLogger(__name__)


@dataclass
class DimensionResult:
    key: str
    label: str
    score: int          # 0-100
    comment: str        # Chinese comment, up to ~100 chars


@dataclass
class Suggestion:
    title: str
    detail: str
    severity: str       # high | medium | low
    category: str = ""  # instructions | tools | examples | error_handling | structure | references | ""
    impact: str = ""    # 如果不修复会导致什么问题


@dataclass
class LLMEvalResult:
    dimensions: list[DimensionResult] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    summary: str = ""
    raw_response: str = ""   # for debugging
    available: bool = True   # False when LLM API unavailable


_EVAL_SYSTEM_PROMPT = """\
你是一个技能评估专家，按 skill-creator 框架标准对一份 SKILL.md 进行深度评估。

对每个维度给出 0-100 的整数分数和中文评语（≤100字），评语必须引用 SKILL.md 中的具体内容作为证据。
评分必须严格、客观，不虚高。大多数 skill 应在 40-80 范围。

重要原则 — substance-over-form：
- 有序号 ≠ 步骤可执行，有代码块 ≠ 示例有效
- 检查的是「质量」而非「有没有」

评分维度：

1. clarity 清晰度与可执行性
   - 步骤是否可直接执行（而非仅有序号）？命令/参数是否可直接复制粘贴？
   - 术语是否一致（同一概念不用不同词汇）？
   - scripts/ 中的脚本语法是否正确？参数定义是否完整（含强制/可选/默认值）？
   - 是否有"工作原理"等帮助模型理解执行流程的说明？

2. completeness 完整性与边界处理
   - 边界条件覆盖是否充分？异常路径有无恢复方案？
   - 前置依赖是否清楚？是否有预检机制（如检查 python/openpyxl、Chrome、扩展路径）？
   - 故障排除(troubleshooting)是否覆盖常见失败模式？
   - 配置项、超时值、默认值在文档与脚本中是否一致？

3. conciseness 简洁度与信息密度
   - 信息密度如何？有无"大段解释已知概念"的填充段落？
   - 是否有应移到 references/ 的冗长细节？
   - 渐进式信息披露是否合理（SKILL.md 放核心，细节放 references/）？

4. trigger 触发精准与描述质量
   - description 是否足够"pushy"（主动触发而非被动等待）？
   - 触发条件是否具象（真实用户会怎么问）？与相邻 skill 边界是否清晰？
   - 是否缺少 compatibility 前置信息（Chrome 版本、Python 版本、OS 限制等）？

5. dependencies 依赖声明与可移植性
   - 外部依赖是否全部声明（python 包、浏览器、扩展、系统工具等）？
   - 引用路径是否真实可达？scripts/ 引用是否正确？
   - 是否存在硬编码路径（如 C:\\Users\\Yue\\）？是否不可移植？
   - 内联脚本（如 PowerShell 嵌入 Python）是否存在注入风险？

同时生成 4-6 条中文修改建议，按 severity (high/medium/low) 排列。
建议必须具体、可执行，禁止泛泛而谈。必须涵盖以下方面：
- high：影响触发或执行正确性的问题（如硬编码路径、预检缺失、注入风险、超时/默认值不一致）
- medium：提升用户体验的问题（如 description 改写、compatibility 补充、术语统一）
- low：锦上添花（如格式美化、注释补充）

每条建议必须附加：
- category：问题所属类别，必须从以下选择：instructions（指令问题）、tools（脚本/工具）、
      examples（示例缺失）、error_handling（错误处理）、structure（结构组织）、references（引用/参考）
- impact（≤30字）：如果不修复此问题，会导致什么具体后果。禁止写"影响用户体验"等空话，必须写具体后果如"硬编码路径导致其他用户无法执行脚本"

重要原则：禁止猜测 SKILL.md 中不存在的内容。你评分和提建议必须基于 SKILL.md 中实际写的内容，没提到的不要评。

一条中文总结 (≤30字)。

输出严格按以下 JSON 格式（不要 markdown 代码块包裹）：
{
  "dimensions": [
    {"key": "clarity", "score": 85, "comment": "步骤可执行但脚本缺少参数默认值说明"}
  ],
  "suggestions": [
    {"title": "修复硬编码路径", "detail": "C:\\\\Users\\\\Yue\\\\ 应改为可配置或环境变量",
     "severity": "high", "category": "tools", "impact": "其他用户执行时会因路径不存在而失败"},
    {"title": "添加预检机制", "detail": "在 Prerequisite 中验证 openpyxl 和 Chrome 扩展是否存在",
     "severity": "high", "category": "instructions", "impact": "缺少依赖时执行会报错且用户不知如何排查"}
  ],
  "summary": "结构清晰但存在硬编码和预检缺失"
}

强制要求：
1. dimensions 数组必须恰好包含 5 个元素（clarity、completeness、conciseness、trigger、dependencies），缺一不可。即使某个维度得 0 分，也必须出现在数组中。
2. 不要输出任何思考过程、解释或额外文字，只输出上述 JSON。
3. 不要包装在 markdown 代码块中。
"""


class LLMEvaluator:
    """Evaluates a SKILL.md using LLM across 5 subjective dimensions."""

    def __init__(self, provider: SimpleLLMProvider):
        self.provider = provider

    async def evaluate(self, skill_content: str) -> LLMEvalResult:
        """Run LLM evaluation. Returns structured result.
        On API failure, returns result with available=False and zero scores.
        """
        user_prompt = f"请评估以下 SKILL.md。\n\n---\n{skill_content}\n---"

        messages = [
            {"role": "system", "content": _EVAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw_text = await self._call_llm(messages, max_tokens=16000)
        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return LLMEvalResult(
                available=False,
                summary=f"评估失败: {e}",
                dimensions=[
                    DimensionResult(key=k, label=_dim_label(k), score=0, comment=f"错误: {str(e)[:40]}")
                    for k in ("clarity", "completeness", "conciseness", "trigger", "dependencies")
                ],
            )

        result = self._parse_response(raw_text)
        result.raw_response = raw_text
        return result

    async def _call_llm(self, messages: list[dict], max_tokens: int = 800) -> str:
        """Collect all content chunks from the async generator."""
        parts: list[str] = []
        async for chunk in self.provider.chat_stream(
            messages=messages, temperature=0.2, max_tokens=max_tokens
        ):
            if "error" in chunk:
                raise RuntimeError(f"LLM API error: {chunk['error']}")
            parts.append(chunk.get("content", ""))
        raw_text = "".join(parts).strip()
        logger.info(f"LLM raw response length: {len(raw_text)}, prefix: {raw_text[:200]!r}, suffix: {raw_text[-200:]!r}")
        return raw_text

    def _parse_response(self, text: str) -> LLMEvalResult:
        """Parse JSON from LLM response, handling markdown fences and natural language prefixes."""
        data = self._extract_json_dict(text)
        if data is None:
            logger.warning(f"JSON parse failed, raw: {text[:300]}")
            return self._fallback_result(text)

        return self._build_result(data)

    def _build_result(self, data: dict) -> LLMEvalResult:
        """Build LLMEvalResult from parsed dict."""
        dim_labels = {
            "clarity": "清晰度",
            "completeness": "完整性",
            "conciseness": "简洁度",
            "trigger": "触发精准",
            "dependencies": "依赖声明",
        }

        raw_dims = data.get("dimensions", [])

        dimensions = []
        for d in raw_dims:
            key = d.get("key", "")
            raw_score = d.get("score", 0)
            score = max(0, min(100, int(raw_score)))
            comment = str(d.get("comment", ""))[:200]
            dimensions.append(DimensionResult(
                key=key, label=dim_labels.get(key, key), score=score, comment=comment
            ))

        # Fallback: if dimensions are empty or missing keys, fill with defaults
        present_keys = {d.key for d in dimensions}
        for k, label in dim_labels.items():
            if k not in present_keys:
                dimensions.append(DimensionResult(key=k, label=label, score=0, comment="未评分"))

        valid_categories = {"instructions", "tools", "examples", "error_handling", "structure", "references"}
        suggestions = []
        for s in data.get("suggestions", []):
            severity = s.get("severity", "low")
            if severity not in ("high", "medium", "low"):
                severity = "low"
            category = s.get("category", "")
            if category not in valid_categories:
                category = ""
            suggestions.append(Suggestion(
                title=str(s.get("title", ""))[:50],
                detail=str(s.get("detail", ""))[:200],
                severity=severity,
                category=category,
                impact=str(s.get("impact", ""))[:50],
            ))

        return LLMEvalResult(
            dimensions=dimensions,
            suggestions=suggestions,
            summary=str(data.get("summary", ""))[:40],
            available=True,
        )

    def _fallback_result(self, raw_text: str) -> LLMEvalResult:
        """When JSON parsing completely fails."""
        logger.error("Could not parse LLM response as JSON")
        dim_labels = {
            "clarity": "清晰度",
            "completeness": "完整性",
            "conciseness": "简洁度",
            "trigger": "触发精准",
            "dependencies": "依赖声明",
        }
        return LLMEvalResult(
            available=False,
            summary="LLM 响应解析失败",
            raw_response=raw_text[:500],
            dimensions=[
                DimensionResult(key=k, label=label, score=0, comment="解析失败")
                for k, label in dim_labels.items()
            ],
        )

    def _extract_json_dict(self, text: str) -> dict | None:
        """Extract and parse JSON dict from text, handling fences and prefixes."""
        cleaned = text.strip()

        # Strip markdown fences
        code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if code_match:
            cleaned = code_match.group(1).strip()

        # Direct parse attempt
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # Brace-balanced scan for largest JSON object
        best = ""
        for i, ch in enumerate(cleaned):
            if ch == "{":
                depth = 1
                for j in range(i + 1, len(cleaned)):
                    if cleaned[j] == "{":
                        depth += 1
                    elif cleaned[j] == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = cleaned[i : j + 1]
                            if len(candidate) > len(best):
                                best = candidate
                            break
        if best:
            try:
                data = json.loads(best)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        return None


def _dim_label(key: str) -> str:
    return {
        "clarity": "清晰度",
        "completeness": "完整性",
        "conciseness": "简洁度",
        "trigger": "触发精准",
        "dependencies": "依赖声明",
    }.get(key, key)
