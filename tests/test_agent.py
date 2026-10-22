"""에이전트 단위 테스트 — 그래프 구조 검증 (LLM 호출 없음)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import ChatState, SYSTEM_PROMPT, _should_continue
from src.tools import LOCAL_TOOLS
from langchain_core.messages import AIMessage, HumanMessage


class TestGraphStructure:
    """그래프 구조 검증."""

    def test_state_has_messages(self):
        state: ChatState = {"messages": []}
        assert "messages" in state

    def test_system_prompt_exists(self):
        assert len(SYSTEM_PROMPT) > 0
        assert "맛집" in SYSTEM_PROMPT

    def test_local_tool_count(self):
        assert len(LOCAL_TOOLS) == 6


class TestShouldContinue:
    """조건부 엣지 테스트."""

    def test_no_tool_calls_ends(self):
        state = {"messages": [AIMessage(content="안녕하세요!")]}
        assert _should_continue(state) == "__end__"

    def test_with_tool_calls_continues(self):
        msg = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_1",
                "name": "search_restaurant",
                "args": {"query": "한식"},
            }],
        )
        state = {"messages": [msg]}
        assert _should_continue(state) == "human_gate"

    def test_human_message_ends(self):
        state = {"messages": [HumanMessage(content="테스트")]}
        assert _should_continue(state) == "__end__"
