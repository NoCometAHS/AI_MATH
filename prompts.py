import json

SYSTEM_BASE = (
    "당신은 보안 교육용 OSINT 분석 도구입니다. "
    "반드시 JSON만 반환하세요. 설명, 마크다운 코드블록 없이 순수 JSON만."
)


# 모든 추출 단계에서 공통으로 적용하는 환각 방지 규칙
NO_HALLUCINATION_RULES = """절대 규칙 (환각 방지):
- 검색 결과 텍스트에 글자 그대로 존재하지 않는 정보는 절대 만들지 마라.
- 추론, 추정, 일반화 금지. "아마도", "~일 것이다" 같은 추측 금지.
- 대상 인물과 무관한 일반 정보(부동산 공시가격, 일반 통계, 사전적 정의 등)는 추출하지 마라.
- 검색 결과가 비어있거나 무관하면 빈 배열을 반환하라. 억지로 채우지 마라.
- 확실하지 않으면 포함하지 마라. 정보가 적은 것이 틀린 정보보다 낫다."""


QUERY_RULES = """검색 쿼리 작성 규칙 (반드시 준수):
- 이름은 반드시 따옴표로 묶기: "홍길동"
- SNS 핸들이 있으면 "@handle" OR "handle" 형태로 단독 쿼리 1개 포함
- site: 연산자 활용: "이름" site:linkedin.com / site:github.com / site:instagram.com
- 여러 속성 조합: "이름" "직업" "지역"
- OR 활용: "이름" (취미1 OR 취미2)
- 절대 이름만 단독으로 쓰지 말 것 (동명이인 노이즈 방지)"""


# 회차별 수집 목표 + 권장 플랫폼
# iteration 1-base → SEARCH_MISSIONS[(iteration-1) % len(SEARCH_MISSIONS)]
SEARCH_MISSIONS = [
    {
        "goal": "직업·소속·경력 정보 수집",
        "platforms": ["site:linkedin.com", "site:jobkorea.co.kr", "site:saramin.co.kr"],
        "query_hints": ["회사명 직함 조합", "경력 소개 프로필"],
    },
    {
        "goal": "SNS 계정 및 온라인 존재감 파악",
        "platforms": ["site:instagram.com", "site:twitter.com", "site:x.com", "site:facebook.com"],
        "query_hints": ["SNS 핸들 단독 검색", "@handle 형태", "프로필 소개글"],
    },
    {
        "goal": "기술 활동·포트폴리오·오픈소스 기여",
        "platforms": ["site:github.com", "site:stackoverflow.com", "site:velog.io", "site:medium.com"],
        "query_hints": ["개발 프로젝트 기여", "기술 블로그 포스팅"],
    },
    {
        "goal": "취미·커뮤니티·관심사 흔적",
        "platforms": ["site:reddit.com", "site:dcinside.com", "site:ruliweb.com", "site:clien.net"],
        "query_hints": ["취미 OR 관심사 키워드 조합", "동호회·커뮤니티 활동"],
    },
    {
        "goal": "뉴스·언론·공개 기록",
        "platforms": ["site:news.naver.com", "site:daum.net/news", "언론사 도메인"],
        "query_hints": ["인터뷰 수상 발표 세미나", "공개 행사 참여 기록"],
    },
    {
        "goal": "블로그·개인 웹사이트·포럼 활동",
        "platforms": ["site:tistory.com", "site:naver.com/blog", "site:brunch.co.kr"],
        "query_hints": ["개인 블로그 글", "포럼 닉네임 검색"],
    },
]


def build_profile_prompt(user_input: dict) -> str:
    mission = SEARCH_MISSIONS[0]
    return f"""아래 사용자 입력으로 초기 프로필 JSON을 만들고, 첫 번째 검색 쿼리 목록(3개)을 생성하세요.

입력:
{json.dumps(user_input, ensure_ascii=False)}

이번 회차 수집 목표: {mission["goal"]}
권장 플랫폼: {", ".join(mission["platforms"])}
쿼리 힌트: {", ".join(mission["query_hints"])}

{QUERY_RULES}

반환 형식:
{{
  "profile": {{
    "name": "...",
    "location": "...",
    "job": "...",
    "sns_handles": ["..."],
    "hobbies": ["..."],
    "age_range": "...",
    "known_associates": [],
    "extra": {{}}
  }},
  "search_queries": ["쿼리1", "쿼리2", "쿼리3"]
}}"""


