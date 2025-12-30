"""
NLU 모듈: Bedrock Titan 기반 자연어 → 필터 JSON 변환
- JSON-only 출력 강제
- 검증/재시도/fallback
- Clarification 지원
"""
import os
import re
import json
from typing import Dict, Optional, Tuple, List, Union
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import boto3
from pydantic import ValidationError

from .schema import (
    FilterRequest, NLUFiltersOutput, NLUClarifyOutput,
    ClarifyQuestion
)
from .data_loader import (
    get_dim_dict, validate_and_correct_filter,
    get_default_date_range, get_data_date_range
)

# Bedrock 클라이언트
_bedrock_client = None

def get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        region = os.environ.get("AWS_REGION", "ap-southeast-2")
        _bedrock_client = boto3.client("bedrock-runtime", region_name=region)
    return _bedrock_client


MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")


# ============================================================
# 프롬프트 템플릿
# ============================================================

SYSTEM_PROMPT = """You are a filter extraction assistant for agricultural price data.
Your task is to convert Korean natural language questions into a structured JSON filter.

CRITICAL RULES:
1. Output ONLY valid JSON. No markdown, no code blocks, no explanations.
2. NEVER generate SQL or execute any queries.
3. If the question is ambiguous, output a clarify response.

Available item_names (품목): {item_names}
Available variety_names (품종): {variety_names}
Available market_names (시장): {market_names}

Data date range: {date_range}
Reference date for "최근/recent" queries: {today} (use this as "today" for calculating recent periods)

OUTPUT FORMAT (choose ONE):

Option A - Confirmed filters:
{{"type": "filters", "filters": {{...}}, "warnings": []}}

Option B - Need clarification (max 2 questions):
{{"type": "clarify", "draft_filters": {{...}}, "questions": [{{"id": "...", "question": "...", "options": [...], "default": "..."}}], "warnings": []}}

FILTER SCHEMA:
- item_name: string (REQUIRED, must be from available list)
- variety_name: string or null
- market_name: string or null (default: "전국도매시장")
- date_from: "YYYY-MM-DD" or null
- date_to: "YYYY-MM-DD" or null
- chart_type: "trend" | "compare_markets" | "volume_price" | "volatility"
- metrics: ["price"] | ["volume"] | ["price", "volume"]
- granularity: "daily" | "weekly"
- top_n_markets: integer (for compare_markets)
- explain: boolean
- intent: "normal" | "high_avg_price" | "high_price_change" | "high_volatility"
- window_days: integer (default 30)

DATE CONVERSION RULES:
- "최근 N개월" = last N months from today
- "작년" = previous year (full year)
- "2019년" = 2019-01-01 to 2019-12-31
- "상순" = 1st~10th day, "중순" = 11th~20th, "하순" = 21st~end

CLARIFICATION TRIGGERS:
- "요즘/최근/요새" without specific period → ask about window_days
- "비싼/싼/좋은" without metric → ask about intent (high_avg_price, high_price_change, high_volatility)
- Multiple matching items/varieties → ask to confirm"""


USER_PROMPT_TEMPLATE = """Convert this question to JSON filter:
"{question}"

Remember: Output ONLY valid JSON, nothing else."""


RETRY_PROMPT_TEMPLATE = """Your previous output was invalid JSON or failed validation.
Error: {error}

Please try again. Output ONLY valid JSON for this question:
"{question}"
"""


# ============================================================
# 날짜 표현 파싱
# ============================================================

def parse_date_expression(text: str, today: datetime = None) -> Tuple[Optional[str], Optional[str]]:
    """
    자연어 날짜 표현을 (date_from, date_to) 튜플로 변환

    Examples:
        "최근 6개월" → (6개월 전, 데이터 마지막 날짜)
        "작년" → (작년 1월 1일, 작년 12월 31일)
        "2019년" → (2019-01-01, 2019-12-31)
        "최근 한달" → (30일 전, 데이터 마지막 날짜)
    """
    if today is None:
        # 데이터의 마지막 날짜를 기준으로 사용 (실제 오늘 날짜가 아닌)
        _, max_date_str = get_data_date_range()
        if max_date_str:
            today = datetime.strptime(max_date_str, "%Y-%m-%d")
        else:
            today = datetime.now()

    # 최근 N개월
    match = re.search(r"최근\s*(\d+)\s*개월", text)
    if match:
        months = int(match.group(1))
        date_from = today - relativedelta(months=months)
        return (date_from.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))

    # 최근 N일
    match = re.search(r"최근\s*(\d+)\s*일", text)
    if match:
        days = int(match.group(1))
        date_from = today - timedelta(days=days)
        return (date_from.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))

    # 최근 한달/한 달
    if re.search(r"최근\s*(한\s*)?달", text):
        date_from = today - relativedelta(months=1)
        return (date_from.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))

    # 최근 N주
    match = re.search(r"최근\s*(\d+)\s*주", text)
    if match:
        weeks = int(match.group(1))
        date_from = today - timedelta(weeks=weeks)
        return (date_from.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))

    # 작년
    if "작년" in text:
        last_year = today.year - 1
        return (f"{last_year}-01-01", f"{last_year}-12-31")

    # 특정 년도
    match = re.search(r"(\d{4})년", text)
    if match:
        year = match.group(1)
        return (f"{year}-01-01", f"{year}-12-31")

    # 전월/전달 대비
    if "전월" in text or "전달" in text:
        # 비교 분석용이므로 최근 2개월
        date_from = today - relativedelta(months=2)
        return (date_from.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))

    return (None, None)


