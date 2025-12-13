import asyncio
from typing import Optional
from pydantic import Field
from react_core.tools import BaseTool, ToolInput, ToolResult
from util.analyze_code_util import analyze_with_claude_code


class AnalyzeCodeInput(ToolInput):
    analyze_target: str = Field(description="Describe your target to analyze")
    log: str = Field(description="Related log")
    stack_trace: Optional[str] = Field(default="", description="Related stack trace")


class AnalyzeCodeTool(BaseTool):
    name = "AnalyzeCode"
    description = "Analyze code and locate root cause of issue"
    input_model = AnalyzeCodeInput

    def __init__(self, code_path: str = ""):
        super().__init__()
        self.code_path = code_path

    async def __call__(self, data) -> ToolResult:
        inp: AnalyzeCodeInput = self.parse_input(data)
        if not self.code_path:
            return ToolResult(content="Code path is not provided", success=False)
        print("\n" + "=" * 20 + "分析代码" + "=" * 20 + "\n")
        print(f"{inp.analyze_target}\n{inp.log}\n{inp.stack_trace}")
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,  # 使用默认线程池
            analyze_with_claude_code,
            self.code_path,
            inp.analyze_target,
            inp.log,
            inp.stack_trace,
        )

        return ToolResult(content=res, success=True)
