import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# 발급받은 Gemini API 키를 여기에 입력하세요.
# (실제 서비스 배포 시에는 보안을 위해 .env 파일로 숨기는 것이 좋습니다.)
GEMINI_API_KEY = ""

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