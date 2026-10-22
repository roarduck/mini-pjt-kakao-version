"""메인 에이전트 그래프 — LangGraph StateGraph + HITL 승인 게이트."""

from __future__ import annotations

import asyncio
import re
import sqlite3
import sys
from pathlib import Path
from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from src.config import CHECKPOINT_DB, _default_llm, get_text
from src.guardrails import get_risk_level
from src.tools import LOCAL_TOOLS

# ── MCP 도구 로드 ──
_MCP_SERVER_PATH = str(Path(__file__).resolve().parent / "mcp_server.py")

_mcp_tools: list | None = None


async def _load_mcp_tools() -> list:
    """MCP 서버에서 유틸리티 도구를 로드한다 (최초 1회)."""
    global _mcp_tools
    if _mcp_tools is not None:
        return _mcp_tools

    client = MultiServerMCPClient(
        {
            "concierge-utils": {
                "command": sys.executable,
                "args": [_MCP_SERVER_PATH],
                "transport": "stdio",
            }
        }
    )
    _mcp_tools = await client.get_tools()
    return _mcp_tools


async def _get_all_tools() -> list:
    """로컬 도구 + MCP 도구를 합쳐 반환한다."""
    return LOCAL_TOOLS + await _load_mcp_tools()

# ── 시스템 프롬프트 ──
SYSTEM_PROMPT = """\
당신은 서울 맛집 컨시어지 AI입니다.

역할:
- 사용자의 요청에 따라 카카오맵 API를 통해 실시간으로 맛집을 검색하고, 예약을 도와줍니다.
- 친절하고 자연스러운 한국어로 대화합니다.
- 도구를 활용하여 정확한 정보를 제공합니다.

규칙:
1. 맛집 추천 시 반드시 search_restaurant 도구로 카카오맵에서 검색하세요.
2. 메뉴·리뷰 정보는 카카오맵 링크를 안내하세요 (get_menu, get_reviews 도구 활용).
3. 예약(check_availability, make_reservation) 전에 반드시 search_restaurant로 식당을 먼저 검색하세요.
4. 예약 요청 시 날짜, 시간, 인원을 반드시 확인한 후 make_reservation 도구를 사용하세요.
5. 도구를 통해 검색된 실제 데이터만으로 답변하세요. 데이터에 없는 정보를 생성하지 마세요.
6. 검색 결과가 없으면 "해당 정보를 찾을 수 없습니다"라고 안내하세요.
7. 의료/법률 등 전문 영역 질문에는 "전문가 상담을 권장합니다"라고 안내하세요.
8. 카카오맵에서 제공하지 않는 정보(상세 메뉴, 가격, 리뷰 등)는 카카오맵 페이지 링크를 안내하세요.
9. 예약 관련 도구(check_availability, make_reservation, cancel_reservation) 결과에 포함된 시뮬레이션 안내 문구와 캐치테이블 링크를 사용자에게 반드시 전달하세요. 해당 내용을 생략하거나 요약하지 마세요.
10. 메뉴 정보를 안내할 때는 사용자가 별도로 요청하지 않더라도 알레르기 정보를 항상 함께 제공하세요. get_menu 도구 결과에 포함된 알레르기 정보를 생략하지 마세요.
"""


# ── 상태 정의 ──
class ChatState(TypedDict):
    """에이전트 대화 상태."""
    messages: Annotated[list[AnyMessage], add_messages]


# ── 노드 함수 ──
def agent_node(state: ChatState, *, llm=None, tools=None) -> dict:
    """LLM을 호출하여 응답 또는 도구 호출을 결정한다."""
    model = llm or _default_llm()
    all_tools = tools or _get_all_tools()
    model_with_tools = model.bind_tools(all_tools)

    messages = state["messages"]
    if not any(isinstance(m, SystemMessage) for m in messages):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

    response = model_with_tools.invoke(messages)
    return {"messages": [response]}


