from __future__ import annotations

import asyncio
import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionToolParam

from app.config import LLMConfig

logger = structlog.get_logger(__name__)


@dataclass
class LLMResult:
    """LLM流式响应结果，包含推理内容、生成文本和工具调用"""

    content: str  # 生成的最终文本内容
    reasoning_content: Optional[str] = None  # 推理/思考过程内容
    tool_calls: Optional[List[Dict[str, Any]]] = None  # 需要执行的工具调用列表
    usage: Optional[Any] = None  # Token使用情况

    @property
    def requires_tool_execution(self) -> bool:
        """是否需要执行工具调用"""
        return bool(self.tool_calls)


class LLMClient:
    """
    支持工具调用的流式LLM客户端
    推理内容和工具调用将返回给调用方处理
    """

    def __init__(self, config: LLMConfig):
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self.config = config

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((TimeoutError, Exception)),
    )
    async def acomplete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ChatCompletionToolParam]] = None,
    ) -> LLMResult:
        """
        流式完成方法，支持返回推理内容和工具调用给调用方处理

        Args:
            messages: 对话消息列表
            tools: 工具定义列表（可选）

        Returns:
            LLMResult: 包含推理内容、生成内容及工具调用信息的结果对象
        """
        logger.info(
            "llm.request",
            model=self.config.model,
            messages_count=len(messages),
            tools_count=len(tools) if tools else 0,
        )

        # 流式状态变量
        reasoning_content = ""
        answer_content = ""
        is_answering = False

        # 工具调用累积器: {index: {"id": ..., "function": {"name": ..., "arguments": ...}}}
        tool_calls_accumulator: Dict[int, Dict[str, Any]] = {}
        usage = None

        # 根据 dump_thinking 参数控制是否打印思考过程
        if self.config.dump_thinking:
            print("\n" + "=" * 20 + "思考过程" + "=" * 20 + "\n")

        try:
            # 创建流式请求
            completion = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    top_p=1.0,
                    presence_penalty=0.0,
                    frequency_penalty=0.0,
                    extra_body={"enable_thinking": self.config.enable_thinking},
                    stream=True,
                    stream_options={"include_usage": True},
                    tools=tools,
                    tool_choice="auto",
                    parallel_tool_calls=True,
                ),
                timeout=self.config.timeout,
            )

            # 处理流式响应
            async for chunk in completion:
                if chunk.usage is not None:
                    usage = chunk.usage

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # 累积工具调用信息（支持碎片化传输）
                if delta.tool_calls:
                    for tool_call_chunk in delta.tool_calls:
                        index = tool_call_chunk.index

                        # 初始化新的工具调用槽位
                        if index not in tool_calls_accumulator:
                            tool_calls_accumulator[index] = {
                                "id": tool_call_chunk.id,
                                "type": tool_call_chunk.type,
                                "function": {"name": "", "arguments": ""},
                            }

                        # 累积函数名
                        if tool_call_chunk.function and tool_call_chunk.function.name:
                            tool_calls_accumulator[index]["function"][
                                "name"
                            ] = tool_call_chunk.function.name

                        # 累积参数字符串（可能分多次接收）
                        if (
                            tool_call_chunk.function
                            and tool_call_chunk.function.arguments
                        ):
                            tool_calls_accumulator[index]["function"][
                                "arguments"
                            ] += tool_call_chunk.function.arguments

                # 收集并实时打印推理内容
                if (
                    hasattr(delta, "reasoning_content")
                    and delta.reasoning_content is not None
                ):
                    if not is_answering:  # 确保推理内容在回答之前
                        if self.config.dump_thinking:
                            print(delta.reasoning_content, end="", flush=True)
                        reasoning_content += delta.reasoning_content

                # 收集并实时打印回答内容
                if hasattr(delta, "content") and delta.content:
                    if not is_answering:
                        if self.config.dump_answer:
                            # 首次进入回答阶段，打印标题
                            print("\n" + "=" * 20 + "完整回复" + "=" * 20 + "\n")
                        is_answering = True
                    if self.config.dump_answer:
                        print(delta.content, end="", flush=True)
                    answer_content += delta.content

        except asyncio.TimeoutError as e:
            logger.error("llm.timeout")
            raise TimeoutError("LLM request timed out") from e

        # 获取Token消耗数据
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0

        print("\n")
        logger.info(
            "llm.response",
            chars=len(answer_content),
            reasoning_chars=len(reasoning_content),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        # 构建返回结果
        if tool_calls_accumulator:
            # 将累积的工具调用转换为有序列表
            sorted_indices = sorted(tool_calls_accumulator.keys())
            tool_calls_list = []

            for idx in sorted_indices:
                tool_call = tool_calls_accumulator[idx]
                # 验证参数是否为合法JSON
                try:
                    fixed_arguments = self._validate_and_fix_tool_arguments(
                        tool_call["function"]["name"],
                        tool_call["function"]["arguments"],
                    )
                    tool_call["function"]["arguments"] = fixed_arguments
                    json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError as e:
                    logger.error(
                        "llm.invalid_tool_arguments",
                        function_name=tool_call["function"]["name"],
                        arguments=tool_call["function"]["arguments"],
                        error=str(e),
                    )
                    raise ValueError(f"工具调用参数JSON解析失败: {e}")

                tool_calls_list.append(
                    {
                        "id": tool_call["id"],
                        "type": tool_call["type"],
                        "function": {
                            "name": tool_call["function"]["name"],
                            "arguments": tool_call["function"]["arguments"],
                        },
                    }
                )

            logger.info(
                "llm.tool_calls_detected",
                tool_calls_count=len(tool_calls_list),
                tool_names=[tc["function"]["name"] for tc in tool_calls_list],
            )

            # 返回推理内容 + 工具调用信息（不执行）
            return LLMResult(
                content=answer_content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls_list,
                usage=usage,
            )

        # 返回推理内容 + 最终生成内容
        return LLMResult(
            content=answer_content,
            reasoning_content=reasoning_content,
            tool_calls=None,
            usage=usage,
        )

    def _validate_and_fix_tool_arguments(
        self, function_name: str, arguments_str: str
    ) -> str:
        """
        验证并自动修复工具调用的参数字符串

        修复策略（按优先级）：
        1. 尝试直接解析，成功则返回原字符串
        2. 移除末尾多余的 {}、[]、"" 等污染字符
        3. 提取第一个完整的 JSON 对象
        4. 无法修复则抛出详细错误

        Args:
            function_name: 函数名称，用于日志记录
            arguments_str: 累积的参数字符串

        Returns:
            修复后的合法JSON字符串

        Raises:
            ValueError: 如果无法修复JSON格式错误
        """
        # 策略1: 直接尝试解析
        try:
            json.loads(arguments_str)
            return arguments_str  # 合法，直接返回
        except json.JSONDecodeError as original_error:
            logger.warning(
                "llm.tool_arguments_invalid",
                function_name=function_name,
                original_arguments=arguments_str[:200],
                error=str(original_error),
            )

            original_length = len(arguments_str)

            # 策略2: 移除末尾多余的空白和污染模式
            cleaned = arguments_str.strip()

            # 移除末尾连续的空对象、数组、引号
            # 例如: {...}{} -> {...}
            cleaned = re.sub(r"(?:{}\s*)+(?=\s*$)", "", cleaned)
            cleaned = re.sub(r"(?:\[\]\s*)+(?=\s*$)", "", cleaned)
            cleaned = re.sub(r'(?:""\s*)+(?=\s*$)', "", cleaned)

            # 再次尝试解析
            try:
                json.loads(cleaned)
                logger.info(
                    "llm.tool_arguments_fixed",
                    function_name=function_name,
                    fix_type="removed_trailing_garbage",
                    original_length=original_length,
                    cleaned_length=len(cleaned),
                )
                return cleaned
            except json.JSONDecodeError:
                pass

            # 策略3: 提取第一个完整的 JSON 对象
            if cleaned.startswith("{"):
                depth = 0
                in_string = False
                escape_next = False
                end_pos = -1

                for i, char in enumerate(cleaned):
                    if escape_next:
                        escape_next = False
                        continue

                    if char == "\\" and in_string:
                        escape_next = True
                        continue

                    if char == '"' and not in_string:
                        in_string = True
                    elif char == '"' and in_string:
                        in_string = False
                    elif not in_string:
                        if char == "{":
                            depth += 1
                        elif char == "}":
                            depth -= 1
                            if depth == 0 and end_pos == -1:
                                end_pos = i + 1
                                break

                if end_pos > 0:
                    first_json = cleaned[:end_pos]
                    try:
                        json.loads(first_json)
                        logger.info(
                            "llm.tool_arguments_fixed",
                            function_name=function_name,
                            fix_type="extracted_first_json_object",
                            original_length=original_length,
                            extracted_length=len(first_json),
                        )
                        return first_json
                    except json.JSONDecodeError:
                        pass

            # 策略4: 无法修复，抛出详细错误
            logger.error(
                "llm.tool_arguments_unfixable",
                function_name=function_name,
                original_arguments=arguments_str[:500],
                error=str(original_error),
            )

            raise ValueError(
                f"工具调用参数JSON解析失败 [函数: {function_name}]: {original_error}\n"
                f"参数预览: {arguments_str[:200]}{'...' if len(arguments_str) > 200 else ''}\n"
                f"参数长度: {len(arguments_str)}\n"
                f"请检查模型输出或工具定义是否正确。"
            )
