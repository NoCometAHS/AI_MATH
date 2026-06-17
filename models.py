from pydantic import BaseModel
from typing import Dict, Any, List

# --- [수정됨] 단일 딕셔너리 안에 배열들이 들어가는 구조 ---
class ExtractBatchResponse(BaseModel):
    extracted_data: Dict[str, List[Any]]

# --- 기존 데이터 병합용 모델 (유지) ---
class MergeRequest(BaseModel):
    ground_truth: Dict[str, Any]
    inferred_data: Dict[str, Any]

class MergeResponse(BaseModel):
    verified_data: Dict[str, Any]
    rejected_data: List[str]
    reasoning: str
    updated_ground_truth: Dict[str, Any]

# --- [NEW] 최종 프로필 요약 응답 규격 추가 ---
class ProfileSummaryResponse(BaseModel):
    profile_data: Dict[str, Any]={}  # 인물 중심으로 유연하게 요약된 프로필 JSON