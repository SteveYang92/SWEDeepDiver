from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
import structlog

from .llm import LLMClient
from .tools import ToolRegistry, ToolError, ToolResult
from .prompt import main_agent_prompt
from util.font_style import GRAY_NORMAL, BLUE_BOLD, RESET, WHITE_BOLD

logger = structlog.get_logger(__name__)
tools = [
    {
        "type": "function",
        "function": {
            "name": "LoadKnowledge",
            "description": "加载与问题相关的诊断知识库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "knowledge_key": {
                        "type": "string",
                        "description": "知识库类型标识，例如：Login。",
                    }
                },
                "required": ["knowledge_key"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ProcessFile",
            "description": "对单个“原始文件”进行预处理（例如日志文件解密、脱敏、格式规范化；压缩包解包；图片文件信息读取等），并返回**处理后文件的相对路径**，可供后续 Grep、Inspect 使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "原始文件路径，可以是绝对路径或相对路径。通常来自用户输入或 Glob 工具的结果。",
                    },
                    "type": {
                        "type": "string",
                        "description": "文件类型，支持:log/trace/img/other",
                    },
                },
                "required": ["path", "type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "基于 ripgrep 能力的通用文本搜索工具，可在一个或多个路径（文件/目录）中搜索模式，适用于日志、trace、配置、代码等文本文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "description": "要搜索的路径列表。每一项可以是文件路径或目录路径。",
                        "items": {"type": "string"},
                    },
                    "pattern": {
                        "type": "string",
                        "description": "搜索模式（通常为正则表达式或简单字符串，具体取决于后端实现）。",
                    },
                    "glob": {
                        "type": "array",
                        "description": "文件过滤的 glob 模式列表（相对于每个 path）。例如 ['**/*.log', '**/*.trace']。为空或缺省时不过滤。",
                        "items": {"type": "string"},
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "是否忽略大小写，相当于 ripgrep 的 -i。默认 false。",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "是否大小写敏感，相当于 ripgrep 的 -s。通常不需要与 ignore_case 同时使用。",
                    },
                    "context": {
                        "type": "integer",
                        "description": "匹配行前后各返回多少行上下文，相当于 ripgrep 的 -C。",
                    },
                    "before_context": {
                        "type": "integer",
                        "description": "匹配行前返回多少行上下文，相当于 ripgrep 的 -B。如果同时设置了 context，则 before_context 优先级由实现决定。",
                    },
                    "after_context": {
                        "type": "integer",
                        "description": "匹配行后返回多少行上下文，相当于 ripgrep 的 -A。如果同时设置了 context，则 after_context 优先级由实现决定。",
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "最多返回的匹配条数上限，用于防止结果过大。",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "可选扩展字段，仅对带时间戳的日志有意义，格式为 'HH:mm:ss-HH:mm:ss'，按时间窗口过滤结果",
                    },
                },
                "required": ["paths", "pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "通用目录探索工具，基于 glob 模式遍历目录，帮助了解一个目录下有哪些文件/子目录，常用于问题目录或日志目录初探。",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "description": "要探索的根目录绝对路径或相对路径。",
                    },
                    "patterns": {
                        "type": "array",
                        "description": "glob 模式数组（相对于 root），用于限定返回哪些文件，例如 ['**/*.log', '**/*.trace']。为空或缺省时默认 ['**/*']。",
                        "items": {"type": "string"},
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "最大递归深度。根目录为深度 0，1 表示只遍历一层子目录。缺省表示使用默认值。",
                    },
                    "include_hidden": {
                        "type": "boolean",
                        "description": "是否包含隐藏文件和隐藏目录（以点号开头）。默认 false。",
                    },
                },
                "required": ["root"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Inspect",
            "description": "在给定时间窗口内扫描日志的错误密度和异常分布，用于缩小排查范围。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "日志文件路径，例如：/Volumes/var/log/2025-1-1.log",
                    },
                    "knowledge_key": {
                        "type": "array",
                        "description": '当前使用到的知识类型 key 列表，例如：["Login"]，可选。',
                        "items": {"type": "string"},
                    },
                    "pattern": {
                        "type": "string",
                        "description": "grep 兼容正则，用于统计的关键字/模式。",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "时间范围，格式为 HH:mm:ss-HH:mm:ss，可选。",
                    },
                },
                "required": ["path", "pattern", "knowledge_key"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "AskHuman",
            "description": "向用户请求补充/确认关键信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "要向用户提出的问题，需简洁明确。",
                    }
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Review",
            "description": "请求专家评审当前的证据链与结论。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "当前主要分析使用的日志文件路径。",
                    },
                    "issue": {"type": "string", "description": "用户问题的完整描述。"},
                    "ref_knowledge_keys": {
                        "type": "array",
                        "description": '当前引用的知识类型 key 列表，例如：["Login"]。',
                        "items": {"type": "string"},
                    },
                    "timeline_event": {
                        "type": "string",
                        "description": "当前完整的时间轴事件总结。",
                    },
                    "evidence_chain": {
                        "type": "string",
                        "description": "当前的证据链描述（根因->中间事件->表象问题）。",
                    },
                    "knowledge_evidence": {
                        "type": "string",
                        "description": "支持当前证据链和结论的知识库依据。",
                    },
                    "log_evidence": {
                        "type": "string",
                        "description": "支持当前证据链和结论的关键日志依据（时间+事件）。",
                    },
                    "code_analysis_evidence": {
                        "type": "string",
                        "description": "代码分析的关键证据（如有可填），可选。",
                    },
                    "other_basis": {
                        "type": "string",
                        "description": "其他依据（如有可填），可选。",
                    },
                    "conclusion": {"type": "string", "description": "你当前的结论。"},
                },
                "required": [
                    "path",
                    "issue",
                    "ref_knowledge_keys",
                    "timeline_event",
                    "evidence_chain",
                    "knowledge_evidence",
                    "log_evidence",
                    "conclusion",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": """读取任意文件。- 适用场景：
            - 完整异常堆栈可读取（例如已经从Grep得到了异常事件在日志中的行数，需要进一步查看完整堆栈）
            - 读取配置文件
            - 探测文件格式（必须指定limit）
            - 不适用场景：
            - 可以通过Grep/Inspect快速获取到完整信息的场景
            """,
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径",
                    },
                    "offset": {
                        "type": "number",
                        "description": "起始行数，默认0",
                    },
                    "limit": {
                        "type": "number",
                        "description": "读取的行数，不填则使用默认值",
                    },
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "AnalyzeCode",
            "description": "在日志或知识不足时，请求专家分析项目代码以补充证据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "analyze_target": {
                        "type": "string",
                        "description": "需要代码专家分析的目标，2-5 句话说明要搞清楚什么问题。",
                    },
                    "log": {
                        "type": "string",
                        "description": "与问题相关的关键日志（建议包含完整上下文，可帮助分析者全面了解要分析的问题）；每条日志包含时间 + TAG + 内容(多条日志用换行符分割)",
                    },
                    "stack_trace": {
                        "type": "string",
                        "description": "与问题相关的异常堆栈/代码调用栈等",
                    },
                },
                "required": ["analyze_target", "log"],
                "additionalProperties": False,
            },
        },
    },
]


class ReActAgentConfig:
    def __init__(
        self,
        max_steps: int = 30,
        allow_tool_hallucination: bool = False,
        dump_observation: bool = True,
        dump_tool_call: bool = True,
    ):
        self.max_steps = max_steps
        self.allow_tool_hallucination = allow_tool_hallucination
        self.dump_observation = dump_observation
        self.dump_tool_call = dump_tool_call


class ReActAgent:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        config: Optional[ReActAgentConfig] = None,
    ):
        self.llm = llm
        self.tools = tools
        self.config = config or ReActAgentConfig()
        self.trajectory_msgs: List[Dict[str, str]] = []

    async def aask(self, user_query: str) -> Dict[str, Any]:
        """
        Run a full ReAct loop for a single query.
        Returns:
          - final_answer: str
          - steps: list of dicts with thought/action/observation
        """

        # Seed conversation with system + user messages
        system = main_agent_prompt(self.tools.as_instructions())
        self.trajectory_msgs.append({"role": "system", "content": system})
        self.trajectory_msgs.append({"role": "user", "content": user_query})

        for step_idx in range(1, self.config.max_steps + 1):
            logger.info("react.step.start", step=step_idx)
            rsp = await self.llm.acomplete(messages=self.trajectory_msgs, tools=tools)

            if rsp.requires_tool_execution:
                # https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#anthropic-models-with-reasoning-tokens
                reasoning_content = rsp.reasoning_details.get("aggregated_text", "")
                reasoning_details = rsp.reasoning_details.get("chunks", [])
                self.trajectory_msgs.append(
                    {
                        "role": "assistant",
                        "content": rsp.content,
                        "reasoning_content": reasoning_content,
                        "reasoning_details": reasoning_details,
                        "tool_calls": rsp.tool_calls,
                    }
                )
                await self._call_tools(rsp.tool_calls)
                continue
            else:
                logger.info("react.step.final", step=step_idx)
                return {"final_answer": rsp.content.strip()}

        # Max steps reached: force finalization
        logger.warning("react.max_steps_reached", max_steps=self.config.max_steps)
        return {
            "final_answer": "I'm stopping due to step limit. Here is my best answer based on the progress above.",
        }

    async def _call_tools(self, tool_calls: List[Dict[str, Any]]):
        for tool_call in tool_calls:
            await self._call(tool_call)

    async def _call(self, tool_call):
        function_name = tool_call["function"]["name"]
        function_args = json.loads(tool_call["function"]["arguments"])
        # Validate tool
        try:
            tool = self.tools.get(function_name)
        except ToolError as e:
            logger.warning("react.unknown_tool", action=function_name)
            if not self.config.allow_tool_hallucination:
                # Nudge model and continue
                self.trajectory_msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": f"Tool is not available. Available: {', '.join(self.tools.list_names())}. Continue.",
                    }
                )
                return
            else:
                raise

        # Execute tool
        tool_result: str
        try:
            self._dump_toolcall(tool, function_args)
            result: ToolResult = await tool(function_args)
            tool_result = result.content
            self._dump_observation(tool, tool_result)
        except Exception as e:
            tool_result = f"Tool error: {e!r}"
            self._dump_observation(tool, tool_result)

        # Append tool result back to the loop
        self.trajectory_msgs.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result,
            }
        )

    def _dump_observation(self, tool, observation):
        if self.config.dump_observation and tool.dump_observation:
            print(
                f"\n{WHITE_BOLD}{tool.name}Response:\n{RESET}{GRAY_NORMAL}{observation}{RESET}"
            )
        else:
            print(f"\n{WHITE_BOLD}{tool.name}Response:\n{RESET}{GRAY_NORMAL}...{RESET}")

    def _dump_toolcall(self, tool, tool_input):
        if self.config.dump_tool_call:
            print(
                f"{WHITE_BOLD}{tool.name}:\n{RESET}{GRAY_NORMAL}{json.dumps(tool_input, ensure_ascii=False, indent=4)}{RESET}"
            )
