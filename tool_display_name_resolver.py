"""Resolve display metadata for AgentScope tools and skills."""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ToolDisplayNameResolver:
    """Resolve Chinese display names for tools and concrete Skill calls."""

    SKILL_TOOL_NAME_CN = "技能加载"

    def __init__(self) -> None:
        self._tool_name_cn_cache: dict[str, str] = {}
        self._skill_info_cache: dict[str, dict[str, str]] = {}

    def clear(self) -> None:
        self._tool_name_cn_cache.clear()
        self._skill_info_cache.clear()

    @property
    def has_tool_names(self) -> bool:
        return bool(self._tool_name_cn_cache)

    @property
    def has_skill_info(self) -> bool:
        return bool(self._skill_info_cache)

    @staticmethod
    def is_skill_tool(tool_name: str) -> bool:
        return tool_name == "Skill" or tool_name.endswith("__Skill")

    async def refresh(self, toolkit: Any) -> None:
        await self.refresh_tool_names(toolkit)
        await self.refresh_skill_info(toolkit)

    async def refresh_tool_names(self, toolkit: Any) -> None:
        if toolkit is None:
            return

        try:
            schemas = await toolkit.get_tool_schemas()
        except TypeError:
            schemas = toolkit.get_tool_schemas()
        except Exception as exc:
            logger.debug("Failed to refresh tool Chinese names: %s", exc)
            return

        self.update_tool_names_from_schemas(schemas)
        await self.refresh_mcp_tool_titles(toolkit)

    def update_tool_names_from_schemas(self, schemas: Any) -> None:
        for schema in schemas or []:
            pair = self._extract_tool_name_cn_from_schema(schema)
            if pair:
                tool_name, name_cn = pair
                for alias in self._tool_name_aliases(tool_name):
                    self._tool_name_cn_cache[alias] = name_cn

    async def refresh_mcp_tool_titles(self, toolkit: Any) -> None:
        if toolkit is None:
            return

        for group in getattr(toolkit, "tool_groups", []) or []:
            for client in getattr(group, "mcps", []) or []:
                try:
                    tools = await client.list_tools()
                except TypeError:
                    tools = client.list_tools()
                except Exception as exc:
                    logger.debug(
                        "Failed to refresh MCP tool titles for %s: %s",
                        getattr(client, "name", "unknown"),
                        exc,
                    )
                    continue

                self.update_tool_names_from_registered_tools(tools)

    def update_tool_names_from_registered_tools(self, tools: Any) -> None:
        for tool in tools or []:
            tool_name = self._first_non_empty_text(getattr(tool, "name", ""))
            raw_tool = getattr(tool, "_tool", None)
            title = self._first_non_empty_text(getattr(raw_tool, "title", ""))
            if not tool_name or not self._looks_like_cn_name(title):
                continue
            for alias in self._tool_name_aliases(tool_name):
                self._tool_name_cn_cache[alias] = title

    async def refresh_skill_info(self, toolkit: Any) -> None:
        if toolkit is None:
            return

        get_available_skills = getattr(toolkit, "_get_available_skills", None)
        if get_available_skills is None:
            return

        try:
            skills = await get_available_skills()
        except TypeError:
            skills = get_available_skills()
        except Exception as exc:
            logger.debug("Failed to refresh skill info: %s", exc)
            return

        for fallback_name, skill in (skills or {}).items():
            skill_name = self._first_non_empty_text(
                getattr(skill, "name", ""),
                str(fallback_name),
            )
            if not skill_name:
                continue
            self._skill_info_cache[skill_name] = {
                "skill_name": skill_name,
                "skill_name_cn": self._derive_skill_name_cn(skill, skill_name),
            }

    def tool_name_cn(self, tool_name: str) -> str:
        if not tool_name:
            return ""
        if self.is_skill_tool(tool_name):
            return self.SKILL_TOOL_NAME_CN
        for alias in self._tool_name_aliases(tool_name):
            name_cn = self._tool_name_cn_cache.get(alias)
            if name_cn:
                return name_cn
        return tool_name

    def extract_skill_name_from_args(self, args: str) -> str:
        payload = self._json_loads_maybe(args)
        if not isinstance(payload, dict):
            return ""
        return self._first_non_empty_text(
            payload.get("skill"),
            payload.get("skill_name"),
            payload.get("name"),
        )

    def skill_info_from_args(self, tool_name: str, args: str) -> dict[str, str]:
        if not self.is_skill_tool(tool_name):
            return {}
        skill_name = self.extract_skill_name_from_args(args)
        return self.skill_info(skill_name)

    def skill_info(self, skill_name: str) -> dict[str, str]:
        if not skill_name:
            return {}
        return self._skill_info_cache.get(
            skill_name,
            {
                "skill_name": skill_name,
                "skill_name_cn": skill_name,
            },
        )

    @classmethod
    def _extract_tool_name_cn_from_schema(cls, schema: Any) -> tuple[str, str] | None:
        if not isinstance(schema, dict):
            return None

        fn = cls._schema_function(schema)
        tool_name = cls._first_non_empty_text(
            fn.get("name"),
            schema.get("name"),
        )
        if not tool_name:
            return None

        metadata = fn.get("metadata")
        if not isinstance(metadata, dict):
            metadata = schema.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        name_cn = cls._first_non_empty_text(
            fn.get("tool_name_cn"),
            fn.get("name_cn"),
            fn.get("display_name_cn"),
            schema.get("tool_name_cn"),
            schema.get("name_cn"),
            schema.get("display_name_cn"),
            metadata.get("tool_name_cn"),
            metadata.get("name_cn"),
            metadata.get("display_name_cn"),
        )
        if not name_cn:
            title = cls._first_non_empty_text(
                fn.get("title"),
                schema.get("title"),
                metadata.get("title"),
            )
            if cls._looks_like_cn_name(title):
                name_cn = title
        if not name_cn:
            name_cn = cls._derive_tool_name_cn_from_description(
                cls._first_non_empty_text(
                    fn.get("description"),
                    schema.get("description"),
                ),
            )
        if not name_cn:
            name_cn = tool_name

        return tool_name, name_cn

    @staticmethod
    def _tool_name_aliases(tool_name: str) -> tuple[str, ...]:
        if "__" not in tool_name:
            return (tool_name,)
        short_name = tool_name.rsplit("__", 1)[-1]
        if short_name == tool_name:
            return (tool_name,)
        return (tool_name, short_name)

    @staticmethod
    def _schema_function(schema: dict[str, Any]) -> dict[str, Any]:
        fn = schema.get("function")
        return fn if isinstance(fn, dict) else schema

    @staticmethod
    def _first_non_empty_text(*values: Any) -> str:
        for value in values:
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _looks_like_cn_name(text: str) -> bool:
        if not text:
            return False
        return any(0x4E00 <= ord(ch) <= 0x9FFF for ch in text)

    @classmethod
    def _derive_tool_name_cn_from_description(cls, description: str) -> str:
        text = (description or "").strip()
        if not text:
            return ""

        first_line = text.splitlines()[0].strip()
        first_sentence = first_line
        for sep in ("。", "；", ";", ".", "\n"):
            if sep in first_sentence:
                first_sentence = first_sentence.split(sep, 1)[0].strip()
        tool_marker = first_sentence.find("工具")
        if 0 < tool_marker <= 20:
            candidate = first_sentence[:tool_marker].strip(" ，,")
            if cls._looks_like_cn_name(candidate):
                return candidate
        if not cls._looks_like_cn_name(first_sentence):
            return ""
        if len(first_sentence) > 60:
            return ""
        return first_sentence

    @classmethod
    def _derive_skill_name_cn(cls, skill: Any, fallback_name: str) -> str:
        name_cn = cls._first_non_empty_text(
            getattr(skill, "skill_name_cn", ""),
            getattr(skill, "name_cn", ""),
            getattr(skill, "display_name_cn", ""),
        )
        if name_cn:
            return name_cn

        markdown = cls._first_non_empty_text(getattr(skill, "markdown", ""))
        for line in markdown.splitlines():
            title = line.strip()
            if not title.startswith("# "):
                continue
            title = title[2:].strip()
            if cls._looks_like_cn_name(title):
                return title

        return fallback_name

    @staticmethod
    def _json_loads_maybe(value: Any) -> Any:
        if not isinstance(value, str):
            return value

        text = value.strip()
        if not text:
            return None

        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except (json.JSONDecodeError, TypeError):
                return None

        return None
