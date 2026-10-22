"""공통 설정 · LLM 팩터리 · 유틸리티."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
REGION = "us-east-1"
CHECKPOINT_DB = "concierge.sqlite"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")


def _default_llm():
    """기본 LLM을 생성한다."""
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(model=MODEL_ID, region_name=REGION, temperature=0)


def get_text(message) -> str:
    """ChatBedrockConverse 응답에서 텍스트만 추출한다."""
    content = message.content if hasattr(message, "content") else message
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content)
