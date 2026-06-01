from pydantic import BaseModel
from typing import Dict, Any, List

# [요청] 웹페이지(팀원)가 서버로 보낼 데이터 구조
class MergeRequest(BaseModel):
    ground_truth: Dict[str, Any]  # 정답 데이터 (예: 해시태그, 작성일)
    inferred_data: Dict[str, Any] # 불확실한 추론 데이터 (예: 이미지에서 뽑은 텍스트)

# [응답] 서버가 웹페이지로 돌려줄 데이터 구조
class MergeResponse(BaseModel):
    verified_data: Dict[str, Any] # 검증 통과하여 편입할 데이터
    rejected_data: List[str]      # 기각된 데이터 목록
    reasoning: str                # AI의 판단 논리
    updated_ground_truth: Dict[str, Any] # 최종 병합된 완성본 데이터