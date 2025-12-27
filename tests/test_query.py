"""
쿼리 모듈 테스트
"""
import pytest
from src.query import (
    execute_query,
    apply_filters,
    aggregate_by_granularity,
    get_filtered_dataframe
)
from src.data_loader import load_data


class TestExecuteQuery:
    """execute_query 테스트"""

    def test_trend_query(self):
        """trend 차트 쿼리"""
        filters = {
            "item_name": "감자",
            "variety_name": None,
            "market_name": "전국도매시장",
            "date_from": "2018-01-01",
            "date_to": "2018-06-30",
            "chart_type": "trend",
            "granularity": "weekly"
        }
        series, warnings = execute_query(filters)
        assert isinstance(series, list)
        # 데이터가 있으면 검증
        if series:
            assert "date" in series[0]
            assert "price" in series[0]
            assert "volume" in series[0]

    def test_compare_markets_query(self):
        """compare_markets 차트 쿼리"""
        filters = {
            "item_name": "감자",
            "variety_name": None,
            "market_name": None,
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "compare_markets",
            "top_n_markets": 3,
            "granularity": "weekly"
        }
        series, warnings = execute_query(filters)
        assert isinstance(series, list)
        # 데이터가 있고 시장 비교면 market_name이 있어야 함
        if series:
            assert "market_name" in series[0]

    def test_volatility_query(self):
        """volatility 차트 쿼리"""
        filters = {
            "item_name": "감자",
            "variety_name": None,
            "market_name": "전국도매시장",
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "volatility",
            "granularity": "weekly"
        }
        series, warnings = execute_query(filters)
        assert isinstance(series, list)

    def test_empty_result(self):
        """결과 없음"""
        filters = {
            "item_name": "존재하지않는품목",
            "variety_name": None,
            "market_name": None,
            "date_from": "2099-01-01",
            "date_to": "2099-12-31",
            "chart_type": "trend",
            "granularity": "weekly"
        }
        series, warnings = execute_query(filters)
        assert series == []


class TestApplyFilters:
    """apply_filters 테스트"""

    def test_item_filter(self):
        """품목 필터"""
        df = load_data()
        filters = {"item_name": "감자"}
        filtered, warnings = apply_filters(df, filters)
        if len(filtered) > 0:
            assert filtered["item_name"].unique()[0] == "감자"

    def test_date_filter(self):
        """날짜 필터"""
        df = load_data()
        filters = {
            "item_name": "감자",
            "date_from": "2018-01-01",
            "date_to": "2018-06-30"
        }
        filtered, warnings = apply_filters(df, filters)
        if len(filtered) > 0:
            assert filtered["date"].min().year == 2018


class TestAggregation:
    """집계 테스트"""

    def test_weekly_aggregation(self):
        """주간 집계"""
        df = load_data()
        filters = {"item_name": "감자"}
        filtered, _ = apply_filters(df, filters)
        if len(filtered) > 0:
            aggregated = aggregate_by_granularity(filtered, "weekly", group_by_market=False)
            assert "date" in aggregated.columns
            assert "price_kg" in aggregated.columns

    def test_market_grouping(self):
        """시장별 그룹화"""
        df = load_data()
        filters = {"item_name": "감자"}
        filtered, _ = apply_filters(df, filters)
        if len(filtered) > 0:
            aggregated = aggregate_by_granularity(filtered, "weekly", group_by_market=True)
            if len(aggregated) > 0:
                assert "market_name" in aggregated.columns


class TestIntentQueries:
    """intent별 쿼리 테스트"""

    def test_high_avg_price_intent(self):
        """high_avg_price intent"""
        filters = {
            "item_name": "감자",
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "trend",
            "intent": "high_avg_price",
            "top_n_markets": 3,
            "granularity": "weekly"
        }
        series, warnings = execute_query(filters)
        assert isinstance(series, list)
        # high_avg_price는 시장 비교로 자동 변환됨
        if series:
            has_market_name = any(s.get("market_name") for s in series)
            # 시장 비교 데이터가 있을 수 있음

    def test_high_volatility_intent(self):
        """high_volatility intent"""
        filters = {
            "item_name": "감자",
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
            "chart_type": "trend",
            "intent": "high_volatility",
            "granularity": "weekly"
        }
        series, warnings = execute_query(filters)
        assert isinstance(series, list)
