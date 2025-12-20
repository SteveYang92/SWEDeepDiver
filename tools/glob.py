import asyncio
import os
import pathlib
import subprocess
from typing import Any, List, Optional

from pydantic import Field

from react_core.tools import BaseTool, ToolInput, ToolResult, ToolError


class GlobInput(ToolInput):
    root: str = Field(description="要探索的根目录绝对路径或相对路径。")
    patterns: Optional[List[str]] = Field(
        default=None,
        description=(
            "glob 模式数组（相对于 root），例如 ['**/*.log', '**/*.trace']。"
            "若为 None 或空，则默认使用 ['**/*']。"
        ),
    )
    max_depth: Optional[int] = Field(
        default=3,
        description=(
            "最大递归深度。根目录为深度 0，1 表示只遍历一层子目录。"
            "若为 None，则不限制递归深度。"
        ),
    )
    include_hidden: bool = Field(
        default=False,
        description="是否包含隐藏文件和隐藏目录（以点号开头）。默认 false。",
    )


class GlobTool(BaseTool):
    name = "Glob"
    description = (
        "通用目录探索工具，基于 glob 模式遍历目录，帮助了解一个目录下有哪些文件/子目录，"
        "常用于问题目录或日志目录初探。"
    )
    input_model = GlobInput
    timeout_s = 8.0

    async def __call__(self, data: Any) -> ToolResult:
        inp = self.parse_input(data)

        # 校验pattern
        if inp.patterns:
            for pattern in inp.patterns:
                if pattern == "." or pattern == "..":
                    return ToolResult(
                        ok=False, content="Pattern `.` or `..` is not allowed!"
                    )

        root_path = pathlib.Path(inp.root)

        # 基础校验
        if not root_path.exists():
            return ToolResult(ok=False, content="Directory is not found")
        if not root_path.is_dir():
            return ToolResult(ok=False, content="Given root is not a directory")

        patterns = inp.patterns or ["**/*"]
        max_depth = inp.max_depth
        include_hidden = inp.include_hidden

        def is_hidden(p: pathlib.Path) -> bool:
            # 任一路径组件以 '.' 开头即认为是隐藏
            for part in p.parts:
                if part.startswith("."):
                    return True
            return False

        def depth_ok(p: pathlib.Path) -> bool:
            if max_depth is None:
                return True
            # root 深度为 0，子路径深度为其相对路径组件数
            try:
                rel = p.relative_to(root_path)
            except ValueError:
                # 不在 root 之下，防御性处理：直接过滤
                return False
            depth = len(rel.parts)
            return depth <= max_depth

        def walk() -> str:
            results = set()

            try:
                for pattern in patterns:
                    # 使用 rglob 实现 pattern 匹配
                    for p in root_path.rglob(pattern):
                        if not depth_ok(p):
                            continue
                        if not include_hidden and is_hidden(p.relative_to(root_path)):
                            continue
                        # 只输出相对路径
                        rel_str = str(p.relative_to(root_path))
                        results.add(rel_str)
            except PermissionError:
                return "Directory Access denied"
            except Exception as e:
                return f"Glob error: {e!r}"

            if not results:
                return ""  # 没有匹配项时返回空字符串，由上层决定如何解释

            # 统一排序输出，便于阅读和测试
            lines = sorted(results)
            return "\n".join(lines)

        try:
            loop = asyncio.get_running_loop()
            content = await asyncio.wait_for(
                loop.run_in_executor(None, walk),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError as e:
            raise ToolError("Glob timed out") from e

        # 若 walk 返回特定错误字符串，也视为 ok=False
        if content in ("Directory Access denied",):
            return ToolResult(ok=False, content=content)

        return ToolResult(ok=True, content=content)
