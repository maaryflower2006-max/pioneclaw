"""
Red Flag Scanner — 14 条安全红线自动化检测引擎

从 skill-vetter 协议移植，对技能文件进行逐行扫描。
命中任一 CRITICAL 规则 → 立即拒绝。

评分规则:
  - 满分 100
  - 每条 HIGH 命中: -15
  - 任意 CRITICAL 命中: 直接归零
  - 最低 0 分
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RedFlagHit:
    """单条红线命中记录"""
    rule_id: str          # "RF01" ~ "RF14"
    severity: str         # "CRITICAL" | "HIGH"
    description: str      # 人类可读描述
    line: int             # 命中行号 (文件名匹配时为 0)
    snippet: str          # 命中内容摘要


@dataclass
class RedFlagResult:
    """一次扫描的聚合结果"""
    passed: bool = True
    total_hits: int = 0
    critical_hits: int = 0
    high_hits: int = 0
    hits: list[RedFlagHit] = field(default_factory=list)
    score: int = 100
    verdict: str = "PASS"


@dataclass
class RedFlagRuleResult:
    """单条红线规则的检测结果（无论命中与否都返回）"""
    rule_id: str          # "RF01" ~ "RF14"
    description: str      # 人类可读描述
    severity: str         # "CRITICAL" | "HIGH"
    passed: bool          # True = 未命中
    line: int = 0         # 命中行号，passed 时为 0
    snippet: str = ""     # 命中片段，passed 时为空


# ---------------------------------------------------------------------------
# RedFlagScanner
# ---------------------------------------------------------------------------

class RedFlagScanner:
    """14 条安全红线扫描器

    Usage::

        scanner = RedFlagScanner()
        result = scanner.scan(content, filename="SKILL.md")
        print(result.score, result.verdict)
    """

    # ---- 跳过目录（扫描目录时） ----
    _SKIP_DIRS = frozenset({
        "node_modules", ".git", "__pycache__",
        ".venv", "venv", "dist", "build",
    })

    # ---- 二进制 / 媒体扩展名 ----
    _SKIP_EXTS = frozenset({
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
        ".mp3", ".wav", ".ogg", ".mp4", ".mov", ".avi",
        ".ttf", ".woff", ".woff2", ".eot", ".pdf", ".zip", ".tar", ".gz",
    })

    # ---- 注释前缀 ----
    _COMMENT_PREFIXES = ("#", "//", "/*", "*")

    # ---- 即使在注释中也检查的规则 ----
    _ALWAYS_CHECK_RULES = frozenset({"RF06", "RF12"})

    # ---- 文件大小上限 ----
    _MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

    def __init__(self) -> None:
        """硬编码 14 条红线规则，不依赖外部配置文件。"""
        self.rules: list[dict] = [
            {
                "id": "RF01",
                "severity": "CRITICAL",
                "check": "content",
                "description": "curl/wget 管道到 shell",
                "details": "技能中包含 curl/wget 下载后管道传输给 shell 执行，存在 RCE 风险",
                "pattern": re.compile(
                    r'''(?:curl|wget)\s+(?:-[a-zA-Z]+\s+)*(?:['"]?(?:https?://|[a-zA-Z])[^\s|;&]+\s*\|\s*(?:ba)?sh|curl\s+.*\|\s*(?:ba)?sh)''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF02",
                "severity": "HIGH",
                "check": "content",
                "description": "向外部服务器发送数据 (POST/PUT)",
                "details": "技能中存在向外部服务器发送数据的 HTTP 请求代码",
                "pattern": re.compile(
                    r'''(?:fetch|axios\.(?:post|put)|XMLHttpRequest|httpx\.(?:post|put)|requests\.(?:post|put))\s*\(\s*['"](?!https?://(?:api\.)?(?:wttr\.in|openweathermap|weather\.gov|api\.github\.com|raw\.githubusercontent\.com))''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF03",
                "severity": "CRITICAL",
                "check": "content",
                "description": "硬编码凭证/Token/API Key",
                "details": "技能代码中硬编码了真实凭证或密钥，存在泄露风险",
                "pattern": re.compile(
                    r'''(?:api[_-]?key\s*[=:]\s*['"][A-Za-z0-9_]{8,}|token\s*[=:]\s*['"][A-Za-z0-9_]{8,}|password\s*[=:]\s*['"][^'"]{3,}|AUTH_TOKEN\s*=|API_SECRET\s*=|CREDENTIALS_FILE\s*=|bearer\s+['"][A-Za-z0-9_\-]{8,})''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF04",
                "severity": "CRITICAL",
                "check": "content",
                "description": "读取敏感系统路径",
                "details": "技能尝试访问 SSH/云服务/系统配置文件",
                "pattern": re.compile(
                    r'''(?:~/.ssh/|/etc/ssh/|\.ssh/id_|~/.aws/|/root/|/etc/shadow|/etc/passwd|~/.config/gh/hosts\.yml|~/.gcloud/|~/.azure/)''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF05",
                "severity": "CRITICAL",
                "check": "content",
                "description": "主动读取 Agent 身份/记忆文件",
                "details": "技能代码尝试读取 Agent 的身份标识或长期记忆文件",
                "pattern": re.compile(
                    r'''(?:readFile|read_file|open)\s*\(\s*['"](?:.*[/\\])?(MEMORY\.md|USER\.md|SOUL\.md|IDENTITY\.md)['"]''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF06",
                "severity": "CRITICAL",
                "check": "content",
                "description": "Base64 解码/编码操作",
                "details": "技能中使用 Base64 解码，可能用于隐藏恶意载荷",
                "pattern": re.compile(
                    r'''(?:base64\s+(?:-d|--decode|decode\b)|atob\s*\(|btoa\s*\()''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF07",
                "severity": "CRITICAL",
                "check": "content",
                "description": "动态代码执行",
                "details": "技能中使用 eval/exec/system 等动态执行函数",
                "pattern": re.compile(
                    r'''\beval\s*\(|\bexec\s*\([^l]|new\s+Function\s*\(|os\.system\s*\(|subprocess\.(?:call|check_output|run)\s*\(|execSync\s*\(|child_process\.exec\s*\(''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF08",
                "severity": "CRITICAL",
                "check": "content",
                "description": "提权操作或权限修改",
                "details": "技能尝试执行需要提权的系统操作",
                "pattern": re.compile(
                    r'''(?:sudo\s+(?!-)|chmod\s+[0-7]{3,4}\s|chown\s+\w+:\w+\s|privilege.*escalat|root.*access)''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF09",
                "severity": "HIGH",
                "check": "content",
                "description": "安装未声明的第三方软件包",
                "details": "技能尝试在运行时安装系统/语言包",
                "pattern": re.compile(
                    r'''(?:pip\d*\s+install\s+(?!-r|--requirement)|npm\s+(?:i|install)\s+(?!-g|--global|--save-dev)|gem\s+install\s|cargo\s+install\s|go\s+install\s|apt-get\s+install\s+-y|yum\s+install\s+-y|brew\s+install\s)''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF10",
                "severity": "HIGH",
                "check": "content",
                "description": "使用 IP 地址发起网络调用",
                "details": "技能中使用 IP 直连而非域名，可能指向恶意服务器",
                "pattern": re.compile(
                    r'''https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?/''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF11",
                "severity": "CRITICAL",
                "check": "content",
                "description": "混淆 / 编码混淆代码",
                "details": "技能包含混淆或编码后的代码，无法进行有效审查",
                "pattern": re.compile(
                    r'''eval\(.*(?:atob|base64|fromCharCode|unescape|decodeURI)\)|\\x[0-9a-fA-F]{2,}.*\\x[0-9a-fA-F]{2,}.*\\x[0-9a-fA-F]{2,}''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF12",
                "severity": "CRITICAL",
                "check": "content",
                "description": "提取浏览器 Cookie/Session",
                "details": "技能尝试读取或提取浏览器 Cookie 和会话信息",
                "pattern": re.compile(
                    r'''(?:cookies|session|localStorage|sessionStorage)\s*\.\s*(?:get|extract|steal|dump|read|export)|document\.cookie''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF13",
                "severity": "CRITICAL",
                "check": "filename",
                "description": "直接引用凭证文件名",
                "details": "文件名包含凭证/私钥等敏感文件引用",
                "pattern": re.compile(
                    r'''\b(?:id_rsa|id_ed25519|id_ecdsa|\.pem|private\.key|credentials\.json|secrets\.(?:yml|yaml|json|env))\b''',
                    re.IGNORECASE,
                ),
            },
            {
                "id": "RF14",
                "severity": "HIGH",
                "check": "content",
                "description": "递归/强制删除操作",
                "details": "技能中包含递归强制删除操作，可能导致数据丢失",
                "pattern": re.compile(
                    r'''(?:rm\s+(?:-[rR]f|--recursive.*--force)|shutil\.rmtree\s*\(|os\.remove\s*\(|fs\.rmdirSync\s*\(|del\s+/[fF]\s+/[sS]|Remove-Item\s+-Recurse\s+-Force)''',
                    re.IGNORECASE,
                ),
            },
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, content: str, filename: str = "SKILL.md") -> RedFlagResult:
        """扫描单文件内容，返回命中结果。

        Args:
            content: 文件完整文本内容
            filename: 文件名（用于 RF13 文件名规则检查）

        Returns:
            RedFlagResult 聚合结果
        """
        hits: list[RedFlagHit] = []
        seen: set[tuple[str, str]] = set()  # (rule_id, filename) 去重

        # ---- 文件名检查 (RF13) ----
        for rule in self.rules:
            if rule["check"] in ("filename", "filename_and_content"):
                if rule["pattern"].search(filename) or rule["pattern"].search(Path(filename).name):
                    key = (rule["id"], filename)
                    if key not in seen:
                        seen.add(key)
                        hits.append(RedFlagHit(
                            rule_id=rule["id"],
                            severity=rule["severity"],
                            description=rule["description"],
                            line=0,
                            snippet=f"文件名匹配: {filename}",
                        ))

        if not content:
            return self._build_result(hits)

        lines = content.split("\n")
        for line_num, line in enumerate(lines, start=1):
            trimmed = line.strip()
            if not trimmed:
                continue

            is_comment = trimmed.startswith(self._COMMENT_PREFIXES)

            for rule in self.rules:
                if rule["check"] not in ("content", "filename_and_content"):
                    continue

                # 注释行：仅检查 RF06 / RF12
                if is_comment and rule["id"] not in self._ALWAYS_CHECK_RULES:
                    continue

                if rule["pattern"].search(line):
                    key = (rule["id"], filename)
                    if key not in seen:
                        seen.add(key)
                        snippet_len = 100 if is_comment else 120
                        hits.append(RedFlagHit(
                            rule_id=rule["id"],
                            severity=rule["severity"],
                            description=rule["description"],
                            line=line_num,
                            snippet=trimmed[:snippet_len],
                        ))

        return self._build_result(hits)

    def scan_detail(self, content: str, filename: str = "SKILL.md") -> list[RedFlagRuleResult]:
        """逐条检测14条红线，返回每条规则的 PASS/FAIL 结果。

        与 scan() 不同，此方法返回全部 14 条规则的结果，
        而不仅仅是命中的规则。
        """
        lines = content.split("\n")
        results: list[RedFlagRuleResult] = []

        # 预计算哪些规则在内容中命中
        hit_rules: dict[str, tuple[int, str]] = {}  # rule_id -> (line, snippet)
        for i, line in enumerate(lines):
            trimmed = line.strip()
            line_num = i + 1

            # 注释跳过逻辑（与 scan 一致）
            is_comment = trimmed.startswith(self._COMMENT_PREFIXES)

            for rule in self.rules:
                rid = rule["id"]
                if rid in hit_rules:
                    continue  # 已命中，跳过

                if rule["check"] == "filename":
                    continue  # 文件名检查在此方法不适用

                # 注释行：仅 RF06, RF12 仍检查
                if is_comment and rid not in self._ALWAYS_CHECK_RULES:
                    continue

                if rule["pattern"].search(line):
                    hit_rules[rid] = (line_num, trimmed[:120])

        # 构建所有 14 条结果
        for rule in self.rules:
            rid = rule["id"]
            if rid in hit_rules:
                ln, snip = hit_rules[rid]
                results.append(RedFlagRuleResult(
                    rule_id=rid,
                    description=rule["description"],
                    severity=rule["severity"],
                    passed=False,
                    line=ln,
                    snippet=snip,
                ))
            else:
                results.append(RedFlagRuleResult(
                    rule_id=rid,
                    description=rule["description"],
                    severity=rule["severity"],
                    passed=True,
                ))

        return results

    def scan_directory(self, dir_path: str) -> RedFlagResult:
        """扫描整个技能目录，返回聚合结果。

        Args:
            dir_path: 技能目录的绝对/相对路径

        Returns:
            RedFlagResult 聚合所有文件的命中结果
        """
        all_hits: list[RedFlagHit] = []
        seen: set[tuple[str, str]] = set()  # (rule_id, rel_path) 去重

        for file_path in self._walk_dir(dir_path):
            rel_path = os.path.relpath(file_path, dir_path)
            filename = os.path.basename(file_path)
            ext = os.path.splitext(file_path)[1].lower()

            # 跳过二进制 / 媒体文件
            if ext in self._SKIP_EXTS:
                continue

            # 跳过超大文件
            try:
                if os.path.getsize(file_path) > self._MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            # 读取文件内容
            try:
                with open(file_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except (UnicodeDecodeError, OSError):
                continue

            # ---- 文件名检查 (RF13) ----
            for rule in self.rules:
                if rule["check"] in ("filename", "filename_and_content"):
                    if rule["pattern"].search(filename) or rule["pattern"].search(rel_path):
                        key = (rule["id"], rel_path)
                        if key not in seen:
                            seen.add(key)
                            all_hits.append(RedFlagHit(
                                rule_id=rule["id"],
                                severity=rule["severity"],
                                description=rule["description"],
                                line=0,
                                snippet=f"文件名匹配: {filename}",
                            ))

            if not content:
                continue

            lines = content.split("\n")
            for line_num, line in enumerate(lines, start=1):
                trimmed = line.strip()
                if not trimmed:
                    continue

                is_comment = trimmed.startswith(self._COMMENT_PREFIXES)

                for rule in self.rules:
                    if rule["check"] not in ("content", "filename_and_content"):
                        continue

                    if is_comment and rule["id"] not in self._ALWAYS_CHECK_RULES:
                        continue

                    if rule["pattern"].search(line):
                        key = (rule["id"], rel_path)
                        if key not in seen:
                            seen.add(key)
                            snippet_len = 100 if is_comment else 120
                            all_hits.append(RedFlagHit(
                                rule_id=rule["id"],
                                severity=rule["severity"],
                                description=rule["description"],
                                line=line_num,
                                snippet=trimmed[:snippet_len],
                            ))

        return self._build_result(all_hits)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_result(hits: list[RedFlagHit]) -> RedFlagResult:
        """从命中列表计算评分与判定。"""
        critical = [h for h in hits if h.severity == "CRITICAL"]
        high = [h for h in hits if h.severity == "HIGH"]

        # 评分
        if critical:
            score = 0
        else:
            score = max(0, 100 - len(high) * 15)

        # 判定
        if critical:
            verdict = "REJECT"
        elif high:
            verdict = "WARNING"
        else:
            verdict = "PASS"

        return RedFlagResult(
            passed=len(critical) == 0,
            total_hits=len(hits),
            critical_hits=len(critical),
            high_hits=len(high),
            hits=hits,
            score=score,
            verdict=verdict,
        )

    @classmethod
    def _walk_dir(cls, dir_path: str) -> list[str]:
        """递归遍历目录，跳过点文件/缓存/依赖目录。

        与 skill-vetter JS 版本行为一致：
          - 跳过所有以 ``.`` 开头的条目
          - 跳过 node_modules, __pycache__, .venv, venv, dist, build
        """
        file_list: list[str] = []
        if not os.path.isdir(dir_path):
            return file_list

        try:
            entries = sorted(os.scandir(dir_path), key=lambda e: e.name)
        except OSError:
            return file_list

        for entry in entries:
            # 跳过所有点文件 / 点目录 (.git, .env, .ds_store ...)
            if entry.name.startswith("."):
                continue

            if entry.is_dir():
                if entry.name in cls._SKIP_DIRS:
                    continue
                file_list.extend(cls._walk_dir(entry.path))
            elif entry.is_file():
                file_list.append(entry.path)

        return file_list
