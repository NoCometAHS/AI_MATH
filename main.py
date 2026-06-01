import asyncio
import json
import os
from typing import AsyncGenerator

import openai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware
from models import MergeRequest, MergeResponse
from ai_service import run_validation_and_merge

from prompts import (
    build_filter_prompt,
    build_next_queries_prompt,
    build_profile_prompt,
    build_report_prompt,
    build_structure_prompt,
    build_verify_profile_prompt,
    SYSTEM_BASE,
)

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

MAX_ITERATIONS = 6
MIN_ITERATIONS = 5


class UserInput(BaseModel):
    name: str
    location: str = ""
    sns_handles: str = ""
    job: str = ""
    hobbies: str = ""
    age_range: str = ""


# ── OpenAI 호출 헬퍼 ─────────────────────────────────────────────

MODEL = "gpt-4o-mini"


def _client() -> openai.OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    return openai.OpenAI(api_key=api_key)


def call_llm(prompt: str, max_tokens: int = 1000) -> dict:
    """JSON 반환하는 단순 LLM 호출"""
    client = _client()
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_BASE},
            {"role": "user", "content": prompt},
        ],
    )
    text = resp.choices[0].message.content
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # JSON 파싱 실패 시 원본 텍스트 로깅
        raise RuntimeError(f"LLM JSON 파싱 실패: {str(e)}\n원본: {text[:200]}")


def call_llm_with_search(queries: list[str]) -> list[dict]:
    """web_search_preview 툴로 쿼리들을 검색해서 결과 반환"""
    client = _client()
    results = []
    for query in queries:
        resp = client.chat.completions.create(
            model="gpt-4o-mini-search-preview",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": f"다음을 검색하고 찾은 내용을 간결하게 요약해줘: {query}",
            }],
        )
        results.append({
            "query": query,
            "summary": resp.choices[0].message.content or "",
        })
    return results


# ── SSE 이벤트 헬퍼 ──────────────────────────────────────────────

def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── OSINT 파이프라인 (async generator → SSE) ─────────────────────

