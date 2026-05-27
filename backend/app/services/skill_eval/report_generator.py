"""
Self-contained HTML report generator for skill evaluation results.

Generates complete HTML documents (no external dependencies) for:
- Single evaluation results (8-dim rubric + static checks + redflags)
- Benchmark comparisons (with/without skill)
- A/B blind comparison results
- Optimization results (changes + diff)

Design: dark glass-morphism theme matching PioneClaw UI.
Reference: skill-creator eval-viewer/generate_review.py patterns.
"""
from datetime import datetime, timezone

from app.schemas.skill_eval import (
    BenchmarkResult,
    ComparisonResult,
    GradingResult,
    OptimizationResult,
)

# ---------------------------------------------------------------------------
# Shared CSS
# ---------------------------------------------------------------------------

BASE_CSS = """
:root {
    --bg: #0f0f1a;
    --surface: #1a1a2e;
    --border: #2a2a4a;
    --primary: #7c3aed;
    --primary-rgb: 124, 58, 237;
    --text: #e2e8f0;
    --text-muted: #94a3b8;
    --green: #22c55e;
    --amber: #f59e0b;
    --red: #ef4444;
    --radius: 8px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    max-width: 960px;
    margin: 0 auto;
    padding: 24px 20px;
    line-height: 1.6;
}
h1 { font-size: 1.5em; margin-bottom: 4px; }
h2 { font-size: 1.15em; margin: 24px 0 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
    margin-bottom: 12px;
}
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: 600;
    text-transform: uppercase;
}
.badge-high { background: rgba(239,68,68,0.15); color: var(--red); }
.badge-medium { background: rgba(245,158,11,0.15); color: var(--amber); }
.badge-low { background: rgba(34,197,94,0.15); color: var(--green); }
.badge-critical { background: rgba(239,68,68,0.2); color: var(--red); }
table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 16px;
}
th, td {
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    font-size: 0.9em;
}
th { color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 0.78em; letter-spacing: 0.5px; }
tr:hover { background: rgba(255,255,255,0.02); }
.score-bar {
    height: 6px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
    margin-top: 4px;
}
.score-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
.dim-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
}
pre {
    background: rgba(0,0,0,0.3);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px;
    overflow-x: auto;
    font-size: 0.82em;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
}
.footer {
    margin-top: 32px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    color: var(--text-muted);
    font-size: 0.78em;
    text-align: center;
}
.compare-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
}
.compare-col { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
.winner { border-color: var(--primary); box-shadow: 0 0 12px rgba(var(--primary-rgb), 0.15); }
.diff-add { color: var(--green); }
.diff-rem { color: var(--red); }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_color(score: float) -> str:
    if score >= 80:
        return "var(--green)"
    if score >= 60:
        return "var(--amber)"
    return "var(--red)"


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _dimension_bar(key: str, label: str, score: int, weight: int, comment: str) -> str:
    pct = score * 10
    color = _score_color(pct)
    return f"""<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="font-weight:600;">{_escape(label)}</span>
        <span style="color:{color};font-weight:700;font-size:1.1em;">{score}<span style="font-size:0.7em;color:var(--text-muted);">/10</span></span>
    </div>
    <div style="font-size:0.75em;color:var(--text-muted);margin:2px 0;">权重 {weight} · 加权 {score * weight / 10:.1f}</div>
    <div class="score-bar"><div class="score-bar-fill" style="width:{pct}%;background:{color};"></div></div>
    {f'<div style="font-size:0.8em;color:var(--text-muted);margin-top:6px;">{_escape(comment)}</div>' if comment else ''}
</div>"""


def _html_frame(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape(title)}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<h1>{_escape(title)}</h1>
{body}
<div class="footer">Generated by PioneClaw Skill Evaluator · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Evaluation Report
# ---------------------------------------------------------------------------

def generate_evaluation_report(result: GradingResult, skill_name: str = "") -> str:
    """Generate HTML report for a single evaluation."""
    title = f"Skill 评估报告{f' — {skill_name}' if skill_name else ''}"
    score = result.overall_score
    color = _score_color(score)

    parts = [f"""
