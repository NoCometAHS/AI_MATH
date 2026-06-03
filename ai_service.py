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
# --- [수정됨] 자동 라벨링 및 열 기반(Columnar) 추출 함수 ---
def run_batch_text_extraction(items: list) -> dict:
    llm = _get_llm()
    
    # 텍스트가 몇 개인지 명시적으로 알려주면 AI가 배열 길이를 맞추는 데 도움이 됩니다.
    item_count = len(items)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """당신은 뛰어난 데이터 추출 및 구조화 전문가입니다.
        사용자가 제공하는 [원본 데이터 JSON 배열]을 분석하여, 텍스트에서 추출할 수 있는 모든 의미 있는 정보의 '키(Key)'를 스스로 정의(자동 라벨링)하십시오.
        
        출력 형식은 개별 객체의 배열이 아니라, **모든 데이터를 통합한 단일 JSON 객체(Columnar format)**여야 합니다.
        
        규칙:
        1. [자동 라벨링]: 미리 정해진 키는 없습니다. 텍스트들을 종합적으로 분석하여 적절한 분류 기준(키)을 영어 단어로 자유롭게 생성하십시오. (예: date, location, weather, emotion, food_type 등)
        2. [배열 길이 일치]: 모든 키의 값은 '배열(List)'이어야 하며, 이 배열의 길이는 반드시 입력된 원본 텍스트의 개수와 동일해야 합니다.
        3. [인덱스 매칭]: 특정 배열의 n번째 요소는 원본 데이터의 n번째 텍스트에서 추출한 값이어야 합니다.
        4. [결측치 처리]: 특정 텍스트에 해당 키에 대한 정보가 전혀 없다면, 반드시 그 위치(인덱스)에 `null`을 입력하여 배열의 길이를 유지하십시오.
        5. 반드시 마크다운 기호(```json) 없이 순수한 JSON 객체만 반환하십시오.
        
        출력 구조 예시 (입력 데이터가 2개일 경우 모든 배열의 길이는 2):
        {{
          "date": ["2026-05-05", "2026-05-20"],
          "location": ["상도동", "숭실대"],
          "companion": [2, null],
          "action": ["식사", "공부"],
          "new_dynamic_key": ["값1", null]
        }}"""),
        ("user", "[원본 데이터 JSON 배열 (총 {count}개)]:\n{batch_data}")
    ])
    
    chain = prompt | llm
    
    response = chain.invoke({
        "count": item_count,
        "batch_data": json.dumps(items, ensure_ascii=False)
    })
    
    raw_content = response.content.strip()
    if raw_content.startswith("```json"):
        raw_content = raw_content[7:]
    if raw_content.endswith("```"):
        raw_content = raw_content[:-3]
        
    try:
        return json.loads(raw_content.strip())
    except json.JSONDecodeError:
        print("파싱 에러 발생 원문:", raw_content)
        return {} # 실패 시 빈 딕셔너리 반환

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