import asyncio
import os
import re
from pathlib import Path
import shutil
import tempfile
from typing import Any

from pydantic import Field
import structlog

from react_core.tools import BaseTool, ToolInput, ToolResult, ToolError
from app.config import config
from app.processor import log_descyptor

logger = structlog.get_logger(__name__)


class ProcessFileInput(ToolInput):
    path: str = Field(
        description=(
            "原始文件路径（通常为通过 Glob 等工具获取到的路径）。"
            "工具会根据type对文件做预处理（例如log解密、脱敏，img信息读取等），并返回处理后的文件路径。"
        )
    )
    type: str = Field(description=("文件类型，支持:log/trace/img/other"))


class ProcessFileTool(BaseTool):
    """
    日志预处理工具：
    - 输入：原始日志文件路径
    - 功能：对日志进行预处理，例如解密、脱敏、格式归一化等
    - 输出：处理后的日志文件路径（字符串），供后续 Grep、Inspect 等工具使用
    """

    name = "ProcessFile"
    description = (
        "对日志文件进行预处理（如解密、脱敏、格式整理），输入原始日志路径，"
        "返回处理后的日志文件路径（相对或绝对路径，视实现而定）。"
    )
    input_model = ProcessFileInput
    timeout_s = 10.0

    def __init__(self):
        super().__init__()
        self.log_sandbox_dir = config.log_dir
        self.log_decryptor = log_descyptor

    async def __call__(self, data: Any) -> ToolResult:
        inp = self.parse_input(data)
        raw_path = Path(inp.path).expanduser().resolve()

        if not raw_path.exists():
            return ToolResult(
                ok=False,
                content=f"ProcessFile error: file '{raw_path}' does not exist",
            )
        if not raw_path.is_file():
            return ToolResult(
                ok=False, content=f"ProcessFile error: '{raw_path}' is not a file"
            )
        try:
            path = inp.path
            type = inp.type
            source_files = [path]
            logger.debug("tool.processfile", source_log_path=path, type=type)
            if source_files:
                temp_dir = tempfile.mkdtemp(prefix="deepdiver_temp_")
                processed_files = []

                for src_path in source_files:
                    filename = os.path.basename(src_path)
                    temp_path = os.path.join(temp_dir, filename)
                    shutil.copy2(src_path, temp_path)
                    if type == "log" or type == "trace":
                        self._process_log(
                            processed_files, src_path, temp_path, filename
                        )
                    else:
                        shutil.rmtree(temp_dir)
                        return ToolResult(
                            ok=True, content=f"File {type} is not support yet"
                        )
                shutil.rmtree(temp_dir)
                return ToolResult(ok=True, content="\n".join(processed_files))
            else:
                return ToolResult(ok=True, content="File is not found")

        except Exception as e:
            return ToolResult(ok=False, content=f"ProcessFile error: {e!r}")

    def _process_log(
        self,
        processed_files: list[str],
        original_path: str,
        temp_path: str,
        filename: str,
    ):
        try:
            decrypted_log_path = self.log_decryptor.decrypt(
                input_file_path=temp_path,
                output_dir=self.log_sandbox_dir,
                filename=filename,
            )
            os.remove(temp_path)
            processed_files.append(decrypted_log_path)
        except Exception as e:
            logger.error(
                "tools.processfile", path=temp_path, msg=f"Decrypt file failed {e}"
            )
            os.remove(temp_path)
            log_path = os.path.join(self.log_sandbox_dir, filename)
            shutil.copy2(original_path, log_path)
            processed_files.append(log_path)