# ============================================================
# 룰 기반 Fallback
# ============================================================

def rule_based_fallback(question: str) -> Tuple[Dict, List[str]]:
    """
    LLM 실패 시 룰 기반으로 필터 추출
    """
    warnings = ["LLM 파싱 실패로 규칙 기반 추출을 사용했습니다."]
    dim_dict = get_dim_dict()

    # 품목 매칭
    item_name = None
    for item in dim_dict["item_names"]:
        if item in question:
            item_name = item
            break

    if not item_name:
        # fallback to most common items
        common_items = ["감자", "사과", "배추", "양파", "마늘", "대파", "무"]
        for item in common_items:
            if item in question:
                item_name = item
                break

    if not item_name:
        item_name = "감자"  # 기본값
        warnings.append("품목을 찾을 수 없어 '감자'로 설정했습니다.")

    # 품종 매칭
    variety_name = None
    for variety in dim_dict["variety_names"]:
        if variety in question and len(variety) > 1:  # 1글자 품종 제외
            variety_name = variety
            break

    # 시장 매칭
    market_name = "전국도매시장"
    for market in dim_dict["market_names"]:
        if market in question:
            market_name = market
            break

    # 날짜 파싱
    date_from, date_to = parse_date_expression(question)
    if not date_from:
        date_from, date_to = get_default_date_range(90)
        warnings.append("기간을 찾을 수 없어 최근 90일로 설정했습니다.")

    # chart_type 추론
    chart_type = "trend"
    if "비교" in question or "시장별" in question:
        chart_type = "compare_markets"
    elif "변동성" in question or "급등락" in question:
        chart_type = "volatility"
    elif "반입량" in question and "가격" in question:
        chart_type = "volume_price"

    # intent 추론
    intent = "normal"
    if "비싼" in question or "비싸" in question:
        intent = "high_avg_price"
    elif "올랐" in question or "상승" in question:
        intent = "high_price_change"
    elif "변동" in question or "급등" in question or "급락" in question:
        intent = "high_volatility"

    filters = {
        "item_name": item_name,
        "variety_name": variety_name,
        "market_name": market_name,
        "date_from": date_from,
        "date_to": date_to,
        "chart_type": chart_type,
        "metrics": ["price", "volume"],
        "granularity": "weekly",
        "top_n_markets": 5,
        "explain": True,
        "intent": intent,
        "window_days": 30
    }

    return filters, warnings


# ============================================================
# Bedrock Nova 호출
# ============================================================

def call_llm(prompt: str, max_tokens: int = 1024) -> str:
    """Bedrock Nova 모델 호출"""
    client = get_bedrock_client()

    body = {
        "messages": [
            {"role": "user", "content": [{"text": prompt}]}
        ],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": 0.1
        }
    }

    response = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json"
    )

    result = json.loads(response["body"].read())
    output_text = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")
    return output_text.strip()


def extract_json_from_response(text: str) -> Optional[dict]:
    """응답에서 JSON 추출"""
    # 코드 블록 제거
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()

    # JSON 파싱 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # { } 사이의 JSON 찾기
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


# ============================================================
# 메인 파싱 함수
# ============================================================

