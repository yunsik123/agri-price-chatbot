"""
스키마 정의: FilterRequest, Response, Clarification 등
LLM 출력 검증 및 API 응답 구조화에 사용
"""
from typing import List, Optional, Literal, Union
from pydantic import BaseModel, Field, field_validator
from datetime import date
import uuid


# ============================================================
# FilterRequest: LLM이 출력해야 하는 필터 스키마
# ============================================================

class FilterRequest(BaseModel):
    """LLM이 자연어에서 추출하는 필터 스키마"""

    # 필수
    item_name: str = Field(..., description="품목명 (예: 감자, 사과, 배추)")

    # 선택
    variety_name: Optional[str] = Field(None, description="품종명 (예: 수미, 후지)")
    market_name: Optional[str] = Field(None, description="시장명 (없으면 전국도매시장)")
    date_from: Optional[str] = Field(None, description="시작일 YYYY-MM-DD")
    date_to: Optional[str] = Field(None, description="종료일 YYYY-MM-DD")

    # 차트/분석 옵션
    chart_type: Literal["trend", "compare_markets", "volume_price", "volatility"] = Field(
        "trend", description="차트 유형"
    )
    metrics: List[Literal["price", "volume"]] = Field(
        default_factory=lambda: ["price", "volume"], description="표시할 지표"
    )
    granularity: Literal["daily", "weekly"] = Field(
        "weekly", description="집계 단위"
    )
    top_n_markets: Optional[int] = Field(5, description="compare_markets시 상위 N개 시장")
    explain: bool = Field(True, description="narrative 생성 여부")

    # K절: 애매한 질문 처리용 확장 필드
    intent: Literal["normal", "high_avg_price", "high_price_change", "high_volatility"] = Field(
        "normal", description="분석 의도"
    )
    window_days: Optional[int] = Field(30, description="최근 N일 범위")

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def validate_date_format(cls, v):
        if v is None:
            return v
        if isinstance(v, str) and len(v) == 10:
            try:
                date.fromisoformat(v)
                return v
            except ValueError:
                pass
        return None  # 잘못된 형식은 None으로 변환


# ============================================================
# Clarification: 애매한 질문 시 확인 질문 구조
# ============================================================

class ClarifyQuestion(BaseModel):
    """확인 질문 하나"""
    id: str = Field(..., description="질문 ID (예: expensive_meaning)")
    question: str = Field(..., description="사용자에게 보여줄 질문")
    options: List[str] = Field(..., description="선택지 목록")
    default: Optional[str] = Field(None, description="기본 선택값")


class Clarification(BaseModel):
    """Clarification 응답 구조"""
    draft_filters: dict = Field(..., description="추론된 부분 필터")
    questions: List[ClarifyQuestion] = Field(..., description="확인 질문 목록 (최대 2개)")


# ============================================================
# NLU 출력 스키마 (LLM 응답 검증용)
# ============================================================

class NLUFiltersOutput(BaseModel):
    """LLM이 확정 필터를 출력할 때"""
    type: Literal["filters"] = "filters"
    filters: FilterRequest
    warnings: List[str] = Field(default_factory=list)


class NLUClarifyOutput(BaseModel):
    """LLM이 확인 질문을 출력할 때"""
    type: Literal["clarify"] = "clarify"
    draft_filters: dict = Field(default_factory=dict)
    questions: List[ClarifyQuestion]
    warnings: List[str] = Field(default_factory=list)


# Union 타입으로 LLM 출력 검증
NLUOutput = Union[NLUFiltersOutput, NLUClarifyOutput]


# ============================================================
# Series/Summary: 데이터 응답 구조
# ============================================================

class SeriesPoint(BaseModel):
    """시계열 데이터 포인트"""
    date: str = Field(..., description="날짜 YYYY-MM-DD")
    price: Optional[float] = Field(None, description="평균가(원/kg)")
    volume: Optional[float] = Field(None, description="총반입량(kg)")
    market_name: Optional[str] = Field(None, description="시장명 (compare_markets용)")


class SummaryStats(BaseModel):
    """요약 통계"""
    latest_price: Optional[float] = Field(None, description="최근 가격")
    latest_volume: Optional[float] = Field(None, description="최근 반입량")
    wow_price_pct: Optional[float] = Field(None, description="전주 대비 가격 변화율(%)")
    wow_volume_pct: Optional[float] = Field(None, description="전주 대비 반입량 변화율(%)")
    mom_price_pct: Optional[float] = Field(None, description="전월 대비 가격 변화율(%)")
    volatility_14d: Optional[float] = Field(None, description="14일 변동성(rolling std)")
    data_points: int = Field(0, description="데이터 포인트 수")
    missing_rate: float = Field(0.0, description="결측치 비율")


# ============================================================
# API Response: 최종 응답 스키마
# ============================================================

class APIResponse(BaseModel):
    """API 최종 응답"""
    type: Literal["result", "clarify"] = Field(..., description="응답 유형")
    filters: Optional[FilterRequest] = Field(None, description="적용된 필터")
    series: List[SeriesPoint] = Field(default_factory=list, description="시계열 데이터")
    summary: Optional[SummaryStats] = Field(None, description="요약 통계")
    narrative: str = Field("", description="LLM 생성 설명")
    warnings: List[str] = Field(default_factory=list, description="경고 메시지")
    clarification: Optional[Clarification] = Field(None, description="확인 질문 (clarify시)")
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="요청 ID")


class APIErrorResponse(BaseModel):
    """API 에러 응답"""
    error: dict = Field(..., description="에러 정보 {code, message}")
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ============================================================
# 헬퍼 함수
# ============================================================

def create_error_response(code: str, message: str, request_id: Optional[str] = None) -> dict:
    """표준 에러 응답 생성"""
    return {
        "error": {"code": code, "message": message},
        "request_id": request_id or str(uuid.uuid4())
    }


def create_clarify_response(
    draft_filters: dict,
    questions: List[dict],
    warnings: List[str] = None,
    request_id: Optional[str] = None
) -> dict:
    """Clarification 응답 생성"""
    return APIResponse(
        type="clarify",
        filters=None,
        series=[],
        summary=None,
        narrative="",
        warnings=warnings or ["질문이 애매하여 확인이 필요합니다."],
        clarification=Clarification(
            draft_filters=draft_filters,
            questions=[ClarifyQuestion(**q) for q in questions]
        ),
        request_id=request_id or str(uuid.uuid4())
    ).model_dump()