<div class="card" style="text-align:center;padding:32px;">
    <div style="font-size:3em;font-weight:800;color:{color};">{score:.1f}</div>
    <div style="color:var(--text-muted);">综合评分 / 100</div>
    {f'<div style="margin-top:8px;font-size:0.9em;">{_escape(result.summary)}</div>' if result.summary else ''}
    {(
        f'<div style="margin-top:4px;font-size:0.75em;color:var(--text-muted);">'
        f'模型: {_escape(result.model_used) or "—"} · Tokens: {result.tokens_used}</div>'
        if result.model_used or result.tokens_used else ''
    )}
</div>"""]

    # 8 Dimensions
    if result.dimensions:
        parts.append('<h2>维度评分</h2><div class="dim-grid">')
        for d in result.dimensions:
            parts.append(_dimension_bar(d.key, d.label, d.score, d.weight, d.comment))
        parts.append('</div>')

    # Static checks
    if result.static_checks:
        parts.append('<h2>结构检查</h2><table><tr><th>检查项</th><th>状态</th><th>得分</th><th>详情</th></tr>')
        for c in result.static_checks:
            passed = c.get("passed", False)
            status = '<span style="color:var(--green)">✓ 通过</span>' if passed else '<span style="color:var(--red)">✗ 失败</span>'
            parts.append(
                f'<tr><td>{_escape(str(c.get("check","")))}</td>'
                f'<td>{status}</td>'
                f'<td>{c.get("score",0)}/{c.get("max_score",0)}</td>'
                f'<td style="font-size:0.82em;color:var(--text-muted);">'
                f'{_escape(str(c.get("detail","")))}</td></tr>'
            )
        parts.append('</table>')

    # Redflag hits
    if result.redflag_hits:
        parts.append('<h2>安全红线命中</h2><table><tr><th>规则</th><th>严重度</th><th>描述</th><th>位置</th></tr>')
        for h in result.redflag_hits:
            sev = h.get("severity", "HIGH")
            sev_class = "badge-critical" if sev == "CRITICAL" else "badge-high"
            parts.append(
                f'<tr>'
                f'<td style="font-family:monospace;">{_escape(str(h.get("rule_id","")))}</td>'
                f'<td><span class="badge {sev_class}">{_escape(sev)}</span></td>'
                f'<td>{_escape(str(h.get("description","")))}</td>'
                f'<td style="font-size:0.8em;color:var(--text-muted);">'
                f'行 {h.get("line",0)}: {_escape(str(h.get("snippet","")))[:80]}</td>'
                f'</tr>'
            )
        parts.append('</table>')

    # Suggestions
    if result.suggestions:
        parts.append('<h2>优化建议</h2>')
        for s in result.suggestions:
            if isinstance(s, dict):
                pri = s.get("priority", "medium")
                pri_class = f"badge-{pri}" if pri in ("high","medium","low") else "badge-medium"
                parts.append(f"""<div class="card">
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">
        <span class="badge {pri_class}">{s.get('priority','?')}</span>
        <span style="font-size:0.78em;color:var(--primary);">{_escape(str(s.get('category','')))}</span>
    </div>
    <div style="font-weight:600;">{_escape(str(s.get('title','')))}</div>
    <div style="font-size:0.85em;color:var(--text-muted);margin-top:4px;">{_escape(str(s.get('detail','')))}</div>
    {f'<div style="font-size:0.8em;color:var(--amber);margin-top:4px;">影响: {_escape(str(s.get("impact","")))}</div>' if s.get('impact') else ''}
</div>""")
            else:
                pri = getattr(s, 'priority', 'medium')
                pri_class = f"badge-{pri}" if pri in ("high","medium","low") else "badge-medium"
                parts.append(f"""<div class="card">
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">
        <span class="badge {pri_class}">{pri}</span>
        <span style="font-size:0.78em;color:var(--primary);">{_escape(str(getattr(s,'category','')))}</span>
    </div>
    <div style="font-weight:600;">{_escape(str(getattr(s,'title','')))}</div>
    <div style="font-size:0.85em;color:var(--text-muted);margin-top:4px;">{_escape(str(getattr(s,'detail','')))}</div>
    {f'<div style="font-size:0.8em;color:var(--amber);margin-top:4px;">影响: {_escape(str(getattr(s,"impact","")))}</div>' if getattr(s,'impact','') else ''}
