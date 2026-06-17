from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import time  # 💥 무료 티어 안전망을 위한 시간 지연용

# 1. models.py에서 정의한 데이터 규격 가져오기
from models import (
    MergeRequest, 
    MergeResponse
)

# 2. ai_service.py에서 정의한 AI 동작 함수 가져오기
from ai_service import (
    run_validation_and_merge, 
    run_batch_text_extraction,
    run_profile_summarization
)

# FastAPI 앱 초기화
app = FastAPI(title="OSINT 데이터 파이프라인 API", description="정보 추출 및 정답 데이터 교차 검증 서버")

# 웹페이지(프론트엔드)에서 API를 호출할 수 있도록 CORS 허용 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 실제 배포 시에는 프론트엔드 도메인(예: http://localhost:3000)만 허용하는 것이 안전합니다.
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# [API 1] 텍스트 정보 일괄 추출 (Columnar 방식)
# ==========================================
@app.post("/api/extract_batch")
async def api_extract_batch(request: List[Dict[str, Any]]):
    try:
        # 1. 청크 크기(한 번에 LLM에 보낼 데이터 개수) 설정
        # 텍스트 양이 많다면 CHUNK_SIZE를 3~5 정도로 낮추는 것이 안전합니다.
        CHUNK_SIZE = 5 
        combined_extracted_dict = {}
        
        # 2. 데이터를 CHUNK_SIZE만큼 쪼개서 루프 실행
        for i in range(0, len(request), CHUNK_SIZE):
            chunk = request[i : i + CHUNK_SIZE]
            
            # 해당 청크만 LLM으로 추출 실행
            chunk_result = run_batch_text_extraction(chunk)
            
            # 추출된 Columnar 결과를 기존 결과에 누적 병합
            if chunk_result:
                for key, values in chunk_result.items():
                    if key not in combined_extracted_dict:
                        # 처음 발견된 키라면, 이전 청크들의 데이터 개수만큼 null을 채워줌
                        previous_total = i
                        combined_extracted_dict[key] = [None] * previous_total
                    
                    # 현재 청크의 결과값 추가
                    combined_extracted_dict[key].extend(values)
            
            # 3. 다른 키들의 배열 길이도 맞춰주기 (결측치 동기화)
            current_total = i + len(chunk)
            for key in combined_extracted_dict.keys():
                if len(combined_extracted_dict[key]) < current_total:
                    needed_nulls = current_total - len(combined_extracted_dict[key])
                    combined_extracted_dict[key].extend([None] * needed_nulls)
            
            # 💥 중요: 무료 등급 우회를 위해 청크 사이에 의도적인 휴식(1~2초) 부여
            if i + CHUNK_SIZE < len(request):
                time.sleep(1.5)

        # 4. 전체가 통합된 Columnar 데이터를 기반으로 최종 2차 인물 요약 실행
        if not combined_extracted_dict:
            raise ValueError("추출된 데이터가 존재하지 않습니다.")
            
        profile_summary = run_profile_summarization(combined_extracted_dict)
        
        return {
            "raw_table_data": combined_extracted_dict,
            "final_profile": profile_summary
        }
        
    except Exception as e:
        print(f"추출/요약 파이프라인 에러: {str(e)}")
        raise HTTPException(status_code=500, detail="데이터 추출 및 프로필 요약 중 오류가 발생했습니다.")


# ==========================================
# [API 2] 정답 데이터와 추론 데이터 교차 검증 및 병합
# ==========================================
@app.post("/api/merge_data", response_model=MergeResponse)
async def api_merge_data(request: MergeRequest):
    try:
        # Gemini AI를 호출하여 데이터 논리 검증 수행
        ai_result = run_validation_and_merge(
            ground_truth=request.ground_truth,
            inferred_data=request.inferred_data
        )
        
        # 승인된(Verified) 데이터만 추출
        verified = ai_result.get("verified_data", {})
        
        # 기존 정답 데이터(Ground Truth)에 승인된 데이터를 덮어쓰기(병합)
        # 딕셔너리 언패킹(**)을 사용하여 간단하게 합칩니다.
        final_ground_truth = {**request.ground_truth, **verified}
        
        # 검증 결과 및 최종 병합본을 응답 규격에 맞춰 웹으로 반환
        return MergeResponse(
            verified_data=verified,
            rejected_data=ai_result.get("rejected_data", []),
            reasoning=ai_result.get("reasoning", "분석 완료"),
            updated_ground_truth=final_ground_truth
        )
        
    except Exception as e:
        print(f"병합 API 에러: {str(e)}")
        raise HTTPException(status_code=500, detail="데이터 교차 검증 및 병합 중 오류가 발생했습니다.")

# ==========================================
# [헬스 체크] 서버가 정상적으로 켜져 있는지 확인하는 용도
# ==========================================
@app.get("/")
async def root():
    return {"status": "ok", "message": "서버가 정상적으로 실행 중입니다."}