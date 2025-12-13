import os
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import Field
from app.config import config
from react_core.llm import LLMClient
from react_core.tools import BaseTool, ToolInput, ToolResult
import structlog
from util.file_util import read_content

logger = structlog.get_logger(__name__)

# llm
REVIEW_EVIDENCE_PROMPT_FILE = (config.prompt_dir / "reviewer.md").resolve()
# user input placeholder
ISSUE_PLACE_HOLDER = "{{issue}}"
TIMELINE_PLACE_HOLDER = "{{timeline}}"
EVIDENCE_PLACE_HOLDER = "{{evidence}}"
KNOWLEDGE_BASIS_PLACE_HOLDER = "{{knowledge_basis}}"
LOG_BASIS_PLACE_HOLDER = "{{log_basis}}"
CODE_BASIS_PLACE_HOLDER = "{{code_basis}}"
OTHER_BASIS_PLACE_HOLDER = "{{other_basis}}"
CONCLUSION_PLACE_HOLDER = "{{conclusion}}"
# system prompt placeholder
KNOWLEDGE_DIR = config.knowledge_dir
USER_INPUT_TEMPLATE_FILE = (config.config_dir / "evidence_format.md").resolve()
KNOWLEDGE_PLACE_HOLDER = "{{knowledge}}"
COMMIT_COUNT_PLACE_HOLDER = "{{commit_count}}"
MAX_COMMIT_COUNT_PLACE_HOLDER = "{{max_commit_count}}"


class ReviewEvicenceInput(ToolInput):
    path: str = Field(description="完整日志路径")
    issue: str = Field(description="用户问题")
    ref_knowledge_keys: list[str] = Field(description="引用的知识Key")
    timeline_event: str = Field(description="当前时间轴事件")
    evidence_chain: str = Field(description="当前的证据链（根因->中间事件->表象）")
    knowledge_evidence: str = Field(description="支持当前证据链和结论的知识证据")
    log_evidence: str = Field(description="支持当前证据链和结论的日志依据")
    code_analysis_evidence: Optional[str] = Field(
        default="无", description="支持当前证据链和结论的日志依据"
    )
    other_basis: Optional[str] = Field(
        default="无", description="支持当前证据链和结论的其他依据"
    )
    conclusion: str = Field(description="分析结论")


class ReviewEvicenceTool(BaseTool):
    name = "Review"
    description = "评审当前的证据链"
    input_model = ReviewEvicenceInput

    def __init__(self):
        super().__init__()
        self.llm = LLMClient(config.reviewer.llm)
        self.current_commit_count = 0
        self.max_commit_count = config.reviewer.max_commit_count

    async def __call__(self, data):
        inp = self.parse_input(data)
        self.current_commit_count += 1
        res = await self._review_evidence(inp)
        return ToolResult(
            ok=True,
            content=res,
        )

    async def _review_evidence(self, input: ReviewEvicenceInput) -> str:
        """
        review evidence
        """
        logger.info("llm.reviewevidence.start", commit_count=self.current_commit_count)
        evidence = self._build_evidence(input)
        print("\n" + "=" * 20 + "提交证据" + "=" * 20 + "\n")
        print(evidence)
        trajectory_msgs: List[Dict[str, str]] = []
        trajectory_msgs.append(
            {"role": "system", "content": self._get_sys_prompt(input)}
        )
        trajectory_msgs.append({"role": "user", "content": evidence})
        rsp = await self.llm.acomplete(messages=trajectory_msgs)
        return rsp.content

    def _build_evidence(self, input: ReviewEvicenceInput) -> str:
        user_input_template: str = read_content(USER_INPUT_TEMPLATE_FILE)
        res = (
            user_input_template.replace(ISSUE_PLACE_HOLDER, input.issue)
            .replace(KNOWLEDGE_BASIS_PLACE_HOLDER, input.knowledge_evidence)
            .replace(LOG_BASIS_PLACE_HOLDER, input.log_evidence)
            .replace(TIMELINE_PLACE_HOLDER, input.timeline_event)
            .replace(EVIDENCE_PLACE_HOLDER, input.evidence_chain)
            .replace(CODE_BASIS_PLACE_HOLDER, input.code_analysis_evidence)
            .replace(OTHER_BASIS_PLACE_HOLDER, input.other_basis)
            .replace(CONCLUSION_PLACE_HOLDER, input.conclusion)
        )
        return res

    def _get_sys_prompt(self, input: ReviewEvicenceInput) -> str:
        system_prompt: str = read_content(REVIEW_EVIDENCE_PROMPT_FILE)
        key_to_path = [
            (key, self._validate_path_safety(key)) for key in input.ref_knowledge_keys
        ]
        knowledge_list = [
            f"<{key}Knowledge>\n{read_content(path)}\n</{key}Knowledge>"
            for (key, path) in key_to_path
        ]
        knowledges = "\n".join(knowledge_list)
        prompt = (
            system_prompt.replace(KNOWLEDGE_PLACE_HOLDER, knowledges)
            .replace(COMMIT_COUNT_PLACE_HOLDER, str(self.current_commit_count))
            .replace(MAX_COMMIT_COUNT_PLACE_HOLDER, str(self.max_commit_count))
        )
        return prompt

    def _validate_path_safety(self, knowledge_key: str) -> Path:
        """
        防止路径遍历攻击，确保文件在KNOWLEDGE_DIR内
        """
        # 构建安全文件名：只能包含允许的字符
        safe_filename = f"{knowledge_key}.md"

        # 规范化路径并检查是否在知识库目录内
        try:
            # 使用commonpath检查防止目录遍历
            target_path = (KNOWLEDGE_DIR / safe_filename).resolve()
            if os.path.commonpath([target_path, KNOWLEDGE_DIR]) != str(KNOWLEDGE_DIR):
                raise ValueError(f"非法路径访问: {knowledge_key}")

            return target_path
        except Exception as e:
            raise ValueError(f"路径验证失败: {e}")
