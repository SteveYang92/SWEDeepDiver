from pathlib import Path
import re
from typing import Dict, List, Optional
from pydantic import Field
from app.config import config
from react_core.llm import LLMClient
from react_core.tool import BaseTool, ToolInput, ToolResult
from util.grep_util import apply_time_filter, grep_file
from util.log_sorter import sort_logs_with_stacktrace
from util.log_truncate import truncate_line, truncate_log_omit_edges
from util.font_style import GRAY_NORMAL, RESET
from util.file_util import read_content
from app.processor import data_masker
import structlog

logger = structlog.get_logger(__name__)

INSPECT_LOG_PROMPT_FILE = config.prompt_dir / "inspector.md"


def _dump_log(category, res):
    logger.debug("tool.inspectlog", category=category, line_count=len(res.splitlines()))
    print(f"\n{GRAY_NORMAL}{res}{RESET}")


class InspectInput(ToolInput):
    path: str = Field(description="日志文件路径")
    knowledge_key: Optional[list[str]] = Field(
        default=[], description="当前使用到的知识类型 key 列表"
    )
    pattern: Optional[str] = Field(description="grep 兼容正则，用于统计的关键字/模式。")
    time_range: Optional[str] = Field(
        default=None,  # 默认值为None，表示不启用时间过滤
        description="时间范围，格式为 HH:mm:ss-HH:mm:ss",
    )


class InspectTool(BaseTool):
    name = "Inspect"
    description = (
        "在给定时间窗口内扫描日志的错误密度/异常分布/事件分布，用于缩小排查范围。"
    )
    input_model = InspectInput

    def __init__(self):
        super().__init__()
        self.llm = LLMClient(config.inspector.llm)
        self.max_lines_of_grep_result = config.inspector.max_line_of_grep
        self.allow_dir = config.processed_file_dir

    async def __call__(self, data) -> ToolResult:
        inp = self.parse_input(data)
        logs = []

        if config.inspector.pattern.env_pattern:
            logs.append(self._global_info(inp, config.inspector.pattern.env_pattern))

        if config.inspector.pattern.exception_pattern:
            logs.append(
                self._exception_info(inp, config.inspector.pattern.exception_pattern)
            )

        if config.inspector.pattern.error_pattern:
            logs.append(self._error_info(inp, config.inspector.pattern.error_pattern))

        if config.inspector.pattern.context_pattern:
            logs.append(
                self._context_info(inp, config.inspector.pattern.context_pattern)
            )

        if inp.pattern:
            logs.append(self._biz_related_info(inp, inp.pattern))
        # 超长截断
        lines = "\n".join(logs).splitlines()
        truncated_lines = [truncate_line(line) for line in lines]
        logger.debug(
            "tool.inspectlog.dump", category="Total", line_count=len(truncated_lines)
        )
        # 排序
        sorted_log = sort_logs_with_stacktrace("\n".join(truncated_lines))
        if sorted_log:
            return ToolResult(ok=True, content=await self._inspect_log(sorted_log))
        return ToolResult(ok=True, content="")

    async def _inspect_log(self, log: str) -> str:
        """
        inspect log
        """
        logger.info("llm.insepectlog.start")
        trajectory_msgs: List[Dict[str, str]] = []
        trajectory_msgs.append({"role": "system", "content": self._get_sys_prompt()})
        trajectory_msgs.append({"role": "user", "content": log})
        rsp = await self.llm.acomplete(messages=trajectory_msgs)
        return rsp.content

    def _get_sys_prompt(self) -> str:
        return read_content(INSPECT_LOG_PROMPT_FILE)

    def _global_info(self, inp, pattern) -> str:
        res = grep_file(
            path=inp.path,
            pattern=pattern,
            before=0,
            after=0,
            allow_dirs=[self.allow_dir],
        )
        if res:
            res = data_masker.mask(res)
        if res:
            res = truncate_log_omit_edges(res, self.max_lines_of_grep_result)
        _dump_log("Env", res)
        return res

    def _context_info(self, inp, pattern) -> str:
        res = grep_file(
            path=inp.path,
            pattern=pattern,
            before=0,
            after=0,
            allow_dirs=[self.allow_dir],
        )
        if inp.time_range and res:
            res = apply_time_filter(res, inp.time_range)
        if res:
            res = data_masker.mask(res)
        if res:
            res = truncate_log_omit_edges(res, self.max_lines_of_grep_result)
        _dump_log("Context", res)
        return res

    def _exception_info(self, inp, pattern) -> str:
        res = grep_file(
            path=inp.path,
            pattern=pattern,
            before=2,
            after=2,
            allow_dirs=[self.allow_dir],
        )
        if res:
            res = data_masker.mask(res)
        if res:
            res = truncate_log_omit_edges(res, self.max_lines_of_grep_result)
        _dump_log("Exception", res)
        return res

    def _error_info(self, inp, pattern) -> str:
        res = grep_file(
            path=inp.path,
            pattern=pattern,
            before=0,
            after=0,
            allow_dirs=[self.allow_dir],
        )
        if res:
            res = data_masker.mask(res)
        if res:
            res = truncate_log_omit_edges(res, self.max_lines_of_grep_result)
        _dump_log("Error", res)
        return res

    def _biz_related_info(self, inp, pattern) -> str:
        if not pattern:
            return ""
        res = grep_file(
            path=inp.path,
            pattern=pattern,
            before=0,
            after=0,
            allow_dirs=[self.allow_dir],
        )
        if inp.time_range and res:
            res = apply_time_filter(res, inp.time_range)
        if res:
            res = data_masker.mask(res)
        if res:
            res = truncate_log_omit_edges(res, self.max_lines_of_grep_result)
        _dump_log("Biz", res)
        return res
