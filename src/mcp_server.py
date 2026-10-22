"""MCP 서버 — 내부 유틸리티 도구 (calculate_budget, get_current_time)."""

from datetime import datetime

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("concierge-utils")


@mcp.tool()
def calculate_budget(price_per_person: int, party_size: int) -> str:
    """1인당 가격과 인원수로 총 예산을 계산한다.

    Args:
        price_per_person: 1인당 예상 가격 (원).
        party_size: 인원수.
    """
    total = price_per_person * party_size
    return (
        f"예상 총 비용: {total:,}원\n"
        f"  1인당: {price_per_person:,}원 × {party_size}명"
    )


@mcp.tool()
def get_current_time() -> str:
    """현재 날짜와 시간을 반환한다 (영업시간 판단용)."""
    now = datetime.now()
    weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
    return f"현재 시각: {now.strftime('%Y-%m-%d %H:%M')} ({weekday}요일)"


if __name__ == "__main__":
    mcp.run(transport="stdio")