async def human_gate(state: ChatState, *, tools=None) -> dict:
    """도구 호출의 위험도를 확인하고, write/destructive는 HITL 승인을 요청한다."""
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {"messages": []}

    tool_map = {t.name: t for t in (tools or await _get_all_tools())}
    results: list[ToolMessage] = []

    for tc in last.tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        risk = get_risk_level(tool_name)

        if risk == "read":
            tool_fn = tool_map.get(tool_name)
            if tool_fn:
                output = await tool_fn.ainvoke(tool_args)
            else:
                output = f"오류: 알 수 없는 도구 '{tool_name}'"
            results.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))
        else:
            decision = interrupt({
                "tool_name": tool_name,
                "tool_args": tool_args,
                "risk_level": risk,
                "message": f"[{risk.upper()}] '{tool_name}' 도구를 실행하려고 합니다. 승인하시겠습니까?",
            })

            action = decision.get("action", "reject") if isinstance(decision, dict) else "reject"

            if action == "approve":
                tool_fn = tool_map.get(tool_name)
                if tool_fn:
                    output = await tool_fn.ainvoke(tool_args)
                else:
                    output = f"오류: 알 수 없는 도구 '{tool_name}'"
                results.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))

            elif action == "modify":
                modified_args = decision.get("args", tool_args)
                tool_fn = tool_map.get(tool_name)
                if tool_fn:
                    output = await tool_fn.ainvoke(modified_args)
                else:
                    output = f"오류: 알 수 없는 도구 '{tool_name}'"
                results.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))

            else:
                reason = decision.get("reason", "사용자가 거부했습니다") if isinstance(decision, dict) else "사용자가 거부했습니다"
                results.append(ToolMessage(
                    content=f"도구 실행이 거부되었습니다: {reason}",
                    tool_call_id=tc["id"],
                ))

    return {"messages": results}


def _should_continue(state: ChatState) -> str:
    """마지막 메시지에 tool_calls가 있으면 human_gate로, 없으면 종료."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "human_gate"
    return END


# ── 그래프 빌더 ──
async def build_graph(llm=None, checkpointer=None):
    """LangGraph 에이전트 그래프를 빌드하고 체크포인터를 연결한다.

    Args:
        llm: LLM 인스턴스. None이면 기본 LLM 사용.
        checkpointer: 체크포인터. None이면 동기 SqliteSaver 사용.

    Returns:
        (compiled_graph, checkpointer) 튜플.
    """
    all_tools = await _get_all_tools()

    def _agent(state: ChatState) -> dict:
        return agent_node(state, llm=llm, tools=all_tools)

    async def _human_gate(state: ChatState) -> dict:
        return await human_gate(state, tools=all_tools)

    graph = StateGraph(ChatState)
    graph.add_node("agent", _agent)
    graph.add_node("human_gate", _human_gate)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _should_continue, {"human_gate": "human_gate", END: END})
    graph.add_edge("human_gate", "agent")

    if checkpointer is None:
        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    compiled = graph.compile(checkpointer=checkpointer)
    return compiled, checkpointer


# ── 제출 규약용 동기 실행 ──
def run_query(question: str, thread_id: str = "default") -> dict:
    """질문을 처리하고 제출 규약 형식으로 반환한다.

    Returns:
        {"answer": str, "contexts": list[str], "trace": list[str]}
    """
    graph, _ = asyncio.run(build_graph())
    config = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(
        {"messages": [("human", question)]},
        config=config,
    )

    answer = ""
    contexts = []
    trace = []

    for msg in result["messages"]:
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            answer = get_text(msg)
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                trace.append(f"{tc['name']}({tc['args']})")
        elif isinstance(msg, ToolMessage):
            content = msg.content
            kakao_ids = re.findall(r"ID:\s*(\d{5,})", content)
            for kid in kakao_ids:
                ctx = f"kakao_place:{kid}"
                if ctx not in contexts:
                    contexts.append(ctx)
            urls = re.findall(r"https?://place\.map\.kakao\.com/\d+", content)
            for url in urls:
                if url not in contexts:
                    contexts.append(url)

    return {"answer": answer, "contexts": contexts, "trace": trace}
