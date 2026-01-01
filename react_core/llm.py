from __future__ import annotations

import asyncio
import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import httpx
import openai
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
from .tool import ToolError

logger = structlog.get_logger(__name__)


@dataclass
class LLMResult:
    """LLM响应结果，包含推理详情、生成文本和工具调用信息。"""

    content: str
    reasoning_details: Dict[str, Any] = field(default_factory=dict)
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Any] = None

    @property
    def requires_tool_execution(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    """
    支持推理内容提取与工具调用的LLM客户端，可按需切换流式/非流式传输。
    """

    retryable_exceptions = (
        TimeoutError,  # 请求超时
        ConnectionError,  # 连接失败
        httpx.TimeoutException,  # httpx超时
        openai.APIConnectionError,  # OpenAI 连接错误
        openai.APITimeoutError,  # OpenAI 超时
        openai.RateLimitError,  # OpenAI 限流
    )

    def __init__(self, config: LLMConfig):
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self.config = config
        self._default_stream = config.stream

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type(retryable_exceptions),
    )

    # TODO 不同的LLM Provider completion实现存在差异，目前还不支持扩展，后续增加LLM Provider适配层
    async def acomplete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ChatCompletionToolParam]] = None,
        stream: Optional[bool] = None,
    ) -> LLMResult:
        """
        Args:
            messages: 对话消息列表
            tools: 工具定义列表
            stream: 是否启用流式传输（默认读取配置）
        """
        tools = tools or None
        stream = self._default_stream if stream is None else stream

        logger.info(
            "llm.request",
            model=self.config.model,
            messages_count=len(messages),
            tools_count=len(tools) if tools else 0,
            stream=stream,
        )

        request_args = self._build_request_args(messages, tools)

        if stream:
            return await self._stream_completion(request_args)
        return await self._non_stream_completion(request_args)

    async def _stream_completion(self, request_args: Dict[str, Any]) -> LLMResult:
        reasoning_details: Dict[str, Any] = {}
        tool_calls_accumulator: Dict[int, Dict[str, Any]] = {}
        answer_fragments: List[str] = []
        answer_started = False
        usage = None

        self._maybe_print_header("思考过程", self.config.dump_thinking)

        try:
            completion = await asyncio.wait_for(
                self.client.chat.completions.create(
                    **request_args,
                    stream=True,
                    stream_options={"include_usage": True},
                ),
                timeout=self.config.timeout,
            )

            async for chunk in completion:
                usage = chunk.usage or usage
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # 推理详情
                raw_reasoning_details = self._extract_reasoning(delta)
                if raw_reasoning_details:
                    self._accumulate_reasoning_details_chunk(
                        reasoning_details, raw_reasoning_details
                    )
                    if self.config.dump_thinking and not answer_started:
                        print(
                            self._render_reasoning_for_console(raw_reasoning_details),
                            end="",
                            flush=True,
                        )

                # 工具调用
                if delta.tool_calls:
                    for call_chunk in delta.tool_calls:
                        self._accumulate_tool_call_chunk(
                            tool_calls_accumulator, call_chunk
                        )

                # 文本内容
                text_chunk = self._extract_text(delta)
                if text_chunk:
                    if not answer_started:
                        answer_started = True
                        self._maybe_print_header("完整回复", self.config.dump_answer)
                    if self.config.dump_answer:
                        print(text_chunk, end="", flush=True)
                    answer_fragments.append(text_chunk)

        except asyncio.TimeoutError as exc:
            logger.error("llm.timeout")
            raise TimeoutError("LLM request timed out") from exc
        finally:
            if (
                self.config.dump_thinking or self.config.dump_answer
            ) and answer_fragments:
                print()

        content = "".join(answer_fragments)
        tool_calls_list = (
            [tool_calls_accumulator[idx] for idx in sorted(tool_calls_accumulator)]
            if tool_calls_accumulator
            else None
        )
        finalized_tools = (
            self._finalize_tool_calls(tool_calls_list) if tool_calls_list else None
        )

        self._log_response(content, reasoning_details, usage)
        return LLMResult(
            content=content,
            reasoning_details=reasoning_details,
            tool_calls=finalized_tools,
            usage=usage,
        )

    async def _non_stream_completion(self, request_args: Dict[str, Any]) -> LLMResult:
        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(**request_args),
                timeout=self.config.timeout,
            )
        except asyncio.TimeoutError as exc:
            logger.error("llm.timeout")
            raise TimeoutError("LLM request timed out") from exc

        if not response.choices:
            raise RuntimeError("LLM returned no choices")

        message = response.choices[0].message
        reasoning_details: Dict[str, Any] = {}
        raw_reasoning_details = self._extract_reasoning(message)
        if raw_reasoning_details:
            self._accumulate_reasoning_details_chunk(
                reasoning_details, raw_reasoning_details
            )

        if self.config.dump_thinking and raw_reasoning_details:
            self._maybe_print_header("思考过程", True)
            print(self._render_reasoning_for_console(raw_reasoning_details), flush=True)

        content = self._extract_text(message)
        if self.config.dump_answer and content:
            self._maybe_print_header("完整回复", True)
            print(content, flush=True)

        tool_calls = self._finalize_tool_calls(message.tool_calls or None)

        self._log_response(content, reasoning_details, response.usage)
        return LLMResult(
            content=content,
            reasoning_details=reasoning_details,
            tool_calls=tool_calls,
            usage=response.usage,
        )

    def _extract_reasoning(self, data):
        if hasattr(data, "reasoning_details") and data.reasoning_details is not None:
            return data.reasoning_details
        if hasattr(data, "reasoning_content") and data.reasoning_content is not None:
            return data.reasoning_content

    def _build_request_args(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ChatCompletionToolParam]],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": 1.0,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
            "extra_body": self._build_extra_body(),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
        return payload

    def _build_extra_body(self) -> Dict[str, Any]:
        if self.config.enable_thinking:
            return {
                "enable_thinking": True,  # Alibaba Qwen
                "thinking": {"type": "enabled"},  # DeepSeek
                "reasoning": {"enabled": True, "effort": "high"},  # OpenRouter
            }
        return {}

    def _accumulate_reasoning_details_chunk(
        self, store: Dict[str, Any], payload: Any
    ) -> None:
        if payload is None:
            return

        store.setdefault("chunks", [])
        store.setdefault("aggregated_text", "")

        def _merge_block_by_index(store: Dict[str, Any], block: Dict[str, Any]) -> bool:
            """
            对于带有 index 的 reasoning block，如果 chunks 中已经存在同 index、同 type 的块，
            则进行字段级合并，而不是新增一条记录。

            返回 True 表示已合并（不需要再 append），False 表示未找到可合并目标。
            """
            index = block.get("index", None)
            if index is None:
                return False

            chunks = store["chunks"]
            for existing in chunks:
                if existing.get("index") == index and existing.get("type") == block.get(
                    "type"
                ):
                    # 文本类字段累加
                    for key in ("text", "summary", "data"):
                        new_val = block.get(key)
                        if new_val:
                            existing[key] = (existing.get(key, "") or "") + new_val

                    # 其他字段：如果原来没有，则补上；已有则保持原值
                    for key, value in block.items():
                        if key in ("text", "summary", "data"):
                            continue
                        if key not in existing or existing[key] in ("", None):
                            existing[key] = value

                    return True

            return False

        def _append_block(block: Dict[str, Any]) -> None:
            if not isinstance(block, dict):
                return

            # 先尝试按 index 合并
            merged = _merge_block_by_index(store, block)
            if not merged:
                # 未找到同 index 块则作为新块存入
                store["chunks"].append(block)

            # 无论是否合并，都要把本次新增的文本内容累加到 aggregated_text
            store["aggregated_text"] += (
                block.get("text") or block.get("summary") or block.get("data") or ""
            )

        if isinstance(payload, list):
            for block in payload:
                if isinstance(block, dict):
                    _append_block(block)
        elif isinstance(payload, dict):
            _append_block(payload)
        elif isinstance(payload, str):
            _append_block({"type": "reasoning.text", "text": payload, "index": 0})

    def _render_reasoning_for_console(self, payload: Any) -> str:
        """
        仅用于控制台打印，优先输出 text/summary，其次序列化 JSON。
        """
        if isinstance(payload, dict):
            if "text" in payload and isinstance(payload["text"], str):
                return payload["text"]
            if "summary" in payload and isinstance(payload["summary"], str):
                return payload["summary"]
            if "data" in payload and isinstance(payload["data"], str):
                return " Entrypted reasoning...\n"
            if "signature" in payload and isinstance(payload["signature"], str):
                return "\n"
            try:
                return json.dumps(payload, ensure_ascii=False)
            except TypeError:
                return str(payload)

        if isinstance(payload, list):
            # 对于列表，逐块渲染并拼接
            return "".join(self._render_reasoning_for_console(item) for item in payload)

        if isinstance(payload, str):
            return payload

        return str(payload)

    def _extract_text(self, obj: Any) -> str:
        content = getattr(obj, "content", None)
        if not content:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    parts.append(text)
            return "".join(parts)
        return ""

    def _accumulate_tool_call_chunk(
        self,
        accumulator: Dict[int, Dict[str, Any]],
        chunk: Any,
    ) -> None:
        index = chunk.index
        entry = accumulator.setdefault(
            index,
            {
                "id": getattr(chunk, "id", ""),
                "type": getattr(chunk, "type", "function"),
                "function": {"name": "", "arguments": ""},
            },
        )

        if chunk.function:
            if chunk.function.name:
                entry["function"]["name"] = chunk.function.name
            if chunk.function.arguments:
                entry["function"]["arguments"] += chunk.function.arguments

    def _finalize_tool_calls(
        self, raw_tool_calls: Optional[List[Any]]
    ) -> Optional[List[Dict[str, Any]]]:
        if not raw_tool_calls:
            return None

        finalized = []
        for tool_call in raw_tool_calls:
            call_dict = self._tool_call_to_dict(tool_call)
            fn_name = call_dict["function"]["name"]
            arguments = call_dict["function"]["arguments"]
            fixed_arguments = self._validate_and_fix_tool_arguments(fn_name, arguments)
            json.loads(fixed_arguments)
            call_dict["function"]["arguments"] = fixed_arguments
            finalized.append(call_dict)
        print("\n")
        logger.info(
            "llm.tool_calls_detected",
            tool_calls_count=len(finalized),
            tool_names=[call["function"]["name"] for call in finalized],
        )
        return finalized

    def _tool_call_to_dict(self, tool_call: Any) -> Dict[str, Any]:
        if isinstance(tool_call, dict):
            function = tool_call.get("function", {})
            return {
                "id": tool_call.get("id", ""),
                "type": tool_call.get("type", "function"),
                "function": {
                    "name": function.get("name", ""),
                    "arguments": function.get("arguments", ""),
                },
            }

        function = getattr(tool_call, "function", None)
        return {
            "id": getattr(tool_call, "id", ""),
            "type": getattr(tool_call, "type", "function"),
            "function": {
                "name": getattr(function, "name", ""),
                "arguments": getattr(function, "arguments", ""),
            },
        }

    def _maybe_print_header(self, title: str, condition: bool) -> None:
        if condition:
            print(f"\n{'=' * 20}{title}{'=' * 20}\n")

    def _log_response(
        self,
        content: str,
        reasoning_details: Dict[str, Any],
        usage: Optional[Any],
    ) -> None:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
        reasoning_text = reasoning_details.get("aggregated_text", "")
        reasoning_chunk_size = len(reasoning_details.get("chunks", []))

        logger.info(
            "llm.response",
            chars=len(content),
            reasoning_chars=len(reasoning_text),
            reasoning_chunk_size=reasoning_chunk_size,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    def _validate_and_fix_tool_arguments(
        self, function_name: str, arguments_str: str
    ) -> str:
        try:
            json.loads(arguments_str)
            return arguments_str
        except json.JSONDecodeError as original_error:
            logger.warning(
                "llm.tool_arguments_invalid",
                function_name=function_name,
                original_arguments=arguments_str[:200],
                error=str(original_error),
            )

            original_length = len(arguments_str)
            cleaned = arguments_str.strip()
            cleaned = re.sub(r"(?:{}\s*)+(?=\s*$)", "", cleaned)
            cleaned = re.sub(r"(?:\[\]\s*)+(?=\s*$)", "", cleaned)
            cleaned = re.sub(r'(?:""\s*)+(?=\s*$)', "", cleaned)

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

            logger.error(
                "llm.tool_arguments_unfixable",
                function_name=function_name,
                original_arguments=arguments_str[:500],
                error=str(original_error),
            )
            raise ToolError(
                f"工具调用参数JSON解析失败 [函数: {function_name}]: {original_error}\n"
                f"参数预览: {arguments_str[:200]}{'...' if len(arguments_str) > 200 else ''}\n"
                f"参数长度: {len(arguments_str)}\n"
                f"请检查模型输出或工具定义是否正确。"
            )
