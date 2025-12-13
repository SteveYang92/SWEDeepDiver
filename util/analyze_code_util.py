import os
import json
import subprocess
from textwrap import dedent
from typing import List, Dict, Any, Optional
import structlog
import time

from app.config import config
from util.file_util import read_content
from util.measure_time import auto_time_unit

PROMPT_PLACE_HOLDER_PROBLEM_SUMMARY = "{{problem_summary}}"
PROMPT_PLACE_HOLDER_LOG = "{{log}}"
PROMPT_PLACE_HOLDER_STACK_TRACE = "{{stack_trace}}"
PROMPT_PLACE_HOLDER_SUSPECTED_TEXT = "{{suspected_text}}"
PROPMT_FILE = config.prompt_dir / "code_analyzer.md"

logger = structlog.get_logger(__name__)

current_session_id = ""


class ClaudeCodeError(Exception):
    pass


def _strip_ansi(s: str) -> str:
    """简单去掉 ANSI 颜色码（避免影响 JSON 解析）"""
    import re

    ansi_re = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    return ansi_re.sub("", s)


def analyze_with_claude_code(
    repo_path: str,
    problem_summary: str,
    log: str,
    stack_trace: str = "",
    suspected_locations: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 600,
) -> str:
    """
    在指定仓库目录下调用 `claude` CLI，让 Claude Code 看本地代码并给出 JSON 结果。

    参数:
        repo_path: 本地代码仓根目录，例如 "/srv/repos/order-service"
        problem_summary: 问题摘要（来自你的日志分析 Agent）
        log: 关键日志片段（可截断）
        stack_trace: 堆栈信息（可为空）
        suspected_locations: 可疑代码位置列表，如:
            [
                {"file": "src/main/java/com/xxx/order/OrderService.java", "line": 184},
                {"file": "src/main/java/com/xxx/order/OrderController.java", "line": 52},
            ]
        timeout: 调用 CLI 的超时时间（秒）

    返回:
        分析结论，结构由你在 prompt 中约定。
    """
    global current_session_id
    if not os.path.isdir(repo_path):
        raise ClaudeCodeError(f"repo_path 不存在或不是目录: {repo_path}")

    prompt = _get_prompt(problem_summary, log, stack_trace, suspected_locations)

    cmd = ["claude", "-p", "--output-format", "json"]
    if current_session_id:
        cmd += ["--resume", current_session_id]
    logger.info("claudecode.analyzecode.start", repo_path=repo_path, cmd=" ".join(cmd))
    cmd.append(prompt)

    try:
        start = time.perf_counter()
        completed = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),  # 继承当前环境（包括 API key）
        )
        logger.info(
            "claudecode.analyzecode.finish",
            cost=f"{auto_time_unit(time.perf_counter()-start)}",
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeCodeError(f"调用 claude CLI 超时（>{timeout}s）") from e
    except FileNotFoundError as e:
        raise ClaudeCodeError("找不到 `claude` 命令，请确认已安装并在 PATH 中") from e

    if completed.returncode != 0:
        # stderr 里可能有有用信息，可以打日志
        raise ClaudeCodeError(
            f"claude CLI 退出码非 0: {completed.returncode}, stderr: {completed.stderr}"
        )

    raw_out = completed.stdout
    if not raw_out.strip():
        raise ClaudeCodeError("claude CLI 没有产生任何输出")

    # 去掉 ANSI 颜色码，避免影响后续解析
    clean_out = _strip_ansi(raw_out)

    try:
        result_json = json.loads(clean_out)
        (session_id, result) = _parse_response(result_json)
        current_session_id = session_id
    except json.JSONDecodeError as e:
        # 这里同样建议记录 json_block 方便调试 prompt
        raise ClaudeCodeError(f"JSON 解析失败: {e}") from e

    return result


def _get_prompt(
    problem_summary: str,
    log: str,
    stack_trace: str = "",
    suspected_locations: Optional[List[Dict[str, Any]]] = None,
) -> str:
    prompt = read_content(PROPMT_FILE)
    return (
        prompt.replace(PROMPT_PLACE_HOLDER_PROBLEM_SUMMARY, problem_summary)
        .replace(PROMPT_PLACE_HOLDER_LOG, log)
        .replace(PROMPT_PLACE_HOLDER_STACK_TRACE, stack_trace or "无")
        .replace(
            PROMPT_PLACE_HOLDER_SUSPECTED_TEXT,
            _build_suspected_location_str(suspected_locations) or "无明确位置",
        )
    )


def _build_suspected_location_str(
    suspected_locations: Optional[List[Dict[str, Any]]] = None,
) -> str:
    suspected_text = ""
    if suspected_locations:
        lines = []
        for loc in suspected_locations:
            path = loc.get("file") or loc.get("path") or "unknown"
            line = loc.get("line")
            if line is not None:
                lines.append(f"- 文件 {path} 第 {line} 行附近")
            else:
                lines.append(f"- 文件 {path}")
        suspected_text = "\n".join(lines)
    return suspected_text


def _parse_response(result_json: Dict[str, Any]) -> tuple[str, str]:
    """从 JSON 解析 session_id 和内容"""
    try:
        session_id = result_json.get("session_id", "")

        result = result_json.get("result", "")

        is_error = result_json.get("is_error", True)

        usage = result_json.get("usage", {})

        logger.info(
            "claudecode.analyzecode.parsejson",
            session_id=session_id,
            is_success=not is_error,
            usage=usage,
        )
        return session_id, result
    except Exception as e:
        raise ValueError(f"解析失败: {e}")


## 2. 示例调用方式
if __name__ == "__main__":
    repo = "path/to/your/code"  # 你的本地代码目录

    problem_summary = "问题描述"
    log = dedent(
        """
        日志
        日志
        ...
        """
    )
    stack_trace = """"""

    suspected_locations = []

    try:
        result = analyze_with_claude_code(
            repo_path=repo,
            problem_summary=problem_summary,
            log=log,
            stack_trace=stack_trace,
            suspected_locations=suspected_locations,
        )
    except ClaudeCodeError as e:
        print("调用 Claude Code 失败:", e)
    else:
        print("Claude Code 结构化结果：")
        print(result)
