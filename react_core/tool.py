from __future__ import annotations

import asyncio
from typing import Any, Dict, Callable, List, Optional, Tuple
from pydantic import BaseModel, Field, ValidationError
import structlog
import math

logger = structlog.get_logger(__name__)


class ToolInput(BaseModel):
    """Base class for tool inputs; extend per tool."""


class ToolResult(BaseModel):
    ok: bool = True
    content: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class ToolError(Exception):
    pass


class BaseTool:
    """
    Base tool interface for ReAct.
    Each tool provides:
      - name: unique tool name
      - description: when to use this tool
      - input_model: a Pydantic model for input validation
      - __call__: async execution
    """

    name: str
    description: str
    input_model: Callable[..., ToolInput]
    timeout_s: float = 15.0
    max_retries: int = 1
    dump_observation: bool = True

    def __init__(self) -> None:
        if not hasattr(self, "name") or not hasattr(self, "description"):
            raise ValueError("Tool must define name and description")

    def parse_input(self, data: Any) -> ToolInput:
        try:
            return self.input_model.model_validate(data)
        except ValidationError as e:
            raise ToolError(f"Invalid input for tool {self.name}: {e}")

    async def __call__(self, data: Any) -> ToolResult:
        raise NotImplementedError

    @classmethod
    def _get_model_schema(cls) -> Dict[str, Any]:
        """获取 Pydantic 模型的 JSON schema，兼容 v1/v2。"""
        if hasattr(cls.input_model, "model_json_schema"):  # pydantic v2
            return cls.input_model.model_json_schema()
        return cls.input_model.schema()  # pydantic v1

    @classmethod
    def _simplify_anyof_for_llm(cls, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        简化 JSON schema 中的 anyOf 结构，提高 LLM 兼容性。
        只保留 description、type、items（数组类型）三个字段。
        """
        properties = schema.get("properties", {}).copy()
        required = schema.get("required", []).copy()

        for field_name, field_schema in properties.items():
            # 只保留 description（如果存在）
            simplified = {}
            if "description" in field_schema:
                simplified["description"] = field_schema["description"]

            if "anyOf" in field_schema:
                # 提取非 null 的类型定义
                non_null_types = [
                    t for t in field_schema["anyOf"] if t.get("type") != "null"
                ]
            else:
                non_null_types = []

            # 是Optional字段，且只有一个非 null 类型，则简化
            if len(non_null_types) == 1:
                type_def = non_null_types[0]
                simplified["type"] = type_def.get("type")

                # 如果是数组类型，保留 items
                if type_def.get("type") == "array" and "items" in type_def:
                    simplified["items"] = type_def["items"]

                properties[field_name] = simplified

            # 不是Optional字段
            if "anyOf" not in field_schema:
                type_def = field_schema
                simplified["type"] = type_def.get("type")

                # 如果是数组类型，保留 items
                if type_def.get("type") == "array" and "items" in type_def:
                    simplified["items"] = type_def["items"]
                properties[field_name] = simplified
        return {"properties": properties, "required": required}

    @classmethod
    def _parameters_from_input_model(cls) -> Dict[str, Any]:
        """根据 input_model 生成 LLM tool 的 parameters 声明。"""
        schema = cls._get_model_schema()
        simplified = cls._simplify_anyof_for_llm(schema)

        return {
            "type": "object",
            "properties": simplified["properties"],
            "required": simplified["required"],
        }

    @classmethod
    def to_llm_function(cls) -> Dict[str, Any]:
        """
        生成 LLM tool 的 function 声明：
        {
          "name": ...,
          "description": ...,
          "parameters": {...}
        }
        """
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": cls._parameters_from_input_model(),
        }

    @classmethod
    def to_openai_tool(cls) -> Dict[str, Any]:
        """
        生成 OpenAI tools 格式：
        {
          "type": "function",
          "function": {
             "name": ...,
             "description": ...,
             "parameters": {...}
          }
        }
        """
        return {
            "type": "function",
            "function": cls.to_llm_function(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name}")
        return self._tools[name]

    def as_llm_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def list_names(self) -> Tuple[str, ...]:
        return tuple(self._tools.keys())


# Example tool: Safe calculator with limited operations.
class CalcInput(ToolInput):
    expr: str = Field(
        description="Arithmetic expression with + - * / ^ ( ) and math functions like sqrt, log, sin, cos."
    )


class CalculatorTool(BaseTool):
    name = "calculator"
    description = (
        "Evaluate arithmetic expressions accurately, e.g., financial, unit-less math."
    )
    input_model = CalcInput
    timeout_s = 4.0

    async def __call__(self, data: Any) -> ToolResult:
        inp = self.parse_input(data)
        # Very limited safe evaluation
        allowed_names = {
            "sqrt": math.sqrt,
            "log": math.log,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "pi": math.pi,
            "e": math.e,
            "abs": abs,
            "pow": pow,
        }
        expr = inp.expr.replace("^", "**")
        try:
            loop = asyncio.get_running_loop()
            # run in thread to avoid blocking
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: eval(expr, {"__builtins__": {}}, allowed_names)
                ),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError as e:
            raise ToolError("calculator timed out") from e
        except Exception as e:
            return ToolResult(ok=False, content=f"Calculator error: {e!r}")
        return ToolResult(ok=True, content=str(result))
