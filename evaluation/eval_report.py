"""평가 리포트 — test_queries.csv를 읽고 /query 엔드포인트로 채점한다."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000"


def load_queries() -> list[dict]:
    """test_queries.csv를 읽어 리스트로 반환한다."""
    path = Path(__file__).parent / "test_queries.csv"
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def evaluate_one(row: dict) -> dict:
    """하나의 질의를 실행하고 판정한다."""
    qtype = row["type"]
    question = row["question"]
    keywords = row["expected_keywords"].split("|")

    # 가드레일 차단 테스트는 직접 check_input으로 판정
    if qtype == "guardrail_block":
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from src.guardrails import check_input
        result = check_input(question)
        passed = not result["allowed"]
        return {
            "type": qtype,
            "question": question,
            "passed": passed,
            "answer": result.get("reason", ""),
            "detail": "차단됨" if passed else "차단 실패 — 통과해버림",
        }

    if qtype == "guardrail_pass":
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from src.guardrails import check_input
        result = check_input(question)
        passed = result["allowed"]
        return {
            "type": qtype,
            "question": question,
            "passed": passed,
            "answer": "",
            "detail": "정상 통과" if passed else f"오탐 차단: {result['reason']}",
        }

    # 나머지는 /query 엔드포인트 호출
    try:
        res = requests.post(f"{BASE_URL}/query", json={"question": question}, timeout=60)
        data = res.json()
    except Exception as e:
        return {
            "type": qtype,
            "question": question,
            "passed": False,
            "answer": "",
            "detail": f"요청 실패: {e}",
        }

    answer = data.get("answer", "")
    matched = [kw for kw in keywords if kw.lower() in answer.lower()]
    passed = len(matched) > 0

    return {
        "type": qtype,
        "question": question,
        "passed": passed,
        "answer": answer[:200],
        "detail": f"매칭: {matched}" if passed else f"미매칭: {keywords}",
        "contexts": data.get("contexts", []),
        "trace": data.get("trace", []),
    }


def run_evaluation():
    """전체 평가를 실행하고 리포트를 출력한다."""
    queries = load_queries()
    results = []
    type_counts: dict[str, dict] = {}

    print("=" * 60)
    print("  AI 맛집 컨시어지 — 평가 리포트")
    print("=" * 60)

    for i, row in enumerate(queries, 1):
        qtype = row["type"]
        print(f"\n[{i}/{len(queries)}] ({qtype}) {row['question'][:40]}...")

        result = evaluate_one(row)
        results.append(result)

        status = "PASS" if result["passed"] else "FAIL"
        print(f"  → {status}: {result['detail']}")

        if qtype not in type_counts:
            type_counts[qtype] = {"total": 0, "passed": 0}
        type_counts[qtype]["total"] += 1
        if result["passed"]:
            type_counts[qtype]["passed"] += 1

    # 요약
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    rate = passed / total * 100 if total > 0 else 0

    print("\n" + "=" * 60)
    print(f"  총 통과율: {passed}/{total} ({rate:.0f}%)")
    print("=" * 60)
    print(f"\n{'타입':<20} {'통과':>5} {'전체':>5} {'비율':>8}")
    print("-" * 40)
    for qtype, counts in type_counts.items():
        r = counts["passed"] / counts["total"] * 100
        print(f"{qtype:<20} {counts['passed']:>5} {counts['total']:>5} {r:>7.0f}%")

    # JSON 리포트 저장
    report_path = Path(__file__).parent / "eval_result.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "total": total,
            "passed": passed,
            "rate": rate,
            "by_type": type_counts,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n리포트 저장: {report_path}")


if __name__ == "__main__":
    run_evaluation()
