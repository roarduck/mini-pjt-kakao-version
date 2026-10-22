# 미니 PJT: AI 맛집 컨시어지 (카카오맵 API 버전)

## 무엇을 푸나
서울에서 "어디서 뭘 먹을지" 결정부터 리뷰 확인, 예약까지의 전 과정을 **하나의 대화**로 해결한다.

## 활용한 패턴
- **ReAct (도구 자율 선택)**: `bind_tools`로 8개 도구를 LLM에 바인딩, 에이전트가 검색→메뉴→리뷰→예약 플로우에서 도구를 자율 선택·호출
- **RAG (정책 문서 검색)**: 예약 정책·식사 예절·알레르기 가이드 문서를 키워드 검색(`retriever.py`)으로 조회하여 답변에 반영
- **도구 다중 (외부 API·계산기·LLM)**: 카카오맵 API(검색), 블로그 검색 API(리뷰), LLM(메뉴 추정), 예산 계산기(MCP) 등 한 대화에서 복수 도구 자율 결합
- **MCP 서버 연동**: 유틸리티 도구(예산 계산, 현재 시간)를 FastMCP 서버로 분리, `langchain-mcp-adapters`로 에이전트에 통합
- **가드레일 (PII·프롬프트 인젝션 방어)**: 정규식 프롬프트 주입 차단 + PII 마스킹(전화번호·이메일·API키) + 금지 주제 거부
- **HITL (위험 작업 승인)**: 도구를 read/write/destructive로 분류하고, `interrupt()`로 예약 생성·취소 시 사용자 승인을 요구
- **미들웨어 (PII 마스킹)**: FastAPI 입력 전처리 단계에서 `mask_pii`로 개인정보를 마스킹한 뒤 LLM에 전달
- **SSE 스트리밍**: FastAPI + `astream_events`로 실시간 토큰 스트리밍 응답

## 아키텍처

```
사용자 (브라우저)
  │
  ▼
FastAPI (app.py)
  ├─ POST /query        ← 제출 규약 (JSON)
  ├─ POST /api/chat     ← 채팅 (SSE 스트리밍)
  └─ POST /api/chat/approve  ← HITL 승인
  │
  ▼
입력 가드 (guardrails.py)
  ├─ 주입 패턴 차단
  └─ PII 마스킹
  │
  ▼
LangGraph 에이전트 (agent.py)
  ├─ agent 노드: LLM + 도구 바인딩
  ├─ human_gate 노드: 위험도 분류 → read 자동 / write·destructive HITL
  └─ AsyncSqliteSaver: 세션 영속화
  │
  ▼
도구 (tools.py — 로컬 6개)
  ├─ search_restaurant ←→ 카카오맵 Local REST API (실시간 검색)
  ├─ get_menu ←→ LLM (메뉴·알레르기 추정)
  ├─ get_reviews ←→ 카카오 블로그 검색 API (리뷰 3건) + 카카오맵 리뷰 탭 링크
  ├─ check_availability ←→ 예약 가능 여부 시뮬레이션 + 캐치테이블 링크
  ├─ make_reservation ←→ 예약 생성 시뮬레이션 (HITL) + 캐치테이블 링크
  └─ cancel_reservation ←→ 예약 취소 시뮬레이션 (HITL)
MCP 서버 (mcp_server.py — 유틸 2개, stdio)
  ├─ calculate_budget
  └─ get_current_time
정책 검색 (retriever.py) ←→ data/docs/ (RAG)
```

## 기술 스택

| 구분 | 기술 |
|------|------|
| LLM | Claude Sonnet 4.5 via Amazon Bedrock |
| 프레임워크 | LangChain · LangGraph |
| 모델 호출 | `ChatBedrockConverse` (langchain-aws) |
| 체크포인터 | SQLite (`AsyncSqliteSaver`) |
| API 서버 | FastAPI (SSE 스트리밍) |
| 외부 API | 카카오맵 Local REST API · 카카오 블로그 검색 API |
| HTTP 클라이언트 | httpx |
| MCP | mcp (FastMCP) · langchain-mcp-adapters |
| 가드레일 | 정규식 입력 가드 · PII 마스킹 · HITL 승인 게이트 |

## 실행 방법

```bash
# 1. 환경변수 설정
cp .env.example .env
# .env 파일에 KAKAO_REST_API_KEY, AWS 키 입력

# 2. 의존성 설치
pip install -r requirements.txt  # 또는 개별 설치

# 3. 서버 실행
python run.py

# 4. 브라우저 접속
# http://localhost:8000 — 채팅 UI
# http://localhost:8000/docs — API 문서
```

## 인-아웃 세트 통과율 (자체 평가)
- 평가 세트: `evaluation/test_queries.csv` (15건, 7가지 타입)
- 단위 테스트: `python -m pytest tests/ -v` (50건 전체 pass)

## 트라이앤에러 회고

### 시도했지만 변경한 접근
- **정적 JSON 기반 식당 데이터**: 초기에는 `restaurants.json`, `reviews.json`으로 식당 정보를 관리했으나, 데이터가 고정되어 실제 서비스와 괴리가 큼 → 크롤링으로 json 적재하려고 했으나 잘 되지 않음 → 카카오맵 API 실시간 검색으로 전환
- **카카오맵 내부 API로 리뷰 조회**: place 페이지의 내부 JSON 엔드포인트를 호출하려 했으나 SPA 렌더링 방식으로 리뷰 데이터가 HTTP 응답에 포함되지 않음 → 카카오 블로그 검색 API로 대체
- **Playwright 기반 캐치테이블 자동 예약**: 실제 예약까지 자동화하려 했으나 ToS 위반 소지, 로그인 필요, DOM 변경에 취약 → 캐치테이블 지도 검색 링크 안내로 전환

### 최종 채택한 접근
- **카카오맵 API + LLM 하이브리드**: 식당 기본 정보는 카카오맵 API(실제 데이터), 메뉴·알레르기는 LLM 추정(AI 추정 안내 포함)으로 역할 분리
- **place_cache 패턴**: 검색 결과를 메모리 캐시에 저장하여 하위 도구(메뉴·리뷰·예약)가 API 재호출 없이 식당 정보에 접근
- **MCP 분리**: 외부 API 의존이 없는 유틸리티 도구를 MCP 서버로 분리하여 표준 프로토콜 기반 도구 제공 패턴 적용

### 남은 한계 · 향후 개선 방향
- 예약은 시뮬레이션이며 실제 예약 시스템과 연동되지 않음 (캐치테이블 링크로 안내)
- 메뉴·가격 정보는 LLM 추정이므로 실제와 다를 수 있음
- 리뷰는 블로그 검색 기반이라 카카오맵 방문자 리뷰와 상이할 수 있음
- 서울 외 지역 지원 미비 (LOCATION_COORDS가 서울 20개 지역에 한정)

## 핵심 코드 위치
- `src/agent.py` — 메인 에이전트 그래프 (LangGraph + MCP 도구 로드 + HITL 승인 게이트)
- `src/tools.py` — 도메인 도구 6개 (카카오맵 API 기반 검색·메뉴·리뷰·예약)
- `src/mcp_server.py` — MCP 유틸리티 서버 (예산 계산, 현재 시간)
- `src/retriever.py` — RAG 파이프라인 (정책 문서 키워드 검색)
- `src/guardrails.py` — 입력 가드 · PII 마스킹 · 도구 위험도 분류
- `app.py` — FastAPI 서버 (SSE 스트리밍 + HITL 승인 엔드포인트)