</div>""")

    return _html_frame(title, "\n".join(parts))


# ---------------------------------------------------------------------------
# Benchmark Report
# ---------------------------------------------------------------------------

def generate_benchmark_report(benchmark: BenchmarkResult) -> str:
    """Generate HTML report for benchmark results."""
    meta = benchmark.metadata
    skill_name = meta.get("skill_name", "") if isinstance(meta, dict) else getattr(meta, "skill_name", "")
    title = f"Benchmark 报告{f' — {skill_name}' if skill_name else ''}"

    run_summary = benchmark.run_summary
    parts = []

    # Metadata
    model_name = _escape(str(meta.get('executor_model', meta.get('model','—')))
                         if isinstance(meta, dict) else '—')
    version = _escape(str(meta.get('version','—')) if isinstance(meta, dict) else '—')
    timestamp = _escape(str(meta.get('timestamp','—')) if isinstance(meta, dict) else '—')
    evals = _escape(str(meta.get('evals_run','—')) if isinstance(meta, dict) else '—')
    runs = _escape(str(meta.get('runs_per_configuration','—')) if isinstance(meta, dict) else '—')
    parts.append(f"""<div class="card" style="font-size:0.85em;color:var(--text-muted);">
    <div>模型: {model_name} · 版本: {version} · 时间: {timestamp}</div>
    <div>Evals: {evals} · 每配置 {runs} 轮</div>
</div>""")

    # Config comparison
    if run_summary:
        parts.append('<h2>配置对比</h2><table><tr><th>配置</th><th>Pass Rate</th><th>耗时 (s)</th><th>Tokens</th></tr>')
        for config_name in sorted(run_summary.keys()):
            if config_name == "delta":
                continue
            cfg = run_summary[config_name]
            if not isinstance(cfg, dict):
                continue
            pr = cfg.get("pass_rate", {}) if isinstance(cfg.get("pass_rate"), dict) else {}
            ts = cfg.get("time_seconds", {}) if isinstance(cfg.get("time_seconds"), dict) else {}
            tk = cfg.get("tokens", {}) if isinstance(cfg.get("tokens"), dict) else {}
            pr_mean = pr.get("mean", 0) if isinstance(pr, dict) else 0
            ts_mean = ts.get("mean", 0) if isinstance(ts, dict) else 0
            tk_mean = tk.get("mean", 0) if isinstance(tk, dict) else 0
            parts.append(
                f'<tr><td style="font-weight:600;">{_escape(config_name)}</td>'
                f'<td>{pr_mean*100:.0f}%</td><td>{ts_mean:.1f}</td>'
                f'<td>{tk_mean:.0f}</td></tr>'
            )

        # Delta row
        delta = run_summary.get("delta", {})
        if isinstance(delta, dict):
            parts.append(
                f'<tr style="border-top:2px solid var(--primary);">'
                f'<td style="font-weight:700;color:var(--primary);">Delta</td>'
                f'<td style="color:var(--primary);">'
                f'{_escape(str(delta.get("pass_rate","—")))}</td>'
                f'<td>{_escape(str(delta.get("time_seconds","—")))}</td>'
                f'<td>{_escape(str(delta.get("tokens","—")))}</td></tr>'
            )
        parts.append('</table>')

    # Runs detail
    if benchmark.runs:
        parts.append('<h2>运行详情</h2><table><tr><th>Eval</th><th>配置</th><th>Run</th><th>Pass</th><th>耗时</th><th>Tokens</th></tr>')
        for r in benchmark.runs:
            if isinstance(r, dict):
                result = r.get("result", {}) if isinstance(r.get("result"), dict) else {}
                parts.append(f'<tr><td>{_escape(str(r.get("eval_id","?")))}</td><td>{_escape(str(r.get("configuration","?")))}</td><td>{r.get("run_number","?")}</td><td>{result.get("pass_rate",0)*100:.0f}%</td><td>{result.get("time_seconds",0):.1f}s</td><td>{result.get("tokens",0)}</td></tr>')
        parts.append('</table>')

    # Notes
    if benchmark.notes:
        parts.append('<h2>分析备注</h2>')
        for note in benchmark.notes:
            parts.append(f'<div class="card" style="font-size:0.9em;">{_escape(str(note))}</div>')

    return _html_frame(title, "\n".join(parts))


# ---------------------------------------------------------------------------
# Comparison Report
# ---------------------------------------------------------------------------

def generate_comparison_report(comparison: ComparisonResult, skill_name: str = "") -> str:
    """Generate HTML report for A/B comparison results."""
    title = f"A/B 对比报告{f' — {skill_name}' if skill_name else ''}"
    winner = comparison.winner
    winner_color = {"A": "var(--green)", "B": "var(--green)", "TIE": "var(--amber)"}.get(winner, "var(--text)")

    parts = [f"""
