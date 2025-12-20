from pathlib import Path
import sys
import json
import threading
from typing import Optional

from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def get_project_root() -> Path:
    """Get the project root directory"""
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = get_project_root()
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"
PROMPT_DIR = PROJECT_ROOT / "prompt"
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_FILE_PATH = CONFIG_DIR / "config.toml"
LOG_DIR = WORKSPACE_ROOT / "log_processed"
KNOWLEDGE_DIR = WORKSPACE_ROOT / "knowledge"

WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


class LLMConfig(BaseModel):
    model: str
    base_url: str
    api_key: str
    max_tokens: int
    temperature: float
    timeout: float
    enable_thinking: bool
    dump_thinking: bool
    dump_answer: bool
    stream: bool


class DeepDiverConfig(BaseModel):
    max_steps: int = Field(default=30, description="max loop steps")
    llm: dict[str, LLMConfig]


class InsectorPattern(BaseModel):
    error_pattern: str
    exception_pattern: str
    env_pattern: str
    context_pattern: str


class InspectorConfig(BaseModel):
    max_line_of_grep: int
    max_length_of_line: int
    pattern: InsectorPattern
    llm: LLMConfig


class ReviewerConfig(BaseModel):
    max_commit_count: int
    llm: LLMConfig


class GrepConfig(BaseModel):
    max_line_of_grep: int


class ToolsConfig(BaseModel):
    grep: GrepConfig


class IssueDirConfig(BaseModel):
    dirs: list[str]


class LogProcessorConfig(BaseModel):
    max_char_count_per_line: int
    ignore_patterns: Optional[list[str]] = Field(default=[])


class AppConfig(BaseModel):
    deepdiver: DeepDiverConfig
    inspector: InspectorConfig
    reviewer: ReviewerConfig
    tools: ToolsConfig
    issue_dir: IssueDirConfig
    log_processor: LogProcessorConfig


class Config:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._config = None
                    self._load_config()
                    self._initialized = True

    def _get_config_path(self) -> Path:
        return CONFIG_FILE_PATH

    def _load_config_as_dict(self) -> dict:
        config_path = self._get_config_path()
        with config_path.open("rb") as f:
            return tomllib.load(f)

    def _load_config(self):
        raw_config = self._load_config_as_dict()
        deepdiver = raw_config.get("deepdiver", {})
        base_llm = deepdiver.get("llm", {})
        llm_overrides = {
            k: v for k, v in deepdiver.get("llm", {}).items() if isinstance(v, dict)
        }
        default_settings = {
            "model": base_llm.get("model"),
            "base_url": base_llm.get("base_url"),
            "api_key": base_llm.get("api_key"),
            "max_tokens": base_llm.get("max_tokens", 4096),
            "temperature": base_llm.get("temperature", 1.0),
            "timeout": base_llm.get("timeout", 120.0),
            "enable_thinking": base_llm.get("enable_thinking", True),
            "dump_thinking": base_llm.get("dump_thinking", True),
            "dump_answer": base_llm.get("dump_answer", True),
            "stream": base_llm.get("stream", True),
        }
        inspector = raw_config.get("inspector", {})
        reviewer = raw_config.get("reviewer", {})
        tools = raw_config.get("tools", {})
        issue_dir = raw_config.get("issue_dir", {})
        log_processor = raw_config.get("log_processor", {})

        app_config = {
            "deepdiver": {
                "max_steps": deepdiver.get("max_steps", 30),
                "llm": {
                    "default": default_settings,
                    **{
                        name: {**default_settings, **override_config}
                        for name, override_config in llm_overrides.items()
                    },
                },
            },
            "inspector": inspector,
            "reviewer": reviewer,
            "tools": tools,
            "issue_dir": issue_dir,
            "log_processor": log_processor,
        }

        self._config = AppConfig(**app_config)

    @property
    def deepdiver(self) -> DeepDiverConfig:
        return self._config.deepdiver

    @property
    def inspector(self) -> InspectorConfig:
        return self._config.inspector

    @property
    def reviewer(self) -> ReviewerConfig:
        return self._config.reviewer

    @property
    def tools(self) -> ToolsConfig:
        return self._config.tools

    @property
    def issue_dir(self) -> IssueDirConfig:
        return self._config.issue_dir

    @property
    def log_processor(self) -> LogProcessorConfig:
        return self._config.log_processor

    @property
    def log_dir(self) -> str:
        return LOG_DIR.relative_to(PROJECT_ROOT)

    @property
    def prompt_dir(self) -> Path:
        return PROMPT_DIR

    @property
    def config_dir(self) -> Path:
        return CONFIG_DIR

    @property
    def knowledge_dir(self) -> Path:
        return KNOWLEDGE_DIR

    @property
    def workspace_dir(self) -> str:
        return WORKSPACE_ROOT.relative_to(PROJECT_ROOT)


config = Config()

# dump config
if __name__ == "__main__":
    with open(CONFIG_FILE_PATH, "rb") as f:
        print(json.dumps(tomllib.load(f), ensure_ascii=False, indent=4))

    print(config.deepdiver.llm)
