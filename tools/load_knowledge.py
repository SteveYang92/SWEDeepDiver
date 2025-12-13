import os
import asyncio
from typing import Any
from pathlib import Path
from pydantic import Field

from react_core.tools import BaseTool, ToolInput, ToolResult


class LoadKnowledgeInput(ToolInput):
    knowledge_key: str = Field(
        description="知识标识符（如Login/Network/Unknown）",
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9_]+$",  # 只允许字母数字下划线
    )


class LoadKnowledgeTool(BaseTool):
    name = "LoadKnowledge"
    description = "从本地knowledge/目录加载问题相关的原始Markdown知识文档"
    input_model = LoadKnowledgeInput
    timeout_s = 2.0
    dump_observation = False

    # 配置知识库根目录（相对于工作目录）
    KNOWLEDGE_DIR = Path("./knowledge").resolve()

    # 确保目录存在
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    def _validate_path_safety(self, knowledge_key: str) -> Path:
        """
        防止路径遍历攻击，确保文件在KNOWLEDGE_DIR内
        """
        # 构建安全文件名：只能包含允许的字符
        safe_filename = f"{knowledge_key}.md"

        # 规范化路径并检查是否在知识库目录内
        try:
            # 使用commonpath检查防止目录遍历
            target_path = (self.KNOWLEDGE_DIR / safe_filename).resolve()
            if os.path.commonpath([target_path, self.KNOWLEDGE_DIR]) != str(
                self.KNOWLEDGE_DIR
            ):
                raise ValueError(f"非法路径访问: {knowledge_key}")

            return target_path
        except Exception as e:
            raise ValueError(f"路径验证失败: {e}")

    async def __call__(self, data: Any) -> ToolResult:
        """异步加载知识文件，返回原始Markdown内容"""
        inp = self.parse_input(data)
        knowledge_key = inp.knowledge_key.strip()

        try:
            # 1. 路径安全检查
            knowledge_file = self._validate_path_safety(knowledge_key)

            # 2. 异步读取文件（避免阻塞事件循环）
            loop = asyncio.get_running_loop()

            def read_file():
                if not knowledge_file.exists():
                    # 文件不存在时，尝试加载Unknown.md作为回退
                    unknown_file = self.KNOWLEDGE_DIR / "Unknown.md"
                    if unknown_file.exists():
                        return {
                            "status": "fallback",
                            "requested_key": knowledge_key,
                            "markdown_content": unknown_file.read_text(
                                encoding="utf-8"
                            ),
                            "fallback_reason": f"Key '{knowledge_key}' not found, falling back to Unknown",
                        }
                    else:
                        # 连Unknown.md都不存在
                        return {
                            "status": "error",
                            "requested_key": knowledge_key,
                            "error_message": f"Knowledge file not found: {knowledge_file.name}",
                            "fallback_available": False,
                        }

                # 正常读取文件
                return {
                    "status": "success",
                    "knowledge_key": knowledge_key,
                    "markdown_content": knowledge_file.read_text(encoding="utf-8"),
                    "file_path": str(knowledge_file),
                }

            # 使用run_in_executor避免阻塞
            result = await asyncio.wait_for(
                loop.run_in_executor(None, read_file), timeout=self.timeout_s
            )

            # 3. 根据状态返回结果
            if result["status"] == "error":
                return ToolResult(ok=False, content=result)
            else:
                return ToolResult(ok=True, content=result["markdown_content"])

        except asyncio.TimeoutError:
            return ToolResult(
                ok=False,
                content={
                    "status": "timeout",
                    "requested_key": knowledge_key,
                    "error_message": f"Knowledge loading timed out after {self.timeout_s}s",
                },
            )
        except ValueError as e:
            # 路径验证失败
            return ToolResult(
                ok=False,
                content={
                    "status": "security_error",
                    "requested_key": knowledge_key,
                    "error_message": str(e),
                },
            )
        except Exception as e:
            # 其他意外错误
            return ToolResult(
                ok=False,
                content={
                    "status": "unexpected_error",
                    "requested_key": knowledge_key,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