<div class="card" style="text-align:center;padding:28px;">
    <div style="font-size:2em;font-weight:800;color:{winner_color};">Winner: {_escape(winner)}</div>
    {f'<div style="margin-top:8px;font-size:0.9em;color:var(--text-muted);">{_escape(comparison.reasoning)}</div>' if comparison.reasoning else ''}
</div>"""]

    # Rubric scores
    rubric = comparison.rubric
    if rubric:
        parts.append('<h2>Rubric 评分对比</h2><div class="compare-grid">')
        for side in ("A", "B"):
            if side not in rubric:
                continue
            rs = rubric[side]
            is_winner = (side == winner)
            parts.append(f'<div class="compare-col{" winner" if is_winner else ""}">')
            parts.append(f'<h3 style="margin-top:0;">输出 {side}{" ★" if is_winner else ""}</h3>')

            if isinstance(rs, dict):
                content_score = rs.get("content_score", rs.get("content_score", 0))
                structure_score = rs.get("structure_score", rs.get("structure_score", 0))
                overall = rs.get("overall_score", rs.get("overall_score", 0))
            else:
                content_score = getattr(rs, "content_score", 0)
                structure_score = getattr(rs, "structure_score", 0)
                overall = getattr(rs, "overall_score", 0)

            parts.append(
                f'<div style="font-size:2em;font-weight:800;color:{_score_color(overall*10)};">'
                f'{overall:.1f}'
                f'<span style="font-size:0.5em;color:var(--text-muted);">/10</span>'
                f'</div>'
            )
            parts.append(f'<div style="font-size:0.85em;color:var(--text-muted);">Content: {content_score:.1f} · Structure: {structure_score:.1f}</div>')
            parts.append('</div>')
        parts.append('</div>')

    return _html_frame(title, "\n".join(parts))


# ---------------------------------------------------------------------------
# Optimization Report
# ---------------------------------------------------------------------------

def generate_optimization_report(result: OptimizationResult, skill_name: str = "") -> str:
    """Generate HTML report for optimization results."""
    title = f"优化报告{f' — {skill_name}' if skill_name else ''}"
    delta = result.estimated_score_delta
    delta_color = "var(--green)" if delta > 0 else ("var(--red)" if delta < 0 else "var(--text-muted)")

    parts = [f"""
<div class="card" style="text-align:center;padding:28px;">
    <div style="font-size:2.5em;font-weight:800;color:{delta_color};">{delta:+.1f}</div>
    <div style="color:var(--text-muted);">预估分数变化</div>
</div>"""]

    # Changes
    if result.changes:
        parts.append('<h2>变更列表</h2>')
        for c in result.changes:
            if isinstance(c, dict):
                parts.append(f"""<div class="card">
    <div style="font-weight:600;color:var(--primary);margin-bottom:4px;">{_escape(str(c.get('dimension','')))}</div>
    <div style="font-size:0.82em;color:var(--text-muted);margin-bottom:6px;">{_escape(str(c.get('description','')))}</div>
    <div style="font-size:0.8em;"><span class="diff-rem">- {_escape(str(c.get('before','')))[:120]}</span></div>
    <div style="font-size:0.8em;"><span class="diff-add">+ {_escape(str(c.get('after','')))[:120]}</span></div>
</div>""")
            else:
                parts.append(f"""<div class="card">
    <div style="font-weight:600;color:var(--primary);margin-bottom:4px;">{_escape(getattr(c,'dimension',''))}</div>
    <div style="font-size:0.82em;color:var(--text-muted);margin-bottom:6px;">{_escape(getattr(c,'description',''))}</div>
    <div style="font-size:0.8em;"><span class="diff-rem">- {_escape(getattr(c,'before',''))[:120]}</span></div>
    <div style="font-size:0.8em;"><span class="diff-add">+ {_escape(getattr(c,'after',''))[:120]}</span></div>
</div>""")
    else:
        parts.append('<div class="card" style="text-align:center;color:var(--text-muted);padding:20px;">无变更</div>')

    # Optimized content
    if result.optimized_content:
        parts.append(f'<h2>优化后内容</h2><pre>{_escape(result.optimized_content[:5000])}{"..." if len(result.optimized_content) > 5000 else ""}</pre>')

    return _html_frame(title, "\n".join(parts))