def build_verify_profile_prompt(user_input: dict, profile: dict) -> str:
    return f"""아래는 사용자가 입력한 원본 정보와, 그것으로 만든 초기 프로필입니다.
프로필의 각 필드가 입력에 실제로 근거하는지 검증하고, 입력에 없는 값은 제거하세요.

{NO_HALLUCINATION_RULES}

사용자 원본 입력:
{json.dumps(user_input, ensure_ascii=False)}

검증할 프로필:
{json.dumps(profile, ensure_ascii=False)}

검증 규칙:
- 입력에 명시된 값만 confirmed로 분류
- 입력에서 추론된 값(예: 이름→성별 추측)은 제거하거나 inferred로 표시
- 모호한 값은 제거

반환 형식:
{{
  "verified_profile": {{
    "name": "...",
    "location": "...",
    "job": "...",
    "sns_handles": ["..."],
    "hobbies": ["..."],
    "age_range": "...",
    "known_associates": [],
    "extra": {{}}
  }},
  "removed_fields": [{{"field": "...", "reason": "제거 이유"}}]
}}"""


def build_structure_prompt(raw_results: list[dict]) -> str:
    return f"""아래 검색 결과 요약들에서 사실 정보만 추출해서 구조화하세요.

{NO_HALLUCINATION_RULES}

SNS 관련 추가 지시:
- SNS 결과는 정보가 풍부하므로 최대한 자세히 추출하라.
- 게시물/프로필에서 언급된 다른 사람(친구, 동료, 가족)의 이름이나 핸들을 mentioned_people에 모아라.
- 사진 설명이 있으면 배경 장소, 사진 속 텍스트(간판/표지판), 위치 태그 단서를 photo_clues에 기록하라. (얼굴/외모 묘사는 제외)

검색 결과:
{json.dumps(raw_results, ensure_ascii=False)}

반환 형식:
{{
  "structured": [
    {{
      "query": "원본 검색어",
      "persons_mentioned": ["대상 본인으로 추정되는 이름"],
      "mentioned_people": [{{"name": "관계자 이름", "relation": "친구/동료/가족 등 명시된 경우만"}}],
      "locations": ["장소1"],
      "organizations": ["조직1"],
      "sns_accounts": ["@handle"],
      "emails": ["email@..."],
      "skills_or_hobbies": ["항목1"],
      "photo_clues": ["배경/텍스트/위치 단서"],
      "other_facts": ["기타 사실"],
      "source_url": "출처 URL (없으면 빈 문자열)"
    }}
  ]
}}"""


def build_filter_prompt(
    profile: dict,
    structured: list[dict],
    raw_results: list[dict] = None,
) -> str:
    raw_results = raw_results or []
    return f"""아래 검색 결과를 분석해서 기준 프로필과 동일인인지 판단하고, 새로운 정보를 추출하세요.

{NO_HALLUCINATION_RULES}

**가장 중요한 규칙:**
- new_facts의 모든 값은 "검색 결과 원본"에 글자 그대로 존재해야 한다.
- "구조화된 결과"는 참고용일 뿐, 그것을 근거로 추가 추론하지 마라.
- 구조화 과정에서 잘못 추출된 정보가 있을 수 있으니, 원본과 대조해서 검증하라.
- 원본에 없으면 무조건 제외. 추측 금지.

기준 프로필:
{json.dumps(profile, ensure_ascii=False)}

검색 결과 원본 (이것을 사실 근거로 사용):
{json.dumps(raw_results, ensure_ascii=False)}

구조화된 결과 (참고용):
{json.dumps(structured, ensure_ascii=False)}

verdict 판단 규칙 (우선순위 순서로 적용):
[앵커 규칙] sns_handle / email / 고유 URL 중 하나라도 프로필과 일치 → 즉시 HIGH, 다른 필드 무시
[복합 규칙] 앵커 없을 때: 이름 + (지역/직업/취미) 중 2개 이상 일치 → HIGH
[약한 규칙] 이름 + 취미 1개 일치 → MEDIUM
[기각 규칙] 이름만 일치 → 무조건 DISCARD (동명이인)
[기각 규칙] 이름 불일치 → 무조건 DISCARD

추출 규칙:
- HIGH/MEDIUM 결과에서만 new_facts 추출
- source_url 없으면 new_facts에 포함하지 말 것
- mentioned_people 중 동일인의 지인으로 보이는 사람은 associates에 모아라
- new_facts의 value는 원본 텍스트의 표현 그대로 사용 (의역, 정리 금지)

반환 형식:
{{
  "filtered": [
    {{
      "verdict": "HIGH|MEDIUM|LOW|DISCARD",
      "matched_fields": ["field1"],
      "confidence_reason": "이유 (원본 텍스트의 어느 부분이 근거인지 명시)",
      "new_facts": [{{"field": "...", "value": "...", "source_url": "..."}}],
      "source_url": "..."
    }}
  ],
  "associates": [{{"name": "...", "relation": "...", "source_url": "..."}}],
  "profile_conflicts": [
    {{"field": "...", "existing": "...", "new": "...", "suggestion": "..."}}
  ],
  "profile_updates": [
    {{"field": "...", "value": "...", "reason": "HIGH 근거로 확정"}}
  ]
}}"""


