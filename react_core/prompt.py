from __future__ import annotations
import datetime
from pathlib import Path
import re
from app.config import config
from util.file_util import read_content

# 分析Agent提示语文件
main_agent_prompt_file = config.prompt_dir / "deepdiver.md"

# knowledge_config文件
knowledge_config_file = config.config_dir / "knowledge_config.toml"


date_placeholder = "{{current_date}}"
support_knowledge_placeholder = "{{support_knowledge}}"


def main_agent_prompt() -> str:
    """
    生成系统提示
    """
    prompt = read_content(main_agent_prompt_file)

    # date
    def current_date(m):
        return datetime.datetime.now().strftime("%Y-%m-%d")

    prompt = re.sub(date_placeholder, current_date, prompt)

    # support_knowledge
    def support_knowledge(m):
        return read_content(knowledge_config_file)

    prompt = re.sub(support_knowledge_placeholder, support_knowledge, prompt)
    return prompt
