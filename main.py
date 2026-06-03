import os
import sys
import json
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import ProfileRequest, ProfileResponse
from ai_service import (
    run_batch_text_extraction,
    run_validation_and_merge,
    run_profile_summarization
)

app = FastAPI(title="OSINT 통합 프로파일링 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_texts_from_social_data(data, min_length=5):
    """JSON 구조를 순회하며 텍스트 데이터만 추출하는 헬퍼 함수"""
    texts = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in ['url', 'id', 'timestamp', 'video_url', 'profile_pic']:
                continue
            texts.extend(extract_texts_from_social_data(v, min_length))
    elif isinstance(data, list):
        for item in data:
            texts.extend(extract_texts_from_social_data(item, min_length))
    elif isinstance(data, str) and len(data) >= min_length:
        texts.append(data)
    return texts

@app.post("/api/generate_profile", response_model=ProfileResponse)
async def api_generate_profile(request: ProfileRequest):
    target_id = request.target_id
    
    # 1. 크롤러 실행 (subprocess)
    try:
        print(f"[{target_id}] 크롤링을 위해 새 창을 띄웁니다...")
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

        process = subprocess.run(
            [sys.executable, "run_all.py", target_id],
            cwd=current_dir,
            **kwargs
        )
        
        if process.returncode != 0:
            raise Exception("크롤러 실행 중 내부 오류가 발생했습니다.")
            
        print(f"[{target_id}] 크롤링 완료. AI 분석을 시작합니다.")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 2. 통합 결과 파일(merged.json) 로드
    merged_file_path = "output/merged.json"
    if not os.path.exists(merged_file_path):
        raise HTTPException(status_code=404, detail="수집된 데이터(merged.json)가 생성되지 않았습니다.")

    try:
        with open(merged_file_path, "r", encoding="utf-8") as f:
            social_data = json.load(f)
            
        raw_texts = extract_texts_from_social_data(social_data)
        texts_to_analyze = raw_texts[:50] # API 비용 및 속도를 위해 50개 컷
        
        if not texts_to_analyze:
             raise HTTPException(status_code=400, detail="분석할 텍스트 데이터를 찾지 못했습니다.")

        # 3. LLM 파이프라인 가동 및 결과 처리 부분
        items_dict = [{"raw_text": t} for t in texts_to_analyze]
        extracted_table = run_batch_text_extraction(items_dict)
        
        merge_result = run_validation_and_merge(
            ground_truth=request.ground_truth,
            inferred_data=extracted_table
        )
        
        verified_data = merge_result.get("verified_data", {})
        final_ground_truth = {**request.ground_truth, **verified_data}
        rejected_keys = merge_result.get("rejected_data", []) # ai_service에서 받아온 리스트
        
        final_profile = run_profile_summarization(final_ground_truth)
        
        # 💥 [확인 및 수정] ProfileResponse 규격과 완벽히 일치해야 합니다.
        return ProfileResponse(
            target_id=target_id,
            analyzed_post_count=len(texts_to_analyze),
            final_profile=final_profile,
            rejected_data_keys=rejected_keys  # 👈 이 필드명이 명확해야 합니다.
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 분석 중 오류가 발생했습니다: {str(e)}")