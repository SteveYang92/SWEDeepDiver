from react_core.tool import BaseTool, ToolInput, ToolResult


class TerminateInput(ToolInput):
    pass


class TerminateTool(BaseTool):
    """
    输出最终结论前，调用此工具，标记任务完成
    """

    name = "Terminate"
    description = "输出最终结论前，调用此工具，标记任务完成"
    input_model = TerminateInput

    async def __call__(self, data):
        return ToolResult(ok=True, content="")
