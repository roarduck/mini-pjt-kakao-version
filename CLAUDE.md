# 프로젝트 규칙

## 기술 스택

| 구분 | 기술 |
|------|------|
| LLM | Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) via Amazon Bedrock |
| 프레임워크 | LangChain · LangGraph |
| 모델 호출 | `ChatBedrockConverse` (langchain-aws) |
| 체크포인터 | SQLite (`AsyncSqliteSaver`) |
| API 서버 | FastAPI (SSE 스트리밍) |
| 외부 API | 카카오맵 Local REST API (식당 검색) · 카카오 블로그 검색 API (리뷰) |
| HTTP 클라이언트 | httpx (카카오 API 호출) |
| MCP | mcp (FastMCP) · langchain-mcp-adapters (유틸리티 도구 서빙) |
| 가드레일 | 정규식 입력 가드 · PII 마스킹 · HITL 승인 게이트 |

## 폴더 구조 (제출 규약. 바꾸지 않는다)

```
mini-pjt-kakao-version/
├── CLAUDE.md                        # 프로젝트 규칙 (이 파일)
├── SERVICE.md                       # 서비스 기획서
├── .env.example                     # 환경변수 템플릿
├── app.py                           # FastAPI 서버 (POST /query + 채팅 SSE)
├── run.py                           # uvicorn 진입점
│
├── src/                             # 핵심 소스 코드
│   ├── config.py                    #   공통 설정 · LLM 팩터리 · 카카오 API 키
│   ├── tools.py                     #   도메인 도구 (6개 @tool, 카카오맵 API 기반)
│   ├── mcp_server.py                #   MCP 서버 (유틸리티 도구 2개: calculate_budget, get_current_time)
│   ├── retriever.py                 #   RAG 파이프라인 (정책 문서 검색)
│   ├── guardrails.py                #   입력 가드 · PII 마스킹 · 위험도 분류
│   └── agent.py                     #   메인 에이전트 그래프 (LangGraph + HITL)
│
├── static/                          # 프론트엔드
│   └── index.html                   #   채팅 웹 UI (URL 자동 링크 + 캐치테이블 버튼)
│
├── data/                            # RAG용 정책 문서
│   └── docs/
│       ├── reservation_policy.md    #     예약/취소 정책
│       ├── dining_etiquette.md      #     식사 예절 가이드
│       └── allergy_guide.md         #     알레르기 음식 안내
│
├── evaluation/                      # 평가
│   ├── test_queries.csv             #   평가 질의 세트 (15건, 7가지 타입)
│   └── eval_report.py               #   평가 리포트 생성
│
└── tests/                           # 단위 테스트 (pytest)
    ├── test_tools.py                #   도구 테스트 (카카오 API 모킹)
    ├── test_guardrails.py           #   가드레일 테스트
    ├── test_retriever.py            #   RAG 검색 테스트
    └── test_agent.py                #   에이전트 통합 테스트
```

## 주고받는 형식 (제출 규약)

- `POST /query` 로 받고 `question` 필드를 읽는다
- 답은 `answer`, `contexts`, `trace` 세 키로 돌려준다

```json
{
  "answer": "강남역 근처 이탈리안 레스토랑을 추천합니다...",
  "contexts": ["kakao_place:26338954", "http://place.map.kakao.com/26338954"],
  "trace": ["search_restaurant(query='이탈리안', location='강남')"]
}
```

## 코드 규칙

- 파일 하나에 한 가지 역할만 둔다
- 함수와 도구에는 한국어 docstring 을 쓴다
- 비밀 값은 `.env` 에서 읽고 코드에 적지 않는다
- 도구 함수는 예외를 발생시키지 않고 에러 문자열을 반환한다
- 위험 도구(write/destructive)는 HITL 승인 후 실행한다
- 식당 검색은 카카오맵 API로 실시간 조회한다
- 메뉴·알레르기 정보는 LLM 추정으로 제공하며, 결과에 AI 추정 안내를 포함한다
- 메뉴 정보 안내 시 알레르기 정보를 항상 함께 제공한다 (사용자 별도 요청 불필요)
- 예약 도구는 시뮬레이션이며, 캐치테이블 지도 검색 링크로 실제 예약을 안내한다
- 리뷰 링크는 카카오맵 place_url에 `#review` 해시를 붙여 후기 탭으로 직접 이동한다
- 프론트엔드에서 URL은 자동 링크 변환되며, 캐치테이블 URL은 버튼 UI로 표시한다

## 하지 말 것

- 요청하지 않은 파일을 새로 만들지 않는다
- 기존 파일을 통째로 다시 쓰지 않는다. 바뀐 부분만 고친다
