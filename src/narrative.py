"""
내러티브 모듈: 데이터 기반 설명 생성
- Bedrock Titan을 사용한 자연어 설명 생성
- 토큰 제한을 위한 데이터 요약
"""
import os
import json
from typing import Dict, List, Optional

import boto3

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

NARRATIVE_PROMPT = """You are an agricultural market analyst. Based on the data provided, write a concise analysis in Korean.

RULES:
1. Base your analysis ONLY on the provided data
2. If data is insufficient, state that clearly
3. Avoid definitive causal statements; use expressions like "가능성이 있습니다", "추정됩니다"
4. Do not make investment recommendations
5. Write 5-8 sentences followed by 3 bullet points of key insights
6. Use Korean language

FILTER INFO:
- 품목: {item_name}
- 품종: {variety_name}
- 시장: {market_name}
- 기간: {date_from} ~ {date_to}
- 분석유형: {chart_type}

SUMMARY STATISTICS:
{summary_text}

RECENT DATA (last 20 points):
{recent_data}

Please provide the analysis in Korean:"""


FALLBACK_NARRATIVE = """📊 {item_name}{variety_suffix} 분석 결과{market_suffix}

📅 분석 기간: {date_from} ~ {date_to}

💰 주요 지표:
• 최근 가격: {latest_price}
• 전주 대비: {wow_pct}
• 전월 대비: {mom_pct}
• 변동성(14일): {volatility}

{trend_text}{data_quality_note}"""


# ============================================================
# 데이터 준비 함수
# ============================================================

def prepare_summary_text(summary: Dict) -> str:
    """요약 통계를 텍스트로 변환"""
    lines = []

    if summary.get("latest_price"):
        lines.append(f"- 최근 가격: {summary['latest_price']:,.0f}원/kg")

    if summary.get("latest_volume"):
        lines.append(f"- 최근 반입량: {summary['latest_volume']:,.0f}kg")

    if summary.get("wow_price_pct") is not None:
        direction = "상승" if summary["wow_price_pct"] > 0 else "하락"
        lines.append(f"- 전주 대비 가격: {abs(summary['wow_price_pct']):.1f}% {direction}")

    if summary.get("mom_price_pct") is not None:
        direction = "상승" if summary["mom_price_pct"] > 0 else "하락"
        lines.append(f"- 전월 대비 가격: {abs(summary['mom_price_pct']):.1f}% {direction}")

    if summary.get("volatility_14d"):
        lines.append(f"- 14일 변동성: {summary['volatility_14d']:.0f}")

    if summary.get("data_points"):
        lines.append(f"- 데이터 포인트: {summary['data_points']}개")

    if summary.get("missing_rate") is not None:
        lines.append(f"- 결측치 비율: {summary['missing_rate'] * 100:.1f}%")

    return "\n".join(lines) if lines else "요약 통계 없음"


def prepare_recent_data(series: List[Dict], limit: int = 20) -> str:
    """최근 데이터를 텍스트로 변환"""
    if not series:
        return "데이터 없음"

    # 최근 N개 포인트만 선택
    recent = series[-limit:] if len(series) > limit else series

    lines = []
    for point in recent:
        date = point.get("date", "N/A")
        price = f"{point['price']:,.0f}" if point.get("price") else "N/A"
        volume = f"{point['volume']:,.0f}" if point.get("volume") else "N/A"
        market = point.get("market_name", "")

        if market:
            lines.append(f"{date}: 가격 {price}원/kg, 반입량 {volume}kg ({market})")
        else:
            lines.append(f"{date}: 가격 {price}원/kg, 반입량 {volume}kg")

    return "\n".join(lines)


# ============================================================
# Nova 호출
# ============================================================

def call_llm_for_narrative(prompt: str, max_tokens: int = 512) -> str:
    """Bedrock Nova 호출하여 narrative 생성"""
    client = get_bedrock_client()

    body = {
        "messages": [
            {"role": "user", "content": [{"text": prompt}]}
        ],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": 0.3
        }
    }

    try:
        response = client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )

        result = json.loads(response["body"].read())
        output_text = result.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")
        return output_text.strip()

    except Exception as e:
        # 에러 시 fallback 반환
        return f"분석 생성 중 오류가 발생했습니다: {str(e)}"


# ============================================================
# 메인 함수
# ============================================================

