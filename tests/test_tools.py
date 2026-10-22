"""도구 테스트 — 카카오맵 API 모킹 기반."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.tools import (
    LOCAL_TOOLS,
    _cache_places,
    _menu_cache,
    _place_cache,
    _review_cache,
    cancel_reservation,
    check_availability,
    get_menu,
    get_reviews,
    make_reservation,
    search_restaurant,
)

# ── 테스트 픽스처 ──

MOCK_KAKAO_RESPONSE = {
    "documents": [
        {
            "id": "26338954",
            "place_name": "테스트 한식당",
            "category_name": "음식점 > 한식 > 육류,고기",
            "phone": "02-1234-5678",
            "address_name": "서울 강남구 역삼동 123",
            "road_address_name": "서울 강남구 테헤란로 123",
            "x": "127.0276",
            "y": "37.4979",
            "place_url": "http://place.map.kakao.com/26338954",
            "distance": "500",
        },
        {
            "id": "12345678",
            "place_name": "테스트 일식당",
            "category_name": "음식점 > 일식 > 초밥,롤",
            "phone": "02-9876-5432",
            "address_name": "서울 강남구 역삼동 456",
            "road_address_name": "서울 강남구 테헤란로 456",
            "x": "127.0290",
            "y": "37.4985",
            "place_url": "http://place.map.kakao.com/12345678",
            "distance": "800",
        },
    ],
    "meta": {"total_count": 2, "pageable_count": 2, "is_end": True},
}

MOCK_EMPTY_RESPONSE = {
    "documents": [],
    "meta": {"total_count": 0, "pageable_count": 0, "is_end": True},
}


MOCK_BLOG_RESPONSE = [
    {
        "title": "<b>테스트 한식당</b> 솔직 후기",
        "contents": "<b>테스트 한식당</b>에 다녀왔습니다. 갈비탕이 정말 맛있고 반찬도 푸짐했어요. 직원분들도 친절합니다.",
        "url": "https://blog.kakao.com/review1",
        "blogname": "맛집탐험가",
        "datetime": "2026-10-01T12:00:00.000+09:00",
    },
    {
        "title": "강남 <b>한식</b> 맛집 추천",
        "contents": "점심시간에 방문했는데 대기 없이 바로 입장했습니다. 불고기 정식 강추합니다.",
        "url": "https://blog.kakao.com/review2",
        "blogname": "푸디로그",
        "datetime": "2026-09-15T18:30:00.000+09:00",
    },
    {
        "title": "회식 장소 추천 - <b>테스트 한식당</b>",
        "contents": "10명 단체로 방문했는데 룸도 있고 메뉴 선택지도 다양해서 좋았습니다.",
        "url": "https://blog.kakao.com/review3",
        "blogname": "직장인일상",
        "datetime": "2026-08-20T19:00:00.000+09:00",
    },
]


MOCK_LLM_MENU_RESPONSE = (
    "--- 대표 메뉴 ---\n"
    "1. 갈비탕 - 15,000원\n"
    "2. 불고기 정식 - 13,000원\n"
    "3. 된장찌개 - 9,000원\n\n"
    "--- 알레르기 정보 ---\n"
    "주요 알레르기 유발 성분: 대두(된장), 밀(면류), 달걀\n"
    "주의사항: 한식 양념에 대두(간장/된장) 성분이 포함될 수 있습니다."
)


@pytest.fixture(autouse=True)
def clear_cache():
    """각 테스트 전에 캐시를 초기화한다."""
    _place_cache.clear()
    _menu_cache.clear()
    _review_cache.clear()
    yield
    _place_cache.clear()
    _menu_cache.clear()
    _review_cache.clear()


def _populate_cache():
    """테스트용 캐시를 채운다."""
    _cache_places(MOCK_KAKAO_RESPONSE["documents"])


# ═══════════════════════════════════════════════════════════════
# 도구 목록
# ═══════════════════════════════════════════════════════════════


class TestToolList:
    def test_local_tool_count(self):
        assert len(LOCAL_TOOLS) == 6

    def test_local_tool_names(self):
        names = {t.name for t in LOCAL_TOOLS}
        expected = {
            "search_restaurant", "get_menu", "get_reviews",
            "check_availability", "make_reservation", "cancel_reservation",
        }
        assert names == expected


# ═══════════════════════════════════════════════════════════════
# 검색 도구
# ═══════════════════════════════════════════════════════════════


class TestSearchRestaurant:
    @patch("src.tools._search_kakao", return_value=MOCK_KAKAO_RESPONSE)
    def test_search_returns_results(self, mock_api):
        result = search_restaurant.invoke({"query": "한식", "location": "강남"})
        assert "테스트 한식당" in result
        assert "26338954" in result
        assert "검색 결과" in result
        mock_api.assert_called_once()

    @patch("src.tools._search_kakao", return_value=MOCK_KAKAO_RESPONSE)
    def test_search_populates_cache(self, mock_api):
        search_restaurant.invoke({"query": "한식", "location": "강남"})
        assert "26338954" in _place_cache
        assert "12345678" in _place_cache

    @patch("src.tools._search_kakao", return_value=MOCK_EMPTY_RESPONSE)
    def test_search_no_results(self, mock_api):
        result = search_restaurant.invoke({"query": "없는식당", "location": "강남"})
        assert "찾지 못했습니다" in result

    @patch("src.tools._search_kakao", return_value=MOCK_KAKAO_RESPONSE)
    def test_search_with_cuisine(self, mock_api):
        result = search_restaurant.invoke({"query": "맛집", "location": "홍대", "cuisine": "일식"})
        assert "테스트" in result

    @patch("src.tools._search_kakao", side_effect=Exception("네트워크 오류"))
    def test_search_api_error(self, mock_api):
        result = search_restaurant.invoke({"query": "한식"})
        assert "오류" in result


# ═══════════════════════════════════════════════════════════════
# 메뉴·리뷰 도구
# ═══════════════════════════════════════════════════════════════


class TestGetMenu:
    @patch("src.tools._llm_get_menu", return_value=MOCK_LLM_MENU_RESPONSE)
    def test_get_menu_with_llm(self, mock_llm):
        _populate_cache()
        result = get_menu.invoke({"restaurant_id": "26338954"})
        assert "테스트 한식당" in result
        assert "갈비탕" in result
        assert "알레르기" in result
        assert "대두" in result
        assert "AI 추정" in result
        mock_llm.assert_called_once()

    @patch("src.tools._llm_get_menu", return_value=MOCK_LLM_MENU_RESPONSE)
    def test_get_menu_caches_llm_result(self, mock_llm):
        _populate_cache()
        get_menu.invoke({"restaurant_id": "26338954"})
        get_menu.invoke({"restaurant_id": "26338954"})
        mock_llm.assert_called_once()

    @patch("src.tools._llm_get_menu", side_effect=Exception("LLM 오류"))
    def test_get_menu_llm_fallback(self, mock_llm):
        _populate_cache()
        result = get_menu.invoke({"restaurant_id": "26338954"})
        assert "테스트 한식당" in result
        assert "조회할 수 없습니다" in result

    def test_get_menu_cache_miss(self):
        result = get_menu.invoke({"restaurant_id": "99999999"})
        assert "찾을 수 없습니다" in result
        assert "search_restaurant" in result


class TestGetReviews:
    @patch("src.tools._search_blog", return_value=MOCK_BLOG_RESPONSE)
    def test_get_reviews_with_blog(self, mock_blog):
        _populate_cache()
        result = get_reviews.invoke({"restaurant_id": "26338954"})
        assert "테스트 한식당" in result
        assert "솔직 후기" in result
        assert "맛집탐험가" in result
        assert "blog.kakao.com" in result
        assert "#review" in result
        mock_blog.assert_called_once()

    @patch("src.tools._search_blog", return_value=MOCK_BLOG_RESPONSE)
    def test_get_reviews_caches_blog_result(self, mock_blog):
        _populate_cache()
        get_reviews.invoke({"restaurant_id": "26338954"})
        get_reviews.invoke({"restaurant_id": "26338954"})
        mock_blog.assert_called_once()

    @patch("src.tools._search_blog", side_effect=Exception("API 오류"))
    def test_get_reviews_blog_fallback(self, mock_blog):
        _populate_cache()
        result = get_reviews.invoke({"restaurant_id": "26338954"})
        assert "테스트 한식당" in result
        assert "찾지 못했습니다" in result
        assert "#review" in result

    def test_get_reviews_cache_miss(self):
        result = get_reviews.invoke({"restaurant_id": "99999999"})
        assert "찾을 수 없습니다" in result


# ═══════════════════════════════════════════════════════════════
# 예약 도구
# ═══════════════════════════════════════════════════════════════


class TestReservation:
    def test_check_availability(self):
        _populate_cache()
        result = check_availability.invoke({
            "restaurant_id": "26338954",
            "date": "2026-12-25",
            "time": "18:30",
            "party_size": 4,
        })
        assert "테스트 한식당" in result
        assert "예약" in result or "자리" in result
        assert "시뮬레이션" in result
        assert "catchtable.co.kr" in result

    def test_check_availability_cache_miss(self):
        result = check_availability.invoke({
            "restaurant_id": "99999999",
            "date": "2026-12-25",
            "time": "18:30",
            "party_size": 4,
        })
        assert "찾을 수 없습니다" in result

    def test_make_reservation(self):
        _populate_cache()
        result = make_reservation.invoke({
            "restaurant_id": "26338954",
            "date": "2026-12-25",
            "time": "18:30",
            "party_size": 4,
        })
        assert "RSV-" in result
        assert "테스트 한식당" in result
        assert "예약" in result
        assert "시뮬레이션" in result
        assert "catchtable.co.kr" in result

    def test_make_reservation_invalid_party(self):
        _populate_cache()
        result = make_reservation.invoke({
            "restaurant_id": "26338954",
            "date": "2026-12-25",
            "time": "18:30",
            "party_size": 0,
        })
        assert "1명 이상" in result

    def test_make_reservation_too_large_party(self):
        _populate_cache()
        result = make_reservation.invoke({
            "restaurant_id": "26338954",
            "date": "2026-12-25",
            "time": "18:30",
            "party_size": 25,
        })
        assert "20명" in result

    def test_cancel_reservation_valid(self):
        result = cancel_reservation.invoke({
            "reservation_id": "RSV-ABC12345",
            "reason": "일정 변경",
        })
        assert "취소 완료" in result
        assert "RSV-ABC12345" in result
        assert "시뮬레이션" in result

    def test_cancel_reservation_invalid_id(self):
        result = cancel_reservation.invoke({
            "reservation_id": "INVALID-123",
        })
        assert "유효하지 않은" in result


# ═══════════════════════════════════════════════════════════════
# MCP 유틸리티 도구 (직접 함수 테스트)
# ═══════════════════════════════════════════════════════════════


class TestMCPUtilities:
    def test_calculate_budget(self):
        from src.mcp_server import calculate_budget
        result = calculate_budget(price_per_person=20000, party_size=4)
        assert "80,000" in result
        assert "20,000" in result

    def test_get_current_time(self):
        from src.mcp_server import get_current_time
        result = get_current_time()
        assert "현재 시각" in result
        assert "요일" in result
