from __future__ import annotations

import json
import re
from typing import Optional, Tuple, Any


class StepParseResult:
    def __init__(
        self,
        thought: Optional[str],
        action_name: Optional[str],
        action_input: Optional[Any],
        final_answer: Optional[str],
    ):
        self.thought = thought
        self.action_name = action_name
        self.action_input = action_input
        self.final_answer = final_answer


ACTION_RE = re.compile(
    r"Action\s*:\s*(?P<name>[a-zA-Z0-9_\-]+)\s*\((?P<input>\{.*\})\)",
    re.DOTALL,
)
THOUGHT_RE = re.compile(r"Thought\s*:\s*(?P<t>.+?)(?:\n|$)", re.DOTALL)
FINAL_RE = re.compile(r"(?:Action:\s*)?Final\s*:\s*(?P<f>.*)", re.DOTALL)


def tolerant_json_extract(s: str) -> Optional[dict]:
    # Try to find the last JSON object in the string
    braces = []
    start = None
    for i, ch in enumerate(s):
        if ch == "{":
            if start is None:
                start = i
            braces.append("{")
        elif ch == "}":
            if braces:
                braces.pop()
                if not braces and start is not None:
                    chunk = s[start : i + 1]
                    try:
                        return json.loads(chunk)
                    except Exception:
                        # try to sanitize trailing commas
                        try:
                            return json.loads(re.sub(r",\s*}", "}", chunk))
                        except Exception:
                            pass
                    start = None
    return None


def parse_react_step(text: str) -> StepParseResult:
    # Extract final first (highest priority)
    m_final = FINAL_RE.search(text)
    if m_final:
        return StepParseResult(
            thought=None,
            action_name=None,
            action_input=None,
            final_answer=m_final.group("f").strip(),
        )

    # Try explicit Action: name {json}
    m_action = ACTION_RE.search(text)
    action_name = None
    action_input = None
    if m_action:
        action_name = m_action.group("name").strip()
        json_text = m_action.group("input").strip()
        try:
            action_input = json.loads(json_text)
        except Exception:
            # fallback tolerant JSON parse
            action_input = tolerant_json_extract(json_text) or {}

    # Thought is optional but helpful
    m_thought = THOUGHT_RE.search(text)
    thought = m_thought.group("t").strip() if m_thought else None

    return StepParseResult(
        thought=thought,
        action_name=action_name,
        action_input=action_input,
        final_answer=None,
    )