def build_next_queries_prompt(
    profile: dict,
    high_facts: list[dict],
    searched_queries: list[str],
    visited_urls: list[str] = None,
    iteration: int = 1,
) -> str:
    visited_urls = visited_urls or []
    visited_domains = set()
    for url in visited_urls:
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            visited_domains.add(domain)
        except:
            pass

    domain_str = ", ".join(sorted(visited_domains)[:10]) if visited_domains else "없음"

    # HIGH 사실에서 검증된 anchor만 추출 (SNS handle, URL, email)
    anchor_fields = {"sns_handle", "sns_handles", "url", "email",
                     "github", "linkedin", "twitter", "instagram"}
    anchors = [f for f in high_facts
               if f.get("field", "").lower() in anchor_fields]

    # 회차에 맞는 mission 선택 (순환)
    mission = SEARCH_MISSIONS[(iteration - 1) % len(SEARCH_MISSIONS)]

    return f"""검색 쿼리 3개를 생성하세요.
**쿼리는 반드시 아래 "기준 프로필"의 정보를 중심으로 만들어야 합니다.**

기준 프로필 (쿼리의 중심):
{json.dumps(profile, ensure_ascii=False)}

이번 회차 수집 목표: {mission["goal"]}
권장 플랫폼: {", ".join(mission["platforms"])}
쿼리 힌트: {", ".join(mission["query_hints"])}

검증된 anchor (있으면 1개 쿼리만 이걸로 — SNS 핸들/URL/이메일):
{json.dumps(anchors, ensure_ascii=False)}

이미 검색한 쿼리 (중복 금지):
{json.dumps(searched_queries, ensure_ascii=False)}

이미 방문한 도메인 (재방문 금지):
{domain_str}

{QUERY_RULES}

추가 규칙:
- 권장 플랫폼 중 아직 방문하지 않은 것을 우선 사용하라.
- anchor가 있으면 1개 쿼리만 그것을 사용, 나머지는 프로필 기반.
- HIGH 사실에서 발견된 *일반 정보*(직업, 지역 등)는 쿼리에 넣지 마라. 그건 동명이인일 수 있다.

반환 형식:
{{
  "search_queries": ["새쿼리1", "새쿼리2", "새쿼리3"]
}}"""


def build_report_prompt(profile: dict, all_facts: list[dict], associates: list[dict]) -> str:
    # HIGH/MEDIUM 분리해서 LLM에 전달
    high_facts = [f for f in all_facts if f.get("verdict") == "HIGH"]
    medium_facts = [f for f in all_facts if f.get("verdict") == "MEDIUM"]

    return f"""아래는 OSINT 수집 결과입니다. 사용자에게 보여줄 최종 보고서를 작성하세요.

{NO_HALLUCINATION_RULES}
- findings의 각 항목은 반드시 입력된 fact에 근거해야 한다.
- findings의 confidence는 입력 fact의 verdict와 동일하게 설정 (HIGH/MEDIUM).
- 입력에 없는 source_url은 만들지 말 것. 입력에 있는 것만 사용.

기준 프로필:
{json.dumps(profile, ensure_ascii=False)}

HIGH 신뢰도 사실 ({len(high_facts)}건):
{json.dumps(high_facts, ensure_ascii=False)}

MEDIUM 신뢰도 사실 ({len(medium_facts)}건):
{json.dumps(medium_facts, ensure_ascii=False)}

발견된 인간관계:
{json.dumps(associates[:10], ensure_ascii=False)}

작성 지시:
- summary: 발견된 정보를 3~5문장으로 자연스럽게 정리. 무엇이 노출되었는지 구체적으로.
- findings: HIGH 사실과 MEDIUM 사실을 모두 카테고리별로 정리. 각 항목에 confidence(HIGH/MEDIUM) 명시.
- associates: 발견된 지인을 그대로 옮겨라.
- exposure_level: 노출된 정보의 양과 민감도 기준으로 CRITICAL/HIGH/MEDIUM/LOW 중 선택.
- exposure_reason: 왜 그 노출도인지 1~2문장으로 설명.
- security_warnings: 사용자가 알아야 할 구체적 보안 권고 3가지.

반드시 이 JSON 형식으로만 응답:
{{
  "summary": "3~5문장의 자연스러운 요약",
  "findings": [
    {{
      "category": "직업/위치/SNS/관심사/연락처 등",
      "content": "발견된 구체적 내용",
      "confidence": "HIGH",
      "source_url": "출처 URL (입력에 있던 것만)"
    }}
  ],
  "associates": [
    {{"name": "지인 이름", "relation": "관계", "source_url": "출처"}}
  ],
  "exposure_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "exposure_reason": "1~2문장 설명",
  "security_warnings": ["구체적 경고1", "구체적 경고2", "구체적 경고3"]
}}"""