def generate_narrative(
    filters: Dict,
    series: List[Dict],
    summary: Dict,
    use_llm: bool = False
) -> str:
    """
    데이터 기반 내러티브 생성

    Args:
        filters: 필터 정보
        series: 시계열 데이터
        summary: 요약 통계
        use_llm: LLM 사용 여부 (기본 False로 빠른 응답)

    Returns:
        생성된 설명 텍스트
    """
    # 데이터 부족 체크
    if not series or len(series) < 3:
        return generate_fallback_narrative(filters, summary, "데이터가 부족하여 상세 분석이 어렵습니다.")

    # 빠른 응답을 위해 기본적으로 fallback 사용 (LLM 호출 스킵)
    if not use_llm:
        return generate_fallback_narrative(filters, summary)

    # 프롬프트 구성
    prompt = NARRATIVE_PROMPT.format(
        item_name=filters.get("item_name", "알 수 없음"),
        variety_name=filters.get("variety_name") or "전체",
        market_name=filters.get("market_name") or "전국도매시장",
        date_from=filters.get("date_from") or "N/A",
        date_to=filters.get("date_to") or "N/A",
        chart_type=get_chart_type_korean(filters.get("chart_type", "trend")),
        summary_text=prepare_summary_text(summary),
        recent_data=prepare_recent_data(series, limit=20)
    )

    # Claude 호출
    narrative = call_llm_for_narrative(prompt)

    # 빈 응답이면 fallback
    if not narrative or len(narrative) < 20:
        return generate_fallback_narrative(filters, summary)

    return narrative


def generate_fallback_narrative(
    filters: Dict,
    summary: Dict,
    note: str = ""
) -> str:
    """규칙 기반 빠른 narrative 생성"""

    item_name = filters.get("item_name", "품목")
    variety_name = filters.get("variety_name")
    market_name = filters.get("market_name")

    variety_suffix = f" ({variety_name})" if variety_name else ""
    market_suffix = f" - {market_name}" if market_name else ""

    # 추세 텍스트 생성
    trend_text = ""
    wow_pct_val = summary.get("wow_price_pct")
    mom_pct_val = summary.get("mom_price_pct")

    if wow_pct_val is not None and mom_pct_val is not None:
        if wow_pct_val > 5:
            trend_text = "📈 최근 가격이 상승세를 보이고 있습니다.\n"
        elif wow_pct_val < -5:
            trend_text = "📉 최근 가격이 하락세를 보이고 있습니다.\n"
        else:
            trend_text = "➡️ 가격이 비교적 안정적입니다.\n"
    elif summary.get("trend_direction"):
        trend_text = f"📈 분석 기간 동안 가격은 {summary['trend_direction']} 추세를 보였습니다.\n"

    wow_pct = f"{wow_pct_val:+.1f}%" if wow_pct_val is not None else "N/A"
    mom_pct = f"{mom_pct_val:+.1f}%" if mom_pct_val is not None else "N/A"
    latest_price = f"{summary['latest_price']:,.0f}원/kg" if summary.get("latest_price") else "N/A"
    volatility = f"{summary['volatility_14d']:.0f}" if summary.get("volatility_14d") else "N/A"

    data_quality_note = ""
    if note:
        data_quality_note = f"\n⚠️ {note}"
    elif summary.get("missing_rate", 0) > 0.3:
        data_quality_note = "\n⚠️ 결측치 비율이 높아 분석 결과의 신뢰도가 제한적일 수 있습니다."

    return FALLBACK_NARRATIVE.format(
        item_name=item_name,
        variety_suffix=variety_suffix,
        market_suffix=market_suffix,
        date_from=filters.get("date_from") or "N/A",
        date_to=filters.get("date_to") or "N/A",
        trend_text=trend_text,
        latest_price=latest_price,
        wow_pct=wow_pct,
        mom_pct=mom_pct,
        volatility=volatility,
        data_quality_note=data_quality_note
    )


def get_chart_type_korean(chart_type: str) -> str:
    """chart_type을 한글로 변환"""
    mapping = {
        "trend": "가격 추세 분석",
        "compare_markets": "시장 비교 분석",
        "volume_price": "가격/반입량 분석",
        "volatility": "변동성 분석"
    }
    return mapping.get(chart_type, "추세 분석")
