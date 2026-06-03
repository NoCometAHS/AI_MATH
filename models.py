from pydantic import BaseModel
from typing import Dict, Any, List

# --- [NEW] 정보 추출용 모델 (Batch 방식) ---
class RawTextItem(BaseModel):
    raw_text: str
    crawled_date: str = ""

# 웹페이지에서 서버로 던질 전체 JSON 파일(배열) 구조
class ExtractBatchRequest(BaseModel):
    items: List[RawTextItem]

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

# --- [NEW] 웹앱 통합 프로파일링용 모델 ---
class ProfileRequest(BaseModel):
    target_id: str
    ground_truth: Dict[str, Any] = {} # 초기 정답 데이터 (예: 지역, 나이 등)

class ProfileResponse(BaseModel):
    target_id: str
    analyzed_post_count: int
    final_profile: Dict[str, Any]
    rejected_data_keys: List[str] # 기각된 데이터 목록