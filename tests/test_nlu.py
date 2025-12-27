"""
NLU 모듈 테스트 (모킹 사용)
"""
import pytest
from unittest.mock import patch, MagicMock
from src.nlu import (
    parse_date_expression,
    rule_based_fallback,
    detect_ambiguity,
    parse,
    extract_json_from_response
)
from datetime import datetime


class TestParseDateExpression:
    """날짜 표현 파싱 테스트"""

    def test_recent_months(self):
        """최근 N개월"""
        today = datetime(2024, 6, 15)
        date_from, date_to = parse_date_expression("최근 6개월", today)
        assert date_from == "2023-12-15"
        assert date_to == "2024-06-15"

    def test_recent_days(self):
        """최근 N일"""
        today = datetime(2024, 6, 15)
        date_from, date_to = parse_date_expression("최근 30일", today)
        assert date_from == "2024-05-16"
        assert date_to == "2024-06-15"

    def test_recent_month(self):
        """최근 한달"""
        today = datetime(2024, 6, 15)
        date_from, date_to = parse_date_expression("최근 한달", today)
        assert date_from == "2024-05-15"
        assert date_to == "2024-06-15"

    def test_last_year(self):
        """작년"""
        today = datetime(2024, 6, 15)
        date_from, date_to = parse_date_expression("작년", today)
        assert date_from == "2023-01-01"
        assert date_to == "2023-12-31"

    def test_specific_year(self):
        """특정 년도"""
        date_from, date_to = parse_date_expression("2019년", datetime.now())
        assert date_from == "2019-01-01"
        assert date_to == "2019-12-31"

    def test_no_date(self):
        """날짜 표현 없음"""
        date_from, date_to = parse_date_expression("감자 가격 알려줘", datetime.now())
        assert date_from is None
        assert date_to is None


class TestRuleBasedFallback:
    """룰 기반 fallback 테스트"""

    def test_item_extraction(self):
        """품목 추출"""
        filters, warnings = rule_based_fallback("감자 가격 보여줘")
        assert filters["item_name"] == "감자"

    def test_variety_extraction(self):
        """품종 추출"""
        filters, warnings = rule_based_fallback("감자 수미 가격")
        assert filters["item_name"] == "감자"
        # 품종은 dim_dict에 있어야 추출됨

    def test_market_extraction(self):
        """시장 추출"""
        filters, warnings = rule_based_fallback("전국도매시장 감자")
        assert filters["item_name"] == "감자"
        assert filters["market_name"] == "전국도매시장"

    def test_chart_type_inference(self):
        """차트 유형 추론"""
        filters, warnings = rule_based_fallback("감자 시장별 비교")
        assert filters["chart_type"] == "compare_markets"

        filters2, _ = rule_based_fallback("배추 변동성 분석")
        assert filters2["chart_type"] == "volatility"

    def test_intent_inference(self):
        """intent 추론"""
        filters, warnings = rule_based_fallback("감자 비싼 곳")
        assert filters["intent"] == "high_avg_price"

        filters2, _ = rule_based_fallback("양파 가격 올랐어?")
        assert filters2["intent"] == "high_price_change"

    def test_default_item(self):
        """품목 없을 때 기본값"""
        filters, warnings = rule_based_fallback("가격 보여줘")
        assert filters["item_name"] == "감자"  # 기본값
        assert any("찾을 수 없어" in w for w in warnings)


class TestDetectAmbiguity:
    """애매함 감지 테스트"""

    def test_recent_ambiguity(self):
        """'요즘' 애매함"""
        questions = detect_ambiguity("감자 요즘 비싸?")
        assert len(questions) >= 1
        ids = [q["id"] for q in questions]
        assert "recent_window" in ids or "expensive_meaning" in ids

    def test_expensive_ambiguity(self):
        """'비싼' 애매함"""
        questions = detect_ambiguity("감자 비싼 시장")
        ids = [q["id"] for q in questions]
        assert "expensive_meaning" in ids

    def test_no_ambiguity(self):
        """명확한 질문"""
        questions = detect_ambiguity("감자 2019년 가격 추세")
        # 명확한 경우 질문이 없거나 적음
        assert len(questions) <= 2


class TestExtractJsonFromResponse:
    """JSON 추출 테스트"""

    def test_clean_json(self):
        """깨끗한 JSON"""
        text = '{"type": "filters", "filters": {"item_name": "감자"}}'
        result = extract_json_from_response(text)
        assert result["type"] == "filters"

    def test_json_in_code_block(self):
        """코드 블록 내 JSON"""
        text = '```json\n{"type": "filters", "filters": {"item_name": "감자"}}\n```'
        result = extract_json_from_response(text)
        assert result["type"] == "filters"

    def test_json_with_text(self):
        """텍스트와 함께"""
        text = 'Here is the result: {"type": "filters", "filters": {"item_name": "감자"}}'
        result = extract_json_from_response(text)
        assert result["type"] == "filters"

    def test_invalid_json(self):
        """잘못된 JSON"""
        text = "This is not JSON"
        result = extract_json_from_response(text)
        assert result is None


class TestParse:
    """parse 함수 테스트 (모킹)"""

    @patch("src.nlu.call_titan")
    def test_parse_with_mock(self, mock_titan):
        """LLM 모킹 테스트"""
        mock_titan.return_value = '{"type": "filters", "filters": {"item_name": "감자"}, "warnings": []}'

        result, warnings = parse("감자 가격 보여줘")
        assert result["type"] == "filters"
        assert result["filters"]["item_name"] == "감자"

    @patch("src.nlu.call_titan")
    def test_parse_clarify_output(self, mock_titan):
        """clarify 출력 테스트"""
        mock_titan.return_value = '''
        {
            "type": "clarify",
            "draft_filters": {"item_name": "감자"},
            "questions": [
                {"id": "expensive_meaning", "question": "어떤 기준?", "options": ["a", "b"], "default": "a"}
            ],
            "warnings": []
        }
        '''

        result, warnings = parse("감자 요즘 비싼 거")
        assert result["type"] == "clarify"
        assert "questions" in result

    @patch("src.nlu.call_titan")
    def test_parse_fallback_on_error(self, mock_titan):
        """LLM 에러 시 fallback"""
        mock_titan.side_effect = Exception("API Error")

        result, warnings = parse("감자 가격 보여줘")
        # fallback으로 결과가 나와야 함
        assert result["type"] == "filters"
        assert result["filters"]["item_name"] == "감자"
        assert any("규칙 기반" in w for w in warnings)

    def test_parse_with_clarify_answers(self):
        """clarify_answers 처리"""
        clarify_answers = {
            "expensive_meaning": "high_avg_price",
            "recent_window": "30d"
        }

        result, warnings = parse("감자 요즘 비싼 거", clarify_answers=clarify_answers)
        assert result["type"] == "filters"
        assert result["filters"]["intent"] == "high_avg_price"
        assert result["filters"]["window_days"] == 30
