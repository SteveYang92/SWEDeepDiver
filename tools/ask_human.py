import asyncio
import sys
from pydantic import Field
from typing import Any

from react_core.tool import BaseTool, ToolInput, ToolResult


class AskHumanInput(ToolInput):
    question: str = Field(
        description="要向用户提出的问题，需简洁明确。", min_length=1, max_length=2000
    )


class AskHumanTool(BaseTool):
    name = "AskHuman"
    description = "向用户请求补充/确认关键信息。"
    input_model = AskHumanInput
    timeout_s = 3600  # 设置一个极大的超时（1小时），确保不会意外超时

    async def __call__(self, data: Any) -> ToolResult:
        inp = self.parse_input(data)
        question = inp.question.strip()

        if not question:
            return ToolResult(ok=False, content="Error: Question cannot be empty")

        # 在终端打印问题
        print(f"\n{'='*60}")
        print(f"🙋 Agent需要你的输入:")
        print(f"   {question}")
        print(f"{'='*60}\n")
        print("请输入您的回答（按回车提交）: ", end="", flush=True)

        # 将阻塞式input()调用放到线程池中，避免阻塞整个事件循环
        loop = asyncio.get_running_loop()

        def _read_from_terminal() -> str:
            """同步函数：从终端读取一行输入"""
            try:
                # 使用input()阻塞等待用户输入
                user_input = sys.stdin.readline().strip()
                if not user_input:
                    # 处理空输入
                    raise ValueError("输入不能为空")
                return user_input
            except EOFError:
                # Ctrl+D
                raise RuntimeError("用户输入被中断 (EOF)")
            except KeyboardInterrupt:
                # Ctrl+C
                raise RuntimeError("用户输入被中断 (KeyboardInterrupt)")
            except Exception as e:
                raise RuntimeError(f"读取输入失败: {e}")

        try:
            # 在后台线程中执行阻塞的input()调用
            user_input = await asyncio.wait_for(
                loop.run_in_executor(None, _read_from_terminal), timeout=self.timeout_s
            )

            # 成功读取，返回用户原始输入（作为Observation内容）
            return ToolResult(
                ok=True, content=user_input  # 只返回纯文本，不包含任何前缀
            )

        except asyncio.TimeoutError:
            return ToolResult(ok=False, content="Error: User input timed out")
        except RuntimeError as e:
            return ToolResult(ok=False, content=f"Error: {e}")
        except Exception as e:
            return ToolResult(
                ok=False, content=f"Unexpected error: {type(e).__name__}: {str(e)}"
            )
