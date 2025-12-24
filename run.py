import asyncio
import sys
import time

from tools.analyze_code import AnalyzeCodeTool
from tools.glob import GlobTool
from tools.grep import GrepTool
from tools.read import ReadTool
from tools.review import ReviewEvicenceTool
from tools.ask_human import AskHumanTool
from tools.load_knowledge import LoadKnowledgeTool
from tools.process_file import ProcessFileTool
from tools.inspect import InspectTool
from tools.finish import FinishTool

from react_core.llm import LLMClient
from react_core.tool import ToolRegistry
from react_core.agent import ReActAgent, ReActAgentConfig
from util.measure_time import auto_time_unit
from test_case import test_case_entry
from app.config import config
from app.processor import data_masker


# Bug desc
bug_desc = test_case_entry
# Code path
code_path = ""


async def main(llm_config_name: str = "default"):
    # Tools
    tool_registry = ToolRegistry()
    tool_registry.register(GrepTool())
    tool_registry.register(GlobTool())
    tool_registry.register(ProcessFileTool())
    tool_registry.register(InspectTool())
    tool_registry.register(LoadKnowledgeTool())
    tool_registry.register(ReviewEvicenceTool())
    tool_registry.register(AskHumanTool())
    tool_registry.register(AnalyzeCodeTool(code_path))
    tool_registry.register(ReadTool())
    tool_registry.register(FinishTool())
    # Agent
    agent = ReActAgent(
        llm=LLMClient(
            config.deepdiver.llm.get(llm_config_name, config.deepdiver.llm["default"])
        ),
        tools=tool_registry,
        config=ReActAgentConfig(
            max_steps=config.deepdiver.max_steps,
            finish_tool_name=FinishTool().name,
        ),
    )

    start = time.perf_counter()
    await agent.aask(data_masker.mask(bug_desc))
    print(f"Task execution time:{auto_time_unit(time.perf_counter() - start)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 0:
        llm_config_name = "default"
    else:
        llm_config_name = args[0]
    asyncio.run(main(llm_config_name))
