from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# 1. models.py에서 정의한 데이터 규격 가져오기
from models import (
    MergeRequest, 
    MergeResponse, 
    ExtractBatchRequest, 
    ExtractBatchResponse
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
async def api_extract_batch(request: ExtractBatchRequest):
    try:
        items_dict = [item.model_dump() for item in request.items]
        
        # 1단계: 날것의 문장들에서 표(Columnar) 형태로 데이터 일괄 추출
        extracted_dict = run_batch_text_extraction(items_dict)
        
        # 2단계: 추출된 데이터를 다시 Gemini에 넣어서 인물 프로필로 재요약 (💥 추가된 부분)
        profile_summary = run_profile_summarization(extracted_dict)
        
        # 웹페이지로 두 가지 결과를 모두 돌려줍니다. 
        # 화면에 표 형태도 보여주고, 최종 요약본도 보여줄 수 있어서 시각적으로 매우 훌륭해집니다.
        return {
            "raw_table_data": extracted_dict,     # 1차 결과 (표 형태)
            "final_profile": profile_summary      # 2차 결과 (인물 중심 프로필)
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