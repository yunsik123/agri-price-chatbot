"""
스키마 테스트
"""
import pytest
from pydantic import ValidationError
from src.schema import (
    FilterRequest, APIResponse, SummaryStats, SeriesPoint,
    NLUFiltersOutput, NLUClarifyOutput, ClarifyQuestion
)


class TestFilterRequest:
    """FilterRequest 스키마 테스트"""

    def test_required_item_name(self):
        """품목명 필수 검증"""
        with pytest.raises(ValidationError):
            FilterRequest()

    def test_valid_filter(self, sample_filters):
        """유효한 필터 생성"""
        filter_obj = FilterRequest(**sample_filters)
        assert filter_obj.item_name == "감자"
        assert filter_obj.variety_name == "수미"
        assert filter_obj.chart_type == "trend"

    def test_default_values(self):
        """기본값 테스트"""
        filter_obj = FilterRequest(item_name="감자")
        assert filter_obj.chart_type == "trend"
        assert filter_obj.metrics == ["price", "volume"]
        assert filter_obj.granularity == "weekly"
        assert filter_obj.explain is True
        assert filter_obj.intent == "normal"
        assert filter_obj.window_days == 30

    def test_invalid_chart_type(self):
        """잘못된 chart_type 검증"""
        with pytest.raises(ValidationError):
            FilterRequest(item_name="감자", chart_type="invalid")

    def test_invalid_date_format(self):
        """잘못된 날짜 형식은 None으로 변환"""
        filter_obj = FilterRequest(item_name="감자", date_from="invalid-date")
        assert filter_obj.date_from is None

    def test_valid_date_format(self):
        """유효한 날짜 형식"""
        filter_obj = FilterRequest(item_name="감자", date_from="2024-01-15")
        assert filter_obj.date_from == "2024-01-15"


class TestSummaryStats:
    """SummaryStats 스키마 테스트"""

    def test_all_nullable(self):
        """모든 필드가 nullable"""
        summary = SummaryStats()
        assert summary.latest_price is None
        assert summary.data_points == 0

    def test_with_values(self, sample_summary):
        """값이 있는 경우"""
        summary = SummaryStats(**sample_summary)
        assert summary.latest_price == 1900.0
        assert summary.wow_price_pct == 8.57


class TestNLUOutput:
    """NLU 출력 스키마 테스트"""

    def test_filters_output(self, sample_filters):
        """filters 타입 출력"""
        output = NLUFiltersOutput(
            filters=FilterRequest(**sample_filters),
            warnings=["test warning"]
        )
        assert output.type == "filters"
        assert output.filters.item_name == "감자"
        assert len(output.warnings) == 1

    def test_clarify_output(self):
        """clarify 타입 출력"""
        output = NLUClarifyOutput(
            draft_filters={"item_name": "감자"},
            questions=[
                ClarifyQuestion(
                    id="expensive_meaning",
                    question="어떤 기준으로 분석할까요?",
                    options=["high_avg_price", "high_price_change"],
                    default="high_avg_price"
                )
            ]
        )
        assert output.type == "clarify"
        assert len(output.questions) == 1
        assert output.questions[0].id == "expensive_meaning"


class TestAPIResponse:
    """API 응답 스키마 테스트"""

    def test_result_response(self, sample_filters, sample_series, sample_summary):
        """result 타입 응답"""
        response = APIResponse(
            type="result",
            filters=FilterRequest(**sample_filters),
            series=[SeriesPoint(**s) for s in sample_series],
            summary=SummaryStats(**sample_summary),
            narrative="테스트 설명",
            warnings=[]
        )
        assert response.type == "result"
        assert len(response.series) == 8
        assert response.request_id is not None

    def test_clarify_response(self):
        """clarify 타입 응답"""
        response = APIResponse(
            type="clarify",
            filters=None,
            series=[],
            summary=None,
            narrative="",
            warnings=["질문이 애매합니다."]
        )
        assert response.type == "clarify"
        assert response.filters is None
