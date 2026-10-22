"""RAG 파이프라인 — 정책 문서 검색."""

from __future__ import annotations

from pathlib import Path

from src.config import DATA_DIR


def _load_docs() -> dict[str, str]:
    """data/docs/ 아래 마크다운 문서를 로드한다. {파일명: 내용}"""
    docs_dir = DATA_DIR / "docs"
    if not docs_dir.exists():
        return {}
    result = {}
    for md in docs_dir.glob("*.md"):
        result[md.name] = md.read_text(encoding="utf-8")
    return result


def _keyword_score(text: str, query: str) -> int:
    """query의 각 단어가 text에 등장하는 횟수를 합산한다."""
    text_lower = text.lower()
    score = 0
    for word in query.lower().split():
        if len(word) >= 2 and word in text_lower:
            score += text_lower.count(word)
    return score


def search_policy(query: str) -> list[dict]:
    """정책·에티켓·알레르기 문서에서 관련 단락을 검색한다.

    Args:
        query: 검색 키워드 (예: "취소", "노쇼", "알레르기").

    Returns:
        매칭된 단락 리스트 [{source, content, score}].
    """
    docs = _load_docs()
    results = []

    for filename, content in docs.items():
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        for para in paragraphs:
            score = _keyword_score(para, query)
            if score > 0:
                results.append({
                    "source": f"docs/{filename}",
                    "content": para,
                    "score": score,
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5]
