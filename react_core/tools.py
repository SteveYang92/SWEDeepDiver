from __future__ import annotations

import asyncio
from typing import Any, Dict, Callable, Tuple
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

    def as_instructions(self) -> str:
        lines = []
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

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
