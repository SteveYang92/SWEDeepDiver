from pydantic import Field
from react_core.tool import BaseTool, ToolInput, ToolResult


class FinishInput(ToolInput):
    status: str = Field(description="任务状态，success/failure")


class FinishTool(BaseTool):
    """
    无论诊断类问题，还是非诊断类问题，在准备输出最终结论或回复前，先调用此工具，标记任务完成
    """

    name = "Finish"
    description = "无论诊断类问题，还是非诊断类问题，在准备输出最终结论或回复前，先调用此工具，标记任务完成"
    input_model = FinishInput

    async def __call__(self, data):
        return ToolResult(ok=True, content="")
