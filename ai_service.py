import os
import json
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# .env 파일의 내용을 환경변수로 불러옵니다.
load_dotenv()

# --- [NEW] 모델 초기화 및 API 키 검증을 위한 내부 함수 ---
def _get_llm() -> ChatGoogleGenerativeAI:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인해주세요.")
    
    # 공통으로 사용할 Gemini 모델 객체를 생성하여 반환합니다.
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash", 
        temperature=0, 
        google_api_key=api_key
    )
# --- [NEW] JSON 배열 기반 텍스트 추출 함수 ---
def run_batch_text_extraction(items: list) -> list:
    llm = _get_llm()
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """당신은 뛰어난 텍스트 데이터 추출기입니다.
        사용자가 제공하는 [원본 데이터 JSON 배열]을 분석하여, 각 항목에 대해 핵심 정보를 추출하고 동일한 순서의 JSON 배열(List)로 반환하십시오.
        
        각 항목에서 추출할 키(Key):
        - "date": 텍스트의 시점 (기준 날짜 참고하여 MM-DD 변환)
        - "location": 장소, 가게 이름 등
        - "companion": 동행인
        - "action": 행동 요약
        
        규칙:
        1. 텍스트에 해당 정보가 없으면 키를 생략하지 말고 값에 null을 넣으십시오. (데이터 구조 통일)
        2. 원본 배열의 항목 개수와 출력 배열의 항목 개수가 정확히 일치해야 합니다.
        3. 반드시 마크다운 기호(```json) 없이 순수한 JSON 배열(List) 객체만 반환하십시오.
        """),
        ("user", "[원본 데이터 JSON 배열]:\n{batch_data}")
    ])
    
    chain = prompt | llm
    
    # 딕셔너리 리스트를 JSON 문자열로 변환하여 프롬프트에 삽입
    response = chain.invoke({
        "batch_data": json.dumps(items, ensure_ascii=False)
    })
    
    # JSON 파싱 정제
    raw_content = response.content.strip()
    if raw_content.startswith("```json"):
        raw_content = raw_content[7:]
    if raw_content.endswith("```"):
        raw_content = raw_content[:-3]
        
    try:
        return json.loads(raw_content.strip())
    except json.JSONDecodeError:
        print("파싱 에러 발생 원문:", raw_content)
        return []

def run_validation_and_merge(ground_truth: dict, inferred_data: dict) -> dict:
    # 1. Gemini 모델 호출 (gemini-1.5-flash 모델이 가성비와 속도면에서 가장 추천됩니다)
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", 
        temperature=0, 
        google_api_key=GEMINI_API_KEY
    )
    
    # 2. 프롬프트 구성 (Gemini 맞춤형 한국어 프롬프트)
    prompt = ChatPromptTemplate.from_messages([
        ("system", """당신은 엄격한 데이터 검증 전문가입니다.
        [정답 데이터]와 [추론 데이터]를 비교하여 검증하십시오.
        
        규칙:
        1. [추론 데이터]의 각 항목이 [정답 데이터]의 맥락과 모순 없이 일치하는지 논리적으로 확인하세요.
        2. 정답 데이터의 맥락상 사실일 확률이 매우 높은 추론 데이터만 "verified_data"에 추가하세요.
        3. 정답 데이터와 모순되거나, 확인할 수 없는(과도한 추측인) 데이터는 "rejected_data"에 키값을 추가하세요.
        
        출력은 반드시 마크다운 기호(```json) 없이 순수한 JSON 객체로만 작성해야 합니다.
        형식:
        {{"verified_data": {{"key": "value"}}, "rejected_data": ["key1"], "reasoning": "설명"}}"""),
        ("user", "[정답 데이터]: {gt}\n\n[추론 데이터]: {inferred}")
    ])
    
    chain = prompt | llm
    
    # 3. 추론 실행
    response = chain.invoke({
        "gt": json.dumps(ground_truth, ensure_ascii=False),
        "inferred": json.dumps(inferred_data, ensure_ascii=False)
    })
    
    # 4. JSON 파싱 (Gemini의 응답 텍스트 정제)
    raw_content = response.content.strip()
    if raw_content.startswith("```json"):
        raw_content = raw_content[7:]
    if raw_content.endswith("```"):
        raw_content = raw_content[:-3]
        
    try:
        return json.loads(raw_content.strip())
    except json.JSONDecodeError:
        return {"verified_data": {}, "rejected_data": ["전체 파싱 실패"], "reasoning": "모델 출력 오류"}