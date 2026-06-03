import os
import json
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# .env 파일의 내용을 환경변수로 불러옵니다.
load_dotenv()

# ai_service.py 파일의 상단 _get_llm 함수를 아래와 같이 똑같이 맞춰주세요.

# ai_service.py 파일의 _get_llm 함수를 아래 코드로 교체합니다.

def _get_llm() -> ChatGoogleGenerativeAI:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
    
    # 💥 모델명을 공식 표준 명칭인 "gemini-1.5-flash"로 설정합니다.
    # 뒤에 붙은 -latest가 오히려 API 버전 매핑을 방해하는 원인이었습니다.
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", 
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
    # 💥 기존의 ChatGoogleGenerativeAI(...) 부분을 걷어내고, 
    # 아래 한 줄로 변경하여 상단의 팩토리 함수를 호출합니다.
    llm = _get_llm()
    
    # 2. 프롬프트 구성 (Gemini 맞춤형 한국어 프롬프트)
    prompt = ChatPromptTemplate.from_messages([
        ("system", """당신은 엄격한 데이터 검증 전문가입니다.
        [정답 데이터]와 [추론 데이터]를 비교하여 검증하십시오.
        
        규칙:
        1. [추론 데이터]의 각 항목이 [정답 데이터]의 맥락과 모순 없이 일치하는지 논리적으로 확인하세요.
        2. 정답 데이터의 맥락상 사실일 확률이 매우 높은 추론 데이터만 "verified_data"에 추가하세요.
        3. 정답 데이터와 모순되는 데이터는 "rejected_data"에 키값을 추가하세요.
        4. 정답 데이터에서 확인할 수 없는 새로운 데이터는 "verified_data"에 추가하세요.
        
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
    
# --- [NEW] 추출된 Columnar 데이터를 인물 프로필로 2차 요약하는 함수 ---
def run_profile_summarization(extracted_data: dict) -> dict:
    llm = _get_llm()
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """당신은 수집된 행동 로그 데이터를 기반으로 특정 개인의 핵심 신상 프로필을 작성하는 프로파일링 전문가입니다.
        제공되는 [추출된 데이터 세트]는 한 인물의 여러 게시물에서 뽑아낸 정보들입니다.
        
        이 데이터들을 종합적으로 분석하여 이 인물의 고정적인 신상 정보, 가족 관계, 자주 방문하는 곳, 관심사 등을 인물 중심으로 유연하게 요약하여 하나의 JSON 객체로 만드십시오.
        
        규칙:
        1. [유연한 라벨링]: 미리 정해진 키는 없습니다. 데이터에서 유추할 수 있는 핵심 신상 키를 생성하십시오. 
           (예: school, family, often_visit, hobby, fitness_status 등)
        2. 값(Value)은 배열이 아니라 하나의 대표적인 문자열이나 구체적인 데이터여야 합니다. 
        3. 확실하지 않거나 유추할 수 없는 항목은 제외하십시오.
        4. 반드시 마크다운 기호(```json) 없이 순수한 JSON 객체만 반환하십시오.
        
        출력 예시:
        {{
          "school": "상도고등학교",
          "family": "언니",
          "often_visit": "스터디카페, 보라매공원",
          "hobby": "농구",
          "recent_status": "발목 부상 및 중간고사 준비 중"
        }}"""),
        ("user", "[추출된 데이터 세트]:\n{data}")
    ])
    
    chain = prompt | llm
    
    response = chain.invoke({
        "data": json.dumps(extracted_data, ensure_ascii=False)
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
        print("프로필 요약 파싱 에러:", raw_content)
        return {}
