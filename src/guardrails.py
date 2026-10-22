"""입력 가드 · PII 마스킹 · 도구 위험도 분류."""

from __future__ import annotations

import re

# ═══════════════════════════════════════════════════════════════
# 도구 위험도 분류
# ═══════════════════════════════════════════════════════════════

RISK_LEVELS: dict[str, str] = {
    "search_restaurant": "read",
    "get_menu": "read",
    "get_reviews": "read",
    "check_availability": "read",
    "calculate_budget": "read",
    "get_current_time": "read",
    "make_reservation": "write",
    "cancel_reservation": "destructive",
}

DEFAULT_RISK = "write"


def get_risk_level(tool_name: str) -> str:
    """도구의 위험도를 반환한다. 미등록 도구는 write로 간주한다."""
    return RISK_LEVELS.get(tool_name, DEFAULT_RISK)


# ═══════════════════════════════════════════════════════════════
# 입력 가드 — 정규식 기반 프롬프트 주입 및 금지 주제 탐지
# ═══════════════════════════════════════════════════════════════

INJECTION_PATTERNS = [
    re.compile(r"(ignore|disregard|forget).*(previous|above|instruction)", re.I),
    re.compile(r"(system|admin)\s*prompt", re.I),
    re.compile(r"you\s+are\s+now", re.I),
    re.compile(r"act\s+as\s+(a\s+)?different", re.I),
]

FORBIDDEN_TOPICS = [
    re.compile(r"(의료|진단|처방|약물)", re.I),
    re.compile(r"(법률|소송|판례)", re.I),
]


def check_input(text: str) -> dict:
    """사용자 입력의 안전성을 검사한다.

    Returns:
        {"allowed": bool, "reason": str}
    """
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return {"allowed": False, "reason": "프롬프트 주입이 감지되어 요청이 거부되었습니다."}

    for pattern in FORBIDDEN_TOPICS:
        if pattern.search(text):
            return {
                "allowed": False,
                "reason": "해당 주제는 전문가 상담을 권장합니다. 맛집 관련 질문을 해주세요.",
            }

    return {"allowed": True, "reason": ""}


# ═══════════════════════════════════════════════════════════════
# PII 마스킹
# ═══════════════════════════════════════════════════════════════

_PII_PATTERNS = [
    (re.compile(r"01[016789]-?\d{3,4}-?\d{4}"), "[MASKED_PHONE]"),
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[MASKED_EMAIL]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[MASKED_AWS_KEY]"),
    (re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"), "[MASKED_JWT]"),
]


def mask_pii(text: str) -> str:
    """텍스트에서 PII를 마스킹한다."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
