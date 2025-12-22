import asyncio
import os
import pathlib
import subprocess
from typing import Any, List, Optional

from pydantic import Field

from app.config import config
from app.processor import data_masker
from react_core.tool import BaseTool, ToolInput, ToolResult, ToolError
from util.grep_util import is_in_roots, apply_time_filter
from util.log_truncate import truncate_log_omit_edges


class GrepInput(ToolInput):
    paths: List[str] = Field(
        description="要搜索的路径列表。每一项可以是文件路径或目录路径。"
    )
    pattern: str = Field(
        description=(
            "搜索模式（通常为正则表达式或简单字符串，具体行为取决于后端 ripgrep 配置）。"
        )
    )
    glob: Optional[List[str]] = Field(
        default=None,
        description=(
            "文件过滤的 glob 模式列表（相对于每个 path）。"
            "例如 ['**/*.log', '**/*.trace']。为空或缺省时不过滤。"
        ),
    )
    ignore_case: Optional[bool] = Field(
        default=None,
        description="是否忽略大小写，相当于 ripgrep 的 -i。默认 False。",
    )
    case_sensitive: Optional[bool] = Field(
        default=None,
        description="是否大小写敏感，相当于 ripgrep 的 -s。通常不需要与 ignore_case 同时使用。",
    )
    context: Optional[int] = Field(
        default=None,
        description="匹配行前后各返回多少行上下文，相当于 ripgrep 的 -C。",
    )
    before_context: Optional[int] = Field(
        default=None,
        description="匹配行前返回多少行上下文，相当于 ripgrep 的 -B。",
    )
    after_context: Optional[int] = Field(
        default=None,
        description="匹配行后返回多少行上下文，相当于 ripgrep 的 -A。",
    )
    max_count: Optional[int] = Field(
        default=None,
        description="最多返回的匹配条数上限，用于防止结果过大，相当于 ripgrep 的 -m。",
    )
    time_range: Optional[str] = Field(
        default=None,
        description=(
            "日志时间窗口，仅对带时间戳的日志有意义，格式为 'HH:mm:ss-HH:mm:ss'。"
        ),
    )


class GrepTool(BaseTool):
    name = "Grep"
    description = (
        "基于 ripgrep 能力的通用文本搜索工具，可在一个或多个路径（文件/目录）中搜索模式，"
        "适用于日志、trace、配置、代码等文本文件。"
    )
    input_model = GrepInput
    timeout_s = 12.0

    def __init__(self):
        super().__init__()
        self.max_lines_of_grep_result = config.tools.grep.max_line_of_grep
        self.allow_dir = config.processed_file_dir
        self.grep_id = ""

    async def __call__(self, data: Any) -> ToolResult:
        inp = self.parse_input(data)

        if not inp.paths:
            return ToolResult(ok=False, content="No paths provided")

        for path in inp.paths:
            if not is_in_roots(p=path, root_dirs=[self.allow_dir]):
                return ToolResult(ok=False, content=f"[tool] path not allowed:{path}")

        # 构建 ripgrep 命令
        cmd = [
            "rg",
            "-P",
            "--line-number",
            "--color",
            "never",
        ]

        # 大小写选项
        if inp.ignore_case is True:
            cmd.append("--ignore-case")
        if inp.case_sensitive is True:
            cmd.append("--case-sensitive")

        # 上下文选项
        if inp.context is not None:
            cmd.extend(["-C", str(inp.context)])
        if inp.before_context is not None:
            cmd.extend(["-B", str(inp.before_context)])
        if inp.after_context is not None:
            cmd.extend(["-A", str(inp.after_context)])

        # 最大匹配数
        if inp.max_count is not None:
            cmd.extend(["-m", str(inp.max_count)])

        # glob 过滤
        if inp.glob:
            for g in inp.glob:
                cmd.extend(["--glob", g])

        # pattern 和 paths
        cmd.append(inp.pattern)
        cmd.extend(inp.paths)

        # 注意：本示例中不对 inp.time_range 做额外处理
        # 如果你的后端实现支持，可扩展为根据 time_range 对结果进行二次过滤

        def run_rg() -> ToolResult:
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
            except FileNotFoundError:
                return ToolResult(
                    ok=False, content="Grep error: 'rg' (ripgrep) not found in PATH"
                )
            except Exception as e:
                return ToolResult(ok=False, content=f"Grep error: {e!r}")

            # ripgrep 约定：
            # - 0: 有匹配且正常结束
            # - 1: 无匹配
            # - 2: 错误
            if proc.returncode == 0:
                return ToolResult(ok=True, content=proc.stdout)
            elif proc.returncode == 1:
                # 无匹配也视为正常，只是结果为空
                return ToolResult(ok=True, content=proc.stdout or "")
            else:
                msg = proc.stderr.strip() or f"rg exited with code {proc.returncode}"
                return ToolResult(ok=False, content=f"Grep error: {msg}")

        try:
            loop = asyncio.get_running_loop()
            result: ToolResult = await asyncio.wait_for(
                loop.run_in_executor(None, run_rg),
                timeout=self.timeout_s,
            )
            if result.ok and result.content is not None:
                res = result.content
                # 应用时间范围过滤（如果提供）
                if inp.time_range and res:
                    res = apply_time_filter(res, inp.time_range)
                # 数据脱敏
                if res:
                    res = data_masker.mask(res)
                # 日志过长处理
                if res:
                    res = truncate_log_omit_edges(res, self.max_lines_of_grep_result)
                return ToolResult(ok=True, content=res)

            return result
        except asyncio.TimeoutError as e:
            raise ToolError("Grep timed out") from e

        return result
