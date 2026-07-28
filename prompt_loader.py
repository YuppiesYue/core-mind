"""Build the agent system prompt from prompt fragments and Skill metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import frontmatter
except ImportError:  # pragma: no cover - local fallback for minimal environments
    frontmatter = None


SERVICE_ROOT = Path(__file__).resolve().parent
PROMPT_DIR = SERVICE_ROOT / "prompts"
SKILLS_ROOT = SERVICE_ROOT / "skills"

PROMPT_FILES = (
    "identity.md",
    "skill_routing.md",
    "fallback_policy.md",
    "output_quality.md",
    "stream_protocol.md",
    "card_policy.md",
)

VALID_SKILL_TYPES = {"entrypoint", "internal", "data"}
_SERVICE_TIMEZONE = ZoneInfo("Asia/Shanghai")
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    skill_type: str
    path: Path


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if frontmatter is not None:
        return dict(frontmatter.loads(text).metadata)

    if not text.startswith("---"):
        return {}
    _, _, rest = text.partition("---")
    header, sep, _ = rest.partition("---")
    if not sep:
        return {}
    metadata: dict[str, str] = {}
    for raw_line in header.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata


def _normalize_skill_type(value: Any) -> str:
    skill_type = str(value or "entrypoint").strip().lower()
    if skill_type in VALID_SKILL_TYPES:
        return skill_type
    return "entrypoint"


def list_skill_metadata(skills_root: Path = SKILLS_ROOT) -> list[SkillMetadata]:
    if not skills_root.exists():
        return []

    items: list[SkillMetadata] = []
    for path in sorted(skills_root.rglob("SKILL.md")):
        metadata = _parse_frontmatter(path)
        name = str(metadata.get("name") or "").strip()
        description = str(metadata.get("description") or "").strip()
        if not name or not description:
            continue
        items.append(
            SkillMetadata(
                name=name,
                description=description,
                skill_type=_normalize_skill_type(metadata.get("type")),
                path=path,
            )
        )
    return items


def render_skill_catalog(skills: list[SkillMetadata] | None = None) -> str:
    skills = list_skill_metadata() if skills is None else skills
    groups = {
        "entrypoint": [item for item in skills if item.skill_type == "entrypoint"],
        "internal": [item for item in skills if item.skill_type == "internal"],
        "data": [item for item in skills if item.skill_type == "data"],
    }

    lines = [
        "## 动态 Skill 目录",
        "",
        "以下目录由 `agent_service/skills/**/SKILL.md` 的 front matter 自动生成。",
        "路由时优先根据 Skill 的 `description` 判断是否适合当前用户问题；详细流程以对应 `SKILL.md` 正文为准。",
        "",
    ]

    if groups["entrypoint"]:
        lines.extend(["### 可入口 Skills（type=entrypoint）", ""])
        lines.extend(f"- `{item.name}`：{item.description}" for item in groups["entrypoint"])
        lines.append("")

    if groups["internal"]:
        lines.extend(["### 内部 Skills（type=internal）", ""])
        lines.extend(f"- `{item.name}`：{item.description}" for item in groups["internal"])
        lines.append("")

    if groups["data"]:
        lines.extend(["### 数据 Skills（type=data）", ""])
        lines.extend(f"- `{item.name}`：{item.description}" for item in groups["data"])
        lines.append("")

    if not skills:
        lines.append("当前未发现可用 Skill。")

    return "\n".join(lines).strip()


def _read_prompt_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def render_time_context(now: datetime | None = None) -> str:
    """Render request-time context shared by routing, Skills, and tools."""
    current = now.astimezone(_SERVICE_TIMEZONE) if now else datetime.now(_SERVICE_TIMEZONE)
    weekday = _WEEKDAYS[current.weekday()]
    return "\n".join(
        [
            "## 当前时间上下文",
            f"当前日期：{current:%Y-%m-%d}（{weekday}）。",
            "处理相对日期、月份和年份时必须以该日期为基准；用户明确写出的年份优先。",
            "用户只写月份而未写年份时，先按当前年份理解；需要精确数据时再以工具返回的可用统计期为准。",
        ]
    )


def build_runtime_system_prompt(
    base_prompt: str,
    *,
    now: datetime | None = None,
) -> str:
    """Append fresh time context without mutating the static prompt fragments."""
    parts = [str(base_prompt or "").strip(), render_time_context(now)]
    return "\n\n".join(part for part in parts if part).strip()


def load_agent_system_prompt() -> str:
    parts: list[str] = []
    for filename in PROMPT_FILES:
        text = _read_prompt_file(PROMPT_DIR / filename)
        if text:
            parts.append(text)
        if filename == "skill_routing.md":
            parts.append(render_skill_catalog())
    return "\n\n".join(part for part in parts if part).strip()
