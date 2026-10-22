"""도메인 도구 — 8개 LangChain @tool, 카카오맵 API 기반."""

from __future__ import annotations

import hashlib
from urllib.parse import quote

import httpx
from langchain_core.tools import tool

from src.config import KAKAO_REST_API_KEY, _default_llm, get_text

# ── 카카오 API 설정 ──

KAKAO_API_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_BLOG_URL = "https://dapi.kakao.com/v2/search/blog"

LOCATION_COORDS: dict[str, tuple[str, str]] = {
    "강남": ("127.0276", "37.4979"),
    "홍대": ("126.9246", "37.5563"),
    "명동": ("126.9857", "37.5636"),
    "이태원": ("126.9942", "37.5340"),
    "종로": ("126.9917", "37.5704"),
    "성수": ("127.0566", "37.5445"),
    "잠실": ("127.1003", "37.5133"),
    "여의도": ("126.9249", "37.5218"),
    "합정": ("126.9136", "37.5495"),
    "건대": ("127.0686", "37.5404"),
    "신촌": ("126.9370", "37.5552"),
    "압구정": ("127.0283", "37.5271"),
    "삼성": ("127.0635", "37.5088"),
    "을지로": ("126.9920", "37.5660"),
    "혜화": ("127.0019", "37.5822"),
    "서촌": ("126.9702", "37.5790"),
    "망원": ("126.9102", "37.5561"),
    "연남": ("126.9254", "37.5626"),
    "가로수길": ("127.0237", "37.5195"),
    "신사": ("127.0208", "37.5169"),
}
DEFAULT_COORDS = ("126.9780", "37.5665")


# ── 캐시 & HTTP 클라이언트 ──

_place_cache: dict[str, dict] = {}
_menu_cache: dict[str, str] = {}
_review_cache: dict[str, list[dict]] = {}
_http_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    """카카오 API 호출용 httpx 클라이언트를 반환한다 (lazy-init)."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(
            headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"},
            timeout=10.0,
        )
    return _http_client


def _search_kakao(
    query: str,
    x: str | None = None,
    y: str | None = None,
    radius: int = 5000,
    size: int = 5,
) -> dict:
    """카카오 키워드 검색 API를 호출한다."""
    params: dict = {
        "query": query,
        "category_group_code": "FD6",
        "size": size,
    }
    if x and y:
        params["x"] = x
        params["y"] = y
        params["radius"] = radius

    resp = _get_client().get(KAKAO_API_URL, params=params)
    resp.raise_for_status()
    return resp.json()


def _cache_places(documents: list[dict]) -> None:
    """검색 결과를 place_cache에 저장한다."""
    for doc in documents:
        pid = doc.get("id", "")
        if pid:
            _place_cache[pid] = doc


def _get_place(restaurant_id: str) -> dict | None:
    """캐시에서 식당 정보를 조회한다."""
    return _place_cache.get(restaurant_id)


def _search_blog(place_name: str, size: int = 3) -> list[dict]:
    """카카오 블로그 검색 API로 식당 리뷰를 가져온다."""
    params = {"query": f"{place_name} 맛집 후기", "size": size, "sort": "accuracy"}
    resp = _get_client().get(KAKAO_BLOG_URL, params=params)
    resp.raise_for_status()
    return resp.json().get("documents", [])


_MENU_PROMPT_TEMPLATE = """\
다음 식당의 대표 메뉴 3~5개와 알레르기 정보를 알려주세요.

식당명: {place_name}
카테고리: {category_name}
주소: {address}

반드시 아래 형식으로만 답변하세요:

--- 대표 메뉴 ---
1. [메뉴명] - [예상가격]원
2. [메뉴명] - [예상가격]원
3. [메뉴명] - [예상가격]원

--- 알레르기 정보 ---
주요 알레르기 유발 성분: [성분 나열]
주의사항: [한 줄 안내]

