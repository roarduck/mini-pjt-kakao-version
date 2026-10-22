"""uvicorn 진입점."""

import uvicorn

from app import app

if __name__ == "__main__":
    print("=" * 60)
    print("  AI 맛집 컨시어지 챗봇")
    print("  http://localhost:8000      — 채팅 UI")
    print("  http://localhost:8000/docs — API 문서")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
