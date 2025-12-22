import asyncio
from typing import Optional
from pydantic import Field
from react_core.tool import BaseTool, ToolInput, ToolResult
from util.analyze_code_util import analyze_with_claude_code


class AnalyzeCodeInput(ToolInput):
    analyze_target: str = Field(
        description="需要代码专家分析的目标，2-5 句话说明要搞清楚什么问题。"
    )
    log: str = Field(
        description="与问题相关的关键日志（建议包含完整上下文，可帮助分析者全面了解要分析的问题）；每条日志包含时间 + TAG + 内容(多条日志用换行符分割)"
    )
    stack_trace: Optional[str] = Field(
        default="", description="与问题相关的异常堆栈/代码调用栈等"
    )


class AnalyzeCodeTool(BaseTool):
    name = "AnalyzeCode"
    description = "在日志或知识不足时，请求专家分析项目代码以补充证据。"
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
