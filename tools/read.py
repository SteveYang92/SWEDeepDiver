import os
import asyncio
from site import abs_paths
from typing import Any, Optional
from pathlib import Path

from pydantic import Field
from react_core.tools import BaseTool, ToolError, ToolInput, ToolResult
from app.config import config
from util.file_util import is_in_roots
from app.processor import data_masker
from util.log_truncate import truncate_line


class ReadInput(ToolInput):
    """读取工具的输入参数模型"""

    file_path: str = Field(description="The absolute path to the file to read")
    offset: Optional[int] = Field(
        default=0,
        description="The line number to start reading from (0-based). Only provide if the file is too large to read at once",
    )
    limit: Optional[int] = Field(
        default=100,
        description="The maximum number of lines to read. Only provide if the file is too large to read at once.",
    )


class ReadTool(BaseTool):
    """
    安全文件读取工具，支持分页读取大文件
    核心安全特性：
    - 路径遍历攻击防护
    - 符号链接解析校验
    - 工作目录边界限制
    - 隐藏文件过滤
    """

    name = "Read"
    description = (
        "Safely read file contents with offset and limit support for large files"
    )
    input_model = ReadInput
    timeout_s = 10.0  # 文件读取超时时间

    # 安全配置：允许读取的根目录（生产环境建议配置为具体目录）
    ALLOWED_ROOT_DIR = config.log_dir
    # 安全配置：禁止读取的文件扩展名
    FORBIDDEN_EXTENSIONS = {".db", ".sqlite", ".key", ".pem", ".p12", ".pfx"}
    # 安全配置：最大允许读取的文件大小
    MAX_FILE_SIZE = 500 * 1024 * 1024
    # 最大单次读取行数
    MAX_LINE = 300

    def _validate_path_security(self, file_path: str) -> Path:
        """
        多层级路径安全校验
        抛出 ToolError 如果校验失败
        """
        try:
            # 1. 输入基本格式校验
            if not file_path or not isinstance(file_path, str):
                raise ToolError("Invalid file_path: must be non-empty string")

            # 2. 禁止相对路径和特殊字符
            if file_path.startswith("./") or "../" in file_path:
                raise ToolError("Relative paths are not allowed for security reasons")

            if any(char in file_path for char in ["\0", "\n", "\r", "\t"]):
                raise ToolError("Path contains illegal characters")

            # 3. 解析为绝对路径
            path = Path(file_path)

            # 4. 禁止隐藏文件和系统文件
            if path.name.startswith("."):
                raise ToolError("Hidden files are not allowed")

            # 5. 禁止特定扩展名
            if path.suffix.lower() in self.FORBIDDEN_EXTENSIONS:
                raise ToolError(f"Files with {path.suffix} extension are not allowed")

            abs_path = path.resolve()
            # 7. 工作目录边界检查（核心防护）
            if not is_in_roots(file_path, [self.ALLOWED_ROOT_DIR]):
                raise ToolError(
                    f"Access denied: File must be within {self.ALLOWED_ROOT_DIR}"
                )

            # 8. 文件存在性和类型校验
            if not abs_path.exists():
                raise ToolError(f"File does not exist: {abs_path}")

            if not abs_path.is_file():
                raise ToolError(f"Path is not a file: {abs_path}")

            if not os.access(abs_path, os.R_OK):
                raise ToolError(f"File is not readable: {abs_path}")

            # 9. 文件大小检查
            file_size = abs_path.stat().st_size
            if file_size > self.MAX_FILE_SIZE:
                raise ToolError(
                    f"File size ({file_size} bytes) exceeds limit ({self.MAX_FILE_SIZE} bytes)"
                )

            return abs_path

        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Path validation unexpected error: {e}") from e

    async def _read_file_async(
        self, file_path: Path, offset: int, limit: Optional[int]
    ) -> str:
        """异步执行文件读取操作"""

        def _read():
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                # 如果不需要分页且文件不大，直接读取
                if (
                    offset == 0
                    and limit is None
                    and file_path.stat().st_size < 1024 * 1024
                ):
                    return f.read()

                # 分页读取
                lines = []
                current_line = 0

                # 定位到起始行
                while current_line < offset:
                    if not f.readline():
                        break  # 文件结束
                    current_line += 1

                # 读取指定行数
                lines_read = 0
                while limit is None or lines_read < limit:
                    line = f.readline()
                    if not line:
                        break  # 文件结束
                    line = truncate_line(line)
                    lines.append(data_masker.mask(line))
                    lines_read += 1

                return "".join(lines)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _read)

    async def __call__(self, data: Any) -> ToolResult:
        """主入口：解析输入 → 安全校验 → 异步读取 → 返回结果"""
        # 1. 解析输入
        inp = self.parse_input(data)
        file_path_str = inp.file_path
        offset = max(0, inp.offset or 0)  # 确保非负
        limit = min(ReadTool.MAX_LINE, inp.limit)

        if limit is not None:
            limit = max(1, limit)  # 确保正数

        try:
            # 2. 路径安全校验
            safe_path = self._validate_path_security(file_path_str)

            # 3. 异步读取（带超时控制）

            content = await asyncio.wait_for(
                self._read_file_async(safe_path, offset, limit), timeout=self.timeout_s
            )

            # 4. 返回成功结果
            return ToolResult(ok=True, content=content)

        except asyncio.TimeoutError:
            return ToolResult(
                ok=False,
                content=f"Read operation timed out after {self.timeout_s} seconds",
            )
        except ToolError as e:
            return ToolResult(ok=False, content=str(e))
        except UnicodeDecodeError as e:
            return ToolResult(
                ok=False, content=f"File encoding error (utf-8 required): {e}"
            )
        except IOError as e:
            return ToolResult(ok=False, content=f"IO error during read: {e}")
        except Exception as e:
            return ToolResult(ok=False, content=f"Unexpected error: {repr(e)}")


# 使用示例和测试用例
if __name__ == "__main__":
    import asyncio

    async def test():
        tool = ReadTool()

        # 测试1：正常读取
        result = await tool(
            {"file_path": "/safe/directory/test.txt", "offset": 0, "limit": 10}
        )
        print(f"Test 1 - Normal read: {result.ok}")

        # 测试2：路径遍历攻击
        result = await tool(
            {"file_path": "/safe/directory/../../etc/passwd", "offset": 0, "limit": 10}
        )
        print(f"Test 2 - Path traversal: {not result.ok}")  # 应该失败

        # 测试3：符号链接攻击
        result = await tool(
            {"file_path": "/safe/directory/malicious_symlink", "offset": 0, "limit": 10}
        )
        print(f"Test 3 - Symlink: {not result.ok}")  # 应该失败

        # 测试4：大文件分页读取
        result = await tool(
            {"file_path": "/safe/directory/large_log.txt", "offset": 1000, "limit": 100}
        )
        print(f"Test 4 - Pagination: {result.ok}")

    asyncio.run(test())