async def run_pipeline(user_input: dict) -> AsyncGenerator[str, None]:

    def step(msg: str):
        return sse("step", {"message": msg})

    async def run_sync(fn, *args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    try:
        # 1. 초기 프로필 생성
        yield step("🔍 초기 프로필 생성 중...")
        init_result = await run_sync(call_llm, build_profile_prompt(user_input))
        profile: dict = init_result["profile"]
        queries: list[str] = init_result["search_queries"]

        yield sse("log", {
            "type": "llm", "label": "초기 프로필 (검증 전)", "data": profile,
        })

        # 1-2. 프로필 검증 (입력에 근거 없는 값 제거)
        yield step("🧪 초기 프로필 검증 중...")
        verify_result = await run_sync(
            call_llm, build_verify_profile_prompt(user_input, profile)
        )
        profile = verify_result.get("verified_profile", profile)
        removed = verify_result.get("removed_fields", [])

        yield sse("profile", {"profile": profile})
        yield sse("log", {
            "type": "llm", "label": "검증된 프로필", "data": profile,
        })
        if removed:
            yield sse("log", {
                "type": "llm", "label": "검증으로 제거된 필드", "data": removed,
            })
        yield sse("log", {
            "type": "llm", "label": "초기 검색 쿼리", "data": queries,
        })

        searched: list[str] = []
        all_facts: list[dict] = []
        all_associates: list[dict] = []
        visited_urls: list[str] = []  # 방문한 URL 추적
        iteration = 0

        while iteration < MAX_ITERATIONS:
            iteration += 1
            yield step(f"🌐 [{iteration}회차] 검색 중...")

            # 2. 검색 실행
            raw_results = await run_sync(call_llm_with_search, queries)
            searched.extend(queries)
            yield sse("log", {
                "type": "search",
                "label": f"[{iteration}회차] 검색 원본 결과",
                "data": raw_results,
            })

            # 3. 검색 결과 구조화
            yield step(f"🗂️ [{iteration}회차] 검색 결과 구조화 중...")
            structure_result = await run_sync(
                call_llm, build_structure_prompt(raw_results)
            )
            structured = structure_result.get("structured", [])
            
            # 중복 URL 필터링 + 새 URL 기록
            unique_structured = []
            for item in structured:
                url = item.get("source_url", "")
                if url and url not in visited_urls:
                    visited_urls.append(url)
                    unique_structured.append(item)
                elif not url:
                    # URL 없는 항목도 포함
                    unique_structured.append(item)
            structured = unique_structured
            
            yield sse("log", {
                "type": "llm",
                "label": f"[{iteration}회차] 구조화 결과 (중복 제거 후)",
                "data": structured,
            })

            # 4. 필터링 + 정보/지인 추출 (raw_results도 함께 전달해 추론 방지)
            yield step(f"🔎 [{iteration}회차] 동일인 판단 및 필터링 중...")
            filter_result = await run_sync(
                call_llm, build_filter_prompt(profile, structured, raw_results)
            )
            yield sse("log", {
                "type": "llm",
                "label": f"[{iteration}회차] 필터링 판단",
                "data": filter_result.get("filtered", []),
            })

            # 새 사실 수집
            new_facts: list[dict] = []
            for item in filter_result.get("filtered", []):
                if item.get("verdict") in ("HIGH", "MEDIUM"):
                    for fact in item.get("new_facts", []):
                        fact["verdict"] = item["verdict"]
                        new_facts.append(fact)
            all_facts.extend(new_facts)

            # 지인 수집 (중복 이름 제거)
            new_associates = filter_result.get("associates", [])
            known_names = {a.get("name") for a in all_associates}
            for assoc in new_associates:
                if assoc.get("name") and assoc["name"] not in known_names:
                    all_associates.append(assoc)
                    known_names.add(assoc["name"])
            if new_associates:
                yield sse("associates", {"associates": all_associates})
                yield sse("log", {
                    "type": "llm",
                    "label": f"[{iteration}회차] 발견된 지인",
                    "data": new_associates,
                })

            # 모순 처리
            conflicts = filter_result.get("profile_conflicts", [])
            for conflict in conflicts:
                field = conflict.get("field")
                if field:
                    existing = profile.get(field)
                    new_val = conflict.get("new")
                    if existing and new_val and existing != new_val:
                        profile[field] = [existing, new_val]
            if conflicts:
                yield sse("log", {
                    "type": "llm",
                    "label": f"[{iteration}회차] 프로필 모순 감지",
                    "data": conflicts,
                })

            # 프로필 업데이트는 로그만 남기고 실제 적용은 하지 않음
            # (이유: 동명이인 결과가 HIGH로 잘못 판정될 경우 프로필이 오염되어
            #  다음 회차 검색이 완전히 다른 사람을 향하게 되는 문제 방지)
            updates = filter_result.get("profile_updates", [])
            if updates:
                yield sse("log", {
                    "type": "llm",
                    "label": f"[{iteration}회차] 프로필 업데이트 제안 (적용 안 됨)",
                    "data": updates,
                })

            if new_facts:
                yield sse("facts", {"facts": new_facts, "iteration": iteration})
                yield step(f"✅ [{iteration}회차] 새 정보 {len(new_facts)}건 수집")
            else:
                yield step(f"⚪ [{iteration}회차] 새 정보 없음")

            # 5. 종료 조건 — 최소 MIN_ITERATIONS회는 무조건 반복
            if iteration >= MAX_ITERATIONS:
                yield step("⚠️ 최대 반복 횟수 도달 → 분석 종료")
                break
            if iteration >= MIN_ITERATIONS:
                yield step(f"✔️ 최소 {MIN_ITERATIONS}회 반복 완료 → 분석 종료")
                break

            # 6. 다음 검색어 생성 (HIGH 사실만 전달)
            yield step(f"🧠 [{iteration}회차] 다음 검색어 생성 중...")
            high_facts = [f for f in all_facts if f.get("verdict") == "HIGH"]
            next_result = await run_sync(
                call_llm, build_next_queries_prompt(profile, high_facts, searched, visited_urls, iteration)
            )
            queries = next_result.get("search_queries", [])
            yield sse("log", {
                "type": "llm",
                "label": f"[{iteration}회차] 다음 검색 쿼리",
                "data": queries,
            })
            if not queries:
                yield step("더 이상 생성할 검색어 없음 → 종료")
                break

        # 7. 최종 보고서 (긴 응답을 위해 max_tokens 증가)
        yield step("📋 최종 보고서 생성 중...")
        report = await run_sync(
            call_llm, build_report_prompt(profile, all_facts, all_associates), 3000
        )
        yield sse("log", {
            "type": "llm", "label": "최종 보고서 원본", "data": report,
        })
        yield sse("report", {"report": report, "profile": profile})
        yield sse("done", {"message": "분석 완료"})

    except Exception as e:
        yield sse("error", {"message": str(e)})


# ── 엔드포인트 ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


@app.post("/run")
async def run(user_input: UserInput):
    data = {
        "name": user_input.name,
        "location": user_input.location,
        "sns_handles": [h.strip() for h in user_input.sns_handles.split(",") if h.strip()],
        "job": user_input.job,
        "hobbies": [h.strip() for h in user_input.hobbies.split(",") if h.strip()],
        "age_range": user_input.age_range,
    }
    return StreamingResponse(
        run_pipeline(data),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app = FastAPI(title="정답 데이터 병합 API")

# 프론트엔드 연동을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

# 데이터 병합 API 엔드포인트
@app.post("/api/merge_data", response_model=MergeResponse)
async def api_merge_data(request: MergeRequest):
    try:
        # 1. ai_service에 데이터 전달하여 분석 수행
        ai_result = run_validation_and_merge(
            ground_truth=request.ground_truth,
            inferred_data=request.inferred_data
        )
        
        # 2. 최종 정답 데이터셋 합성 (기존 정답 + 새로 검증된 데이터)
        verified = ai_result.get("verified_data", {})
        final_ground_truth = {**request.ground_truth, **verified}
        
        # 3. 프론트엔드에 응답 전송 (models.py의 규격에 맞춤)
        return MergeResponse(
            verified_data=verified,
            rejected_data=ai_result.get("rejected_data", []),
            reasoning=ai_result.get("reasoning", "분석 완료"),
            updated_ground_truth=final_ground_truth
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))