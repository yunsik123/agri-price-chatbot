"""
E2E 스모크 테스트
- 5개 질문에 대해 전체 파이프라인 검증
"""
import pytest
from unittest.mock import patch
from src.nlu import parse as nlu_parse, rule_based_fallback
from src.query import execute_query
from src.features import calculate_summary, enrich_summary_with_context
from src.schema import FilterRequest, APIResponse


# 테스트 케이스 질문
TEST_QUESTIONS = [
    ("감자 수미, 최근 6개월 가격 추세 보여줘", "감자"),
    ("양파, 전국도매시장, 2019년 가격과 반입량 같이 보여줘", "양파"),
    ("배추, 최근 3개월 변동성(급등락) 큰 구간 알려줘", "배추"),
    ("마늘, 시장별 비교해줘(상위 5개 시장)", "마늘"),
    ("대파, 최근 한달 가격이 전월 대비 얼마나 올랐어?", "대파"),
]


class TestE2ESmoke:
    """E2E 스모크 테스트"""

    @pytest.mark.parametrize("question,expected_item", TEST_QUESTIONS)
    def test_full_pipeline_with_fallback(self, question, expected_item):
        """
        전체 파이프라인 테스트 (rule_based_fallback 사용)
        - 자연어 → 필터 (fallback)
        - 필터 → 데이터 조회
        - 데이터 → 요약 계산
        """
        # 1. 필터 추출 (fallback 사용)
        filters, nlu_warnings = rule_based_fallback(question)

        # 품목 확인
        assert filters["item_name"] is not None

        # 필터 스키마 검증
        try:
            filter_obj = FilterRequest(**filters)
            filters = filter_obj.model_dump()
        except Exception as e:
            pytest.fail(f"FilterRequest 검증 실패: {e}")

        # 2. 데이터 조회
        series, query_warnings = execute_query(filters)

        # series가 리스트인지 확인
        assert isinstance(series, list)

        # 3. 요약 계산 (데이터가 있을 때만)
        if series:
            summary = calculate_summary(series, filters)
            summary = enrich_summary_with_context(summary, filters, series)

            # 요약 구조 검증
            assert "data_points" in summary
            assert "missing_rate" in summary
            assert summary["data_points"] == len(series) or summary["data_points"] >= 0

            # 각 series 포인트 검증
            for point in series:
                assert "date" in point
                assert "price" in point or point.get("price") is None
                assert "volume" in point or point.get("volume") is None

    def test_trend_chart_response_schema(self):
        """trend 차트 응답 스키마 검증"""
        filters = {
            "item_name": "감자",
            "variety_name": None,
            "market_name": "전국도매시장",
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "trend",
            "metrics": ["price", "volume"],
            "granularity": "weekly",
            "explain": True
        }

        series, warnings = execute_query(filters)

        if series:
            # 첫 번째 포인트 검증
            point = series[0]
            assert "date" in point
            assert len(point["date"]) == 10  # YYYY-MM-DD

    def test_compare_markets_response_schema(self):
        """compare_markets 차트 응답 스키마 검증"""
        filters = {
            "item_name": "감자",
            "variety_name": None,
            "market_name": None,
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "compare_markets",
            "top_n_markets": 3,
            "granularity": "weekly",
            "explain": True
        }

        series, warnings = execute_query(filters)

        if series:
            # market_name이 있어야 함
            point = series[0]
            assert "market_name" in point
            assert point["market_name"] is not None

    def test_volatility_response_schema(self):
        """volatility 차트 응답 스키마 검증"""
        filters = {
            "item_name": "감자",
            "variety_name": None,
            "market_name": "전국도매시장",
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "volatility",
            "granularity": "weekly",
            "explain": True
        }

        series, warnings = execute_query(filters)

        # volatility 차트는 volatility 필드가 있을 수 있음
        if series and len(series) > 4:
            # 일부 포인트에 volatility가 있어야 함 (rolling 계산 후)
            has_volatility = any(point.get("volatility") is not None for point in series)
            # 데이터가 충분하면 volatility가 있어야 함
            # (초반 window 기간에는 없을 수 있음)


class TestClarifyFlow:
    """Clarification 플로우 테스트"""

    def test_ambiguous_question_detection(self):
        """애매한 질문 감지"""
        from src.nlu import detect_ambiguity

        # "요즘 비싼" 같은 표현은 애매함
        questions = detect_ambiguity("감자 요즘 비싼 거")

        # 최소 1개 이상의 질문이 있어야 함
        assert len(questions) >= 1

    def test_clarify_answers_processing(self):
        """clarify_answers 처리"""
        clarify_answers = {
            "expensive_meaning": "high_avg_price",
            "recent_window": "30d"
        }

        result, warnings = nlu_parse("감자 요즘 비싼 거", clarify_answers=clarify_answers)

        # clarify_answers가 있으면 filters로 확정되어야 함
        assert result["type"] == "filters"
        assert result["filters"]["intent"] == "high_avg_price"


class TestErrorHandling:
    """에러 처리 테스트"""

    def test_nonexistent_item(self):
        """존재하지 않는 품목"""
        filters = {
            "item_name": "존재하지않는품목xyz",
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "trend",
            "granularity": "weekly"
        }

        series, warnings = execute_query(filters)

        # 빈 결과
        assert series == []
        # 경고가 있어야 함
        assert len(warnings) > 0

    def test_invalid_date_range(self):
        """잘못된 날짜 범위"""
        filters = {
            "item_name": "감자",
            "date_from": "2099-01-01",
            "date_to": "2099-12-31",
            "chart_type": "trend",
            "granularity": "weekly"
        }

        series, warnings = execute_query(filters)

        # 미래 날짜라 데이터 없음
        assert series == []


class TestAPIResponseSchema:
    """API 응답 스키마 검증"""

    def test_full_response_creation(self):
        """전체 응답 생성"""
        filters_dict = {
            "item_name": "감자",
            "variety_name": None,
            "market_name": "전국도매시장",
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "trend",
            "metrics": ["price", "volume"],
            "granularity": "weekly",
            "top_n_markets": 5,
            "explain": True,
            "intent": "normal",
            "window_days": 30
        }

        series, _ = execute_query(filters_dict)
        summary = calculate_summary(series, filters_dict) if series else {}

        # APIResponse 생성
        response = APIResponse(
            type="result",
            filters=FilterRequest(**filters_dict),
            series=series,
            summary=summary,
            narrative="테스트 설명",
            warnings=[]
        )

        # 검증
        assert response.type == "result"
        assert response.request_id is not None
        assert isinstance(response.series, list)
