"""FastAPI 서버 — POST /query (제출 규약) + 채팅 SSE 스트리밍."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pathlib import Path
from pydantic import BaseModel, Field

from src.agent import build_graph, SYSTEM_PROMPT, ChatState
from src.config import CHECKPOINT_DB, get_text
from src.guardrails import check_input, mask_pii

# ── 비동기 그래프 (lifespan에서 초기화) ──
_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """AsyncSqliteSaver를 앱 수명주기에 맞춰 관리한다."""
    global _graph
    async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB) as checkpointer:
        _graph, _ = await build_graph(checkpointer=checkpointer)
        yield


# ── FastAPI 앱 ──
app = FastAPI(title="AI 맛집 컨시어지", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 정적 파일 경로 ──
_STATIC_DIR = Path(__file__).parent / "static"


# ═══════════════════════════════════════════════════════════════
# 요청/응답 모델
# ═══════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    """제출 규약 요청."""
    question: str

class QueryResponse(BaseModel):
    """제출 규약 응답."""
    answer: str
    contexts: list[str]
    trace: list[str]

class ChatRequest(BaseModel):
    """채팅 요청."""
    session_id: str
    message: str

class ApproveRequest(BaseModel):
    """HITL 승인 요청."""
    session_id: str
    action: str = Field(description="approve 또는 reject")
    reason: str = ""


# ═══════════════════════════════════════════════════════════════
# 엔드포인트
# ═══════════════════════════════════════════════════════════════

@app.get("/")
async def serve_index():
    """채팅 UI를 서빙한다."""
    index_path = _STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "static/index.html을 생성해주세요."}


@app.post("/query", response_model=QueryResponse)
async def query_endpoint(req: QueryRequest):
    """제출 규약 엔드포인트 — question → answer, contexts, trace."""
    from src.agent import run_query
    result = run_query(req.question, thread_id=f"query-{uuid.uuid4().hex[:8]}")
    return QueryResponse(**result)


@app.post("/api/session/new")
async def new_session():
    """새 세션 ID를 생성한다."""
    return {"session_id": uuid.uuid4().hex}


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """채팅 엔드포인트 — SSE 스트리밍."""

    guard = check_input(req.message)
    if not guard["allowed"]:
        async def blocked_stream():
            yield f"data: {json.dumps({'type': 'blocked', 'reason': guard['reason']}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(blocked_stream(), media_type="text/event-stream")

    masked = mask_pii(req.message)
    config = {"configurable": {"thread_id": req.session_id}}

    async def event_stream():
        try:
            collected_text = ""
            async for event in _graph.astream_events(
                {"messages": [HumanMessage(content=masked)]},
                config=config,
                version="v2",
            ):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    node = event.get("metadata", {}).get("langgraph_node", "")
                    if node != "agent":
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = chunk.content if hasattr(chunk, "content") else ""
                        if isinstance(content, list):
                            token = "".join(
                                b.get("text", "") for b in content if isinstance(b, dict)
                            )
                        elif isinstance(content, str):
                            token = content
                        else:
                            token = ""
                        if token:
                            collected_text += token
                            yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

            state = await _graph.aget_state(config)
            if state.next:
                for task in state.tasks:
                    if hasattr(task, "interrupts") and task.interrupts:
                        for intr in task.interrupts:
                            val = intr.value if hasattr(intr, "value") else intr
                            yield f"data: {json.dumps({'type': 'approval_required', **val}, ensure_ascii=False)}\n\n"
                            break

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'reason': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/chat/approve")
async def approve_endpoint(req: ApproveRequest):
    """HITL 승인/거부를 처리하고 결과를 SSE로 스트리밍한다."""
    config = {"configurable": {"thread_id": req.session_id}}

    if req.action == "approve":
        resume_data = {"action": "approve"}
    else:
        resume_data = {"action": "reject", "reason": req.reason or "사용자가 거부했습니다"}

    async def event_stream():
        try:
            async for event in _graph.astream_events(
                Command(resume=resume_data),
                config=config,
                version="v2",
            ):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    node = event.get("metadata", {}).get("langgraph_node", "")
                    if node != "agent":
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = chunk.content if hasattr(chunk, "content") else ""
                        if isinstance(content, list):
                            token = "".join(
                                b.get("text", "") for b in content if isinstance(b, dict)
                            )
                        elif isinstance(content, str):
                            token = content
                        else:
                            token = ""
                        if token:
                            yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

            state = await _graph.aget_state(config)
            if state.next:
                for task in state.tasks:
                    if hasattr(task, "interrupts") and task.interrupts:
                        for intr in task.interrupts:
                            val = intr.value if hasattr(intr, "value") else intr
                            yield f"data: {json.dumps({'type': 'approval_required', **val}, ensure_ascii=False)}\n\n"
                            break

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'reason': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