def parse(
    question: str,
    clarify_answers: Optional[Dict[str, str]] = None,
    max_retries: int = 1
) -> Tuple[Dict, List[str]]:
    """
    자연어 질문을 필터로 변환

    Args:
        question: 자연어 질문
        clarify_answers: Clarification 답변 (2nd turn)
        max_retries: LLM 재시도 횟수

    Returns:
        (result_dict, warnings)
        result_dict는 두 가지 형태:
        - {"type": "filters", "filters": {...}}
        - {"type": "clarify", "draft_filters": {...}, "questions": [...]}
    """
    warnings = []
    dim_dict = get_dim_dict()
    date_range = get_data_date_range()
    today = datetime.now()

    # Clarification 답변이 있으면 병합 처리
    if clarify_answers:
        # 먼저 룰 기반으로 기본 필터 추출
        base_filters, base_warnings = rule_based_fallback(question)
        warnings.extend(base_warnings)

        # clarify_answers 적용
        if "expensive_meaning" in clarify_answers:
            intent_map = {
                "high_avg_price": "high_avg_price",
                "high_price_change": "high_price_change",
                "high_volatility": "high_volatility"
            }
            base_filters["intent"] = intent_map.get(clarify_answers["expensive_meaning"], "normal")

        if "recent_window" in clarify_answers:
            window_map = {"30d": 30, "90d": 90, "180d": 180}
            base_filters["window_days"] = window_map.get(clarify_answers["recent_window"], 30)

            # date_from/date_to도 업데이트
            days = base_filters["window_days"]
            base_filters["date_to"] = today.strftime("%Y-%m-%d")
            base_filters["date_from"] = (today - timedelta(days=days)).strftime("%Y-%m-%d")

        # 필터 검증/보정
        corrected, corr_warnings = validate_and_correct_filter(
            base_filters.get("item_name", ""),
            base_filters.get("variety_name"),
            base_filters.get("market_name")
        )
        warnings.extend(corr_warnings)
        base_filters.update(corrected)

        return {"type": "filters", "filters": base_filters}, warnings

    # 시스템 프롬프트 구성 - "today"는 데이터 마지막 날짜 사용
    data_max_date = date_range[1] if date_range[1] else today.strftime("%Y-%m-%d")
    system = SYSTEM_PROMPT.format(
        item_names=", ".join(dim_dict["item_names"][:30]),  # 너무 길면 자르기
        variety_names=", ".join(dim_dict["variety_names"][:50]),
        market_names=", ".join(dim_dict["market_names"][:20]),
        date_range=f"{date_range[0]} ~ {date_range[1]}",
        today=data_max_date  # 데이터 마지막 날짜를 기준으로 사용
    )

    user_prompt = USER_PROMPT_TEMPLATE.format(question=question)
    full_prompt = f"{system}\n\n{user_prompt}"

    # LLM 호출 및 재시도
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                # 재시도 시 에러 정보 포함
                full_prompt = f"{system}\n\n" + RETRY_PROMPT_TEMPLATE.format(
                    error=str(last_error),
                    question=question
                )

            response_text = call_llm(full_prompt)
            parsed = extract_json_from_response(response_text)

            if not parsed:
                last_error = "JSON 파싱 실패"
                continue

            # 타입 확인
            response_type = parsed.get("type")

            if response_type == "filters":
                # 필터 검증
                filters_data = parsed.get("filters", {})
                try:
                    filter_obj = FilterRequest(**filters_data)
                    filters_dict = filter_obj.model_dump()

                    # 추가 검증/보정
                    corrected, corr_warnings = validate_and_correct_filter(
                        filters_dict.get("item_name", ""),
                        filters_dict.get("variety_name"),
                        filters_dict.get("market_name")
                    )
                    warnings.extend(corr_warnings)
                    filters_dict.update(corrected)

                    # 날짜 기본값 처리
                    if not filters_dict.get("date_from") or not filters_dict.get("date_to"):
                        date_from, date_to = get_default_date_range(
                            filters_dict.get("window_days", 90)
                        )
                        filters_dict["date_from"] = filters_dict.get("date_from") or date_from
                        filters_dict["date_to"] = filters_dict.get("date_to") or date_to
                        warnings.append("기간 미지정으로 기본값을 적용했습니다.")

                    warnings.extend(parsed.get("warnings", []))
                    return {"type": "filters", "filters": filters_dict}, warnings

                except ValidationError as e:
                    last_error = str(e)
                    continue

            elif response_type == "clarify":
                # Clarification 응답
                return {
                    "type": "clarify",
                    "draft_filters": parsed.get("draft_filters", {}),
                    "questions": parsed.get("questions", [])
                }, parsed.get("warnings", [])

            else:
                last_error = f"Unknown response type: {response_type}"
                continue

        except Exception as e:
            last_error = str(e)
            continue

    # 모든 재시도 실패 → 룰 기반 fallback
    fallback_filters, fallback_warnings = rule_based_fallback(question)
    warnings.extend(fallback_warnings)

    return {"type": "filters", "filters": fallback_filters}, warnings


# ============================================================
# 애매함 감지 함수
# ============================================================

def detect_ambiguity(question: str) -> List[Dict]:
    """
    질문에서 애매한 표현 감지
    Returns: 필요한 clarification questions 목록
    """
    questions = []

    # "요즘/최근/요새" + 구체적 기간 없음
    if re.search(r"요즘|요새", question) and not re.search(r"\d+\s*(개월|일|주|년)", question):
        questions.append({
            "id": "recent_window",
            "question": "어느 기간을 기준으로 분석할까요?",
            "options": ["30d", "90d", "180d"],
            "default": "30d"
        })

    # "비싼/싼" 등 가격 관련 애매함
    if re.search(r"비싼|비싸|싼|저렴", question):
        questions.append({
            "id": "expensive_meaning",
            "question": "'비싼/싼'의 기준을 선택해주세요:",
            "options": ["high_avg_price", "high_price_change", "high_volatility"],
            "default": "high_avg_price"
        })

    return questions[:2]  # 최대 2개
