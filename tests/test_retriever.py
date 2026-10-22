"""RAG 검색 단위 테스트 — 정책 문서 검색."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retriever import search_policy, _load_docs


class TestDataLoading:
    """데이터 로딩 테스트."""

    def test_docs_loaded(self):
        docs = _load_docs()
        assert len(docs) > 0
        assert any("policy" in name for name in docs.keys())


class TestSearchPolicy:
    """정책 문서 검색 테스트."""

    def test_search_cancellation(self):
        results = search_policy("취소")
        assert len(results) > 0
        assert any("취소" in r["content"] for r in results)

    def test_search_allergy(self):
        results = search_policy("알레르기")
        assert len(results) > 0

    def test_search_no_match(self):
        results = search_policy("xyzxyzxyz")
        assert len(results) == 0

    def test_result_has_source(self):
        results = search_policy("예약")
        if results:
            assert "source" in results[0]
            assert "content" in results[0]
            assert "score" in results[0]
