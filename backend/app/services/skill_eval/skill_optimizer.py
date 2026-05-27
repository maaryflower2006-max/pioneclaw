"""Skill optimizer — improves SKILL.md based on evaluation suggestions."""

import logging
from dataclasses import dataclass

from app.modules.llm.provider import SimpleLLMProvider

logger = logging.getLogger(__name__)


@dataclass
class OptimizeRequest:
    content: str                       # Original SKILL.md
    suggestions: list[dict]            # From evaluator (title, detail, severity, category, impact)
    target_dimensions: list[str] = None  # e.g. ["clarity", "trigger"]; None = all
    benchmark_context: dict | None = None  # Optional benchmark results for richer optimization


class SkillOptimizer:
    """Optimizes a SKILL.md given evaluation feedback."""

    def __init__(self, provider: SimpleLLMProvider):
        self.provider = provider

    async def optimize(self, request: OptimizeRequest) -> str:
        """Return optimized SKILL.md content."""
        system_prompt = self._build_system_prompt(request.target_dimensions)
        user_prompt = self._build_user_prompt(request)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        parts: list[str] = []
        async for chunk in self.provider.chat_stream(messages=messages, temperature=0.3, max_tokens=8000):
            if "error" in chunk:
                raise RuntimeError(f"LLM API error: {chunk['error']}")
            parts.append(chunk.get("content", ""))

        result = "".join(parts).strip()

        # Strip markdown fences if the LLM wrapped output
        if result.startswith("```"):
            import re
            result = re.sub(r"^```(?:markdown)?\s*", "", result)
            result = re.sub(r"\s*```$", "", result)

        return result

    def _build_system_prompt(self, target_dimensions: list[str] | None) -> str:
        dim_text = ""
        if target_dimensions:
            dim_names = {
                "clarity": "清晰度",
                "completeness": "完整性",
                "conciseness": "简洁度",
                "trigger": "触发精准",
                "dependencies": "依赖声明",
            }
            labels = [dim_names.get(d, d) for d in target_dimensions]
            dim_text = f"目标维度: {', '.join(labels)}。只改进这些维度相关的问题，其他方面保持不变。"
        else:
            dim_text = "改进所有维度的问题。"

        return f"""\
你是一个 Skill 优化专家。根据评估发现的问题优化 SKILL.md。

{dim_text}

优化原则:
- 保持原有结构和用途不变
- 只改进问题点，不要重写整个 skill
- 避免过度约束（少用 ALL-CAPS MUST），解释 WHY 而非直接命令
- 保持 CONCRETE CODE + REFERENCE IMPLEMENTATION 的完整性
- 如果原 skill 有代码块，保持它们的完整性，只改问题部分
- 不要添加与原 skill 无关的新内容

输出: 优化后的完整 SKILL.md（包含 YAML frontmatter 和全部正文内容，不得截断省略）
"""

    def _build_user_prompt(self, request: OptimizeRequest) -> str:
        suggestion_lines = []
        for s in request.suggestions:
            sev = s.get("severity", "low")
            cat = s.get("category", "")
            title = s.get("title", "")
            detail = s.get("detail", "")
            impact = s.get("impact", "")
            cat_tag = f"[{cat}] " if cat else ""
            impact_text = f"（影响: {impact}）" if impact else ""
            suggestion_lines.append(f"- [{sev}] {cat_tag}{title}: {detail} {impact_text}")

        suggestions_text = "\n".join(suggestion_lines) if suggestion_lines else "（无具体建议，请基于整体质量进行优化）"

        # Benchmark section (optional)
        benchmark_section = ""
        if request.benchmark_context:
            bc = request.benchmark_context
            benchmark_section = "\n## Benchmark 实测结果\n\n"
            # Assertion summary
            a = bc.get("assertion_summary", {})
            if a:
                total = a.get("total", 0)
                w_passed = a.get("with_skill_passed", 0)
                b_passed = a.get("baseline_passed", 0)
                benchmark_section += (
                    f"- 断言通过率: With Skill {w_passed}/{total} vs Baseline {b_passed}/{total}\n"
                )
            # Stats
            st = bc.get("stats", {})
            ds = st.get("delta", {})
            if ds:
                benchmark_section += (
                    f"- 时间 Delta: {ds.get('time_seconds', '-')}\n"
                    f"- Token Delta: {ds.get('tokens', '-')}\n"
                )
            # Per-run assertion details
            runs = bc.get("runs", [])
            if runs:
                benchmark_section += "\n逐条断言打分:\n"
                for i, r in enumerate(runs):
                    prompt = r.get("prompt", "")[:50]
                    w_p = r.get("with_pass", 0)
                    w_t = r.get("with_total", 0)
                    b_p = r.get("baseline_pass", 0)
                    b_t = r.get("baseline_total", 0)
                    benchmark_section += (
                        f"  {i+1}. \"{prompt}\" → With: {w_p}/{w_t}, Baseline: {b_p}/{b_t}\n"
                    )
            benchmark_section += (
    "\n如果断言区分度不足（with/baseline 差距小），"
    "说明 skill 的关键技术指示词不够突出，"
    "需要在 SKILL.md 中强化这些关键词的位置和可见性。\n"
)

        return f"""\
## 当前 SKILL.md

```markdown
{request.content}
```

## 需要改进的问题

{suggestions_text}
{benchmark_section}
请输出优化后的完整 SKILL.md。
"""