참고: 실제 메뉴를 모를 경우, 카테고리와 식당 특성에 기반하여 일반적인 대표 메뉴를 안내하세요."""


def _llm_get_menu(place_name: str, category_name: str, address: str) -> str:
    """LLM을 호출하여 식당의 메뉴·알레르기 정보를 조회한다."""
    llm = _default_llm()
    prompt = _MENU_PROMPT_TEMPLATE.format(
        place_name=place_name,
        category_name=category_name,
        address=address,
    )
    response = llm.invoke(prompt)
    return get_text(response)


# ═══════════════════════════════════════════════════════════════
# 검색 도구
# ═══════════════════════════════════════════════════════════════


@tool
def search_restaurant(query: str, location: str = "", cuisine: str = "") -> str:
    """카카오맵에서 식당을 검색하여 상위 5개 결과를 반환한다.

    Args:
        query: 검색 키워드 (예: "칼국수", "오마카세").
        location: 지역 필터 (예: "강남", "명동"). 빈 문자열이면 전체 지역.
        cuisine: 음식 종류 필터 (예: "한식", "일식"). 빈 문자열이면 전체.
    """
    try:
        parts = []
        if location:
            parts.append(location)
        if cuisine:
            parts.append(cuisine)
        if query:
            parts.append(query)
        search_query = " ".join(parts) if parts else "맛집"

        x, y = None, None
        if location:
            for loc_name, coords in LOCATION_COORDS.items():
                if loc_name in location:
                    x, y = coords
                    break
            if x is None:
                x, y = DEFAULT_COORDS

        data = _search_kakao(search_query, x=x, y=y)
        documents = data.get("documents", [])

        if not documents:
            return f"검색 조건(query='{query}', location='{location}', cuisine='{cuisine}')에 맞는 식당을 찾지 못했습니다."

        _cache_places(documents)

        lines = [f"검색 결과 (총 {len(documents)}건):"]
        for doc in documents:
            distance = doc.get("distance", "")
            dist_str = f" | 거리: {distance}m" if distance else ""
            lines.append(
                f"\n[{doc['place_name']}] (ID: {doc['id']})\n"
                f"  카테고리: {doc.get('category_name', 'N/A')}\n"
                f"  주소: {doc.get('road_address_name', '') or doc.get('address_name', 'N/A')}\n"
                f"  전화: {doc.get('phone', '정보 없음') or '정보 없음'}{dist_str}\n"
                f"  카카오맵: {doc.get('place_url', '')}"
            )
        return "\n".join(lines)
    except httpx.HTTPStatusError as e:
        return f"카카오맵 API 오류 (HTTP {e.response.status_code}): API 키를 확인해주세요."
    except Exception as e:
        return f"검색 중 오류: {e}"


@tool
def get_menu(restaurant_id: str) -> str:
    """특정 식당의 메뉴·가격·알레르기 정보를 반환한다.

    카카오맵 기본 정보와 LLM 기반 메뉴 추정을 결합하여 제공한다.

    Args:
        restaurant_id: 카카오맵 식당 ID (예: "26338954"). search_restaurant 결과에서 확인 가능.
    """
    try:
        place = _get_place(restaurant_id)
        if place is None:
            return (
                f"'{restaurant_id}'를 찾을 수 없습니다. "
                f"먼저 search_restaurant로 식당을 검색해주세요."
            )

        place_name = place["place_name"]
        category = place.get("category_name", "N/A")
        address = place.get("road_address_name", "") or place.get("address_name", "N/A")
        phone = place.get("phone", "정보 없음") or "정보 없음"
        place_url = place.get("place_url", "")

        header = [
            f"=== {place_name} 메뉴 정보 ===",
            f"카테고리: {category}",
            f"주소: {address}",
            f"전화: {phone}",
            "",
        ]

        if restaurant_id in _menu_cache:
            menu_info = _menu_cache[restaurant_id]
        else:
            try:
                menu_info = _llm_get_menu(place_name, category, address)
                _menu_cache[restaurant_id] = menu_info
            except Exception:
                menu_info = (
                    "--- 대표 메뉴 ---\n"
                    "메뉴 정보를 조회할 수 없습니다.\n\n"
                    "--- 알레르기 정보 ---\n"
                    "알레르기 정보를 조회할 수 없습니다."
                )

        footer = [
            "",
            f"※ 메뉴·가격은 AI 추정이며 실제와 다를 수 있습니다.",
            f"   정확한 정보는 카카오맵에서 확인하세요: {place_url}",
        ]

        return "\n".join(header) + menu_info + "\n".join(footer)
    except Exception as e:
        return f"메뉴 조회 오류: {e}"


# ═══════════════════════════════════════════════════════════════
# 리뷰 도구
# ═══════════════════════════════════════════════════════════════


@tool
def get_reviews(restaurant_id: str) -> str:
    """특정 식당의 블로그 리뷰와 카카오맵 리뷰 링크를 안내한다.

    Args:
        restaurant_id: 카카오맵 식당 ID (예: "26338954"). search_restaurant 결과에서 확인 가능.
    """
    try:
        place = _get_place(restaurant_id)
        if place is None:
            return (
                f"'{restaurant_id}'를 찾을 수 없습니다. "
                f"먼저 search_restaurant로 식당을 검색해주세요."
            )

        place_name = place["place_name"]
        review_url = place.get("place_url", "") + "#review"

        lines = [f"=== {place_name} 리뷰 ===", ""]

        if restaurant_id in _review_cache:
            blogs = _review_cache[restaurant_id]
        else:
            try:
                blogs = _search_blog(place_name)
                _review_cache[restaurant_id] = blogs
            except Exception:
                blogs = []

        if blogs:
            lines.append("--- 블로그 리뷰 ---")
            for idx, blog in enumerate(blogs, 1):
                title = blog.get("title", "").replace("<b>", "").replace("</b>", "")
                contents = blog.get("contents", "").replace("<b>", "").replace("</b>", "")
                if len(contents) > 100:
                    contents = contents[:100] + "..."
                blog_url = blog.get("url", "")
                blogname = blog.get("blogname", "")
                lines.append(f"\n{idx}. {title}")
                if blogname:
                    lines.append(f"   작성자: {blogname}")
                lines.append(f"   {contents}")
                if blog_url:
                    lines.append(f"   원문: {blog_url}")
            lines.append("")
        else:
            lines.append("블로그 리뷰를 찾지 못했습니다.")
            lines.append("")

        lines.append("--- 카카오맵 리뷰 ---")
        lines.append(f"더 많은 리뷰는 카카오맵에서 확인하세요: {review_url}")

        return "\n".join(lines)
    except Exception as e:
        return f"리뷰 조회 오류: {e}"


# ═══════════════════════════════════════════════════════════════
# 예약 도구
# ═══════════════════════════════════════════════════════════════


@tool
def check_availability(restaurant_id: str, date: str, time: str, party_size: int) -> str:
    """식당의 예약 가능 여부를 확인한다 (시뮬레이션).

    Args:
        restaurant_id: 카카오맵 식당 ID.
        date: 예약 날짜 (예: "2026-12-25").
        time: 예약 시간 (예: "18:30").
        party_size: 인원수.
    """
    try:
        place = _get_place(restaurant_id)
        if place is None:
            return (
                f"오류: '{restaurant_id}'를 찾을 수 없습니다. "
                f"먼저 search_restaurant로 식당을 검색해주세요."
            )

        name = place["place_name"]
        h = int(hashlib.md5(f"{restaurant_id}-{date}-{time}".encode()).hexdigest(), 16)
        available = (h % 4) != 0

        qname = quote(name)
        catchtable_url = (
            f"https://app.catchtable.co.kr/ct/map/search-map"
            f"?showTabs=true&bottomSheetHeightType=PARTIAL_MAP&serviceType=INTEGRATION"
            f"&keyword={qname}&keywordSearch={qname}"
            f"&uniqueListId=1792646992873&bottomSheetHeightPx=493.0625&zoom=4.5"
            f"&centerBoundsLat=31.449579287271504&centerBoundsLng=128.02662846632302"
            f"&searchedMapLevel=4.5&showSubFilterInMap=1&isNewSearchInMap=1"
            f"&isShowMapSearchButton=1&showTargetShopTooltip=0&isSettingTargetShopBound=0"
        )
        notice = (
            f"\n\n※ 시뮬레이션 결과이며 현재 대화 내에서만 유효합니다.\n"
            f"   실제 예약은 캐치테이블에서 진행하세요: {catchtable_url}"
        )

        if available:
            return f"{name}에 {date} {time}, {party_size}명 예약이 가능합니다." + notice
        else:
            return f"죄송합니다. {name}의 {date} {time}에는 자리가 없습니다. 다른 시간을 시도해 주세요." + notice
    except Exception as e:
        return f"가용성 확인 오류: {e}"


@tool
def make_reservation(restaurant_id: str, date: str, time: str, party_size: int) -> str:
    """식당 예약을 생성한다 (쓰기 작업 — HITL 승인 필요).

    Args:
        restaurant_id: 카카오맵 식당 ID.
        date: 예약 날짜 (예: "2026-12-25").
        time: 예약 시간 (예: "18:30").
        party_size: 인원수 (1~20명).
    """
    try:
        place = _get_place(restaurant_id)
        if place is None:
            return (
                f"예약 실패: '{restaurant_id}'를 찾을 수 없습니다. "
                f"먼저 search_restaurant로 식당을 검색해주세요."
            )
        if party_size < 1:
            return "예약 실패: 인원수는 1명 이상이어야 합니다."
        if party_size > 20:
            return "예약 실패: 20명 이상은 전화 문의 바랍니다."

        name = place["place_name"]
        phone = place.get("phone", "정보 없음") or "정보 없음"

        rid = hashlib.md5(
            f"{restaurant_id}-{date}-{time}-{party_size}".encode()
        ).hexdigest()[:8].upper()

        qname = quote(name)
        catchtable_url = (
            f"https://app.catchtable.co.kr/ct/map/search-map"
            f"?showTabs=true&bottomSheetHeightType=PARTIAL_MAP&serviceType=INTEGRATION"
            f"&keyword={qname}&keywordSearch={qname}"
            f"&uniqueListId=1792646992873&bottomSheetHeightPx=493.0625&zoom=4.5"
            f"&centerBoundsLat=31.449579287271504&centerBoundsLng=128.02662846632302"
            f"&searchedMapLevel=4.5&showSubFilterInMap=1&isNewSearchInMap=1"
            f"&isShowMapSearchButton=1&showTargetShopTooltip=0&isSettingTargetShopBound=0"
        )

        return (
            f"=== 예약 확인 ===\n"
            f"예약번호: RSV-{rid}\n"
            f"식당: {name}\n"
            f"날짜: {date}\n"
            f"시간: {time}\n"
            f"인원: {party_size}명\n"
            f"전화: {phone}\n"
            f"\n예약이 성공적으로 완료되었습니다.\n"
            f"\n※ 시뮬레이션 결과이며 현재 대화 내에서만 유효합니다.\n"
            f"   실제 예약은 캐치테이블에서 진행하세요: {catchtable_url}"
        )
    except Exception as e:
        return f"예약 처리 오류: {e}"


@tool
def cancel_reservation(reservation_id: str, reason: str = "") -> str:
    """예약을 취소한다 (파괴적 작업 — HITL 승인 필요).

    Args:
        reservation_id: 예약번호 (예: "RSV-A1B2C3D4").
        reason: 취소 사유.
    """
    try:
        if not reservation_id.startswith("RSV-"):
            return "오류: 유효하지 않은 예약번호입니다. 'RSV-'로 시작해야 합니다."

        return (
            f"=== 예약 취소 완료 ===\n"
            f"예약번호: {reservation_id}\n"
            f"취소 사유: {reason or '사유 없음'}\n"
            f"환불: 24시간 전 취소로 전액 환불 처리됩니다.\n"
            f"\n취소가 완료되었습니다.\n"
            f"\n※ 시뮬레이션 결과이며 현재 대화 내에서만 유효합니다. 실제 취소는 식당에 직접 문의하세요."
        )
    except Exception as e:
        return f"취소 처리 오류: {e}"


# ── 로컬 도구 목록 (MCP 제외) ──
LOCAL_TOOLS = [
    search_restaurant,
    get_menu,
    get_reviews,
    check_availability,
    make_reservation,
    cancel_reservation,
]
