from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
import structlog

from .llm import LLMClient
from .tool import ToolRegistry, ToolError, ToolResult
from .prompt import main_agent_prompt
from util.font_style import GRAY_NORMAL, BLUE_BOLD, RESET, WHITE_BOLD

logger = structlog.get_logger(__name__)


class ReActAgentConfig:
    def __init__(
        self,
        max_steps: int = 30,
        allow_tool_hallucination: bool = False,
        dump_observation: bool = True,
        dump_tool_call: bool = True,
        terminate_tool_name: str = "",
    ):
        self.max_steps = max_steps
        self.allow_tool_hallucination = allow_tool_hallucination
        self.dump_observation = dump_observation
        self.dump_tool_call = dump_tool_call
        self.terminate_tool_name = terminate_tool_name


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
        self.should_finish = False

    async def aask(self, user_query: str) -> Dict[str, Any]:
        """
        Run a full ReAct loop for a single query.
        Returns:
          - final_answer: str
          - steps: list of dicts with thought/action/observation
        """

        # Rest state
        self.should_finish = False

        # Seed conversation with system + user messages
        system = main_agent_prompt()
        self.trajectory_msgs.append({"role": "system", "content": system})
        self.trajectory_msgs.append({"role": "user", "content": user_query})

        for step_idx in range(1, self.config.max_steps + 1):
            logger.info("react.step.start", step=step_idx)
            rsp = await self.llm.acomplete(
                messages=self.trajectory_msgs, tools=self.tools.as_llm_tools()
            )

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
            elif not self.should_finish:
                logger.warning("react.step.no_toocall", step=step_idx)
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

        if self._is_terminate_tool_call(function_name):
            logger.info("react.terminate")
            self.should_finish = True

    def _is_terminate_tool_call(self, tool_name):
        return self.config.terminate_tool_name == tool_name

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
