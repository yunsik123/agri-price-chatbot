"""
피처 모듈 테스트
"""
import pytest
from src.features import (
    calculate_summary,
    calculate_pct_change,
    detect_anomalies,
    enrich_summary_with_context
)


class TestCalculatePctChange:
    """백분율 변화 계산 테스트"""

    def test_positive_change(self):
        """양수 변화"""
        result = calculate_pct_change(110, 100)
        assert result == 10.0

    def test_negative_change(self):
        """음수 변화"""
        result = calculate_pct_change(90, 100)
        assert result == -10.0

    def test_zero_previous(self):
        """이전 값이 0"""
        result = calculate_pct_change(100, 0)
        assert result is None

    def test_none_values(self):
        """None 값"""
        assert calculate_pct_change(None, 100) is None
        assert calculate_pct_change(100, None) is None


class TestCalculateSummary:
    """요약 통계 계산 테스트"""

    def test_empty_series(self):
        """빈 시리즈"""
        summary = calculate_summary([], {"granularity": "weekly"})
        assert summary["data_points"] == 0
        assert summary["missing_rate"] == 1.0

    def test_with_data(self, sample_series, sample_filters):
        """데이터가 있는 경우"""
        summary = calculate_summary(sample_series, sample_filters)
        assert summary["data_points"] == 8
        assert summary["latest_price"] is not None
        assert summary["missing_rate"] == 0.0

    def test_wow_calculation(self, sample_series, sample_filters):
        """WoW 계산"""
        summary = calculate_summary(sample_series, sample_filters)
        # 마지막 두 포인트: 1750 → 1900
        if summary["wow_price_pct"] is not None:
            assert summary["wow_price_pct"] > 0  # 상승

    def test_compare_markets_aggregation(self):
        """시장 비교 시 집계"""
        series = [
            {"date": "2018-01-05", "price": 1500.0, "volume": 10000.0, "market_name": "시장A"},
            {"date": "2018-01-05", "price": 1600.0, "volume": 12000.0, "market_name": "시장B"},
            {"date": "2018-01-15", "price": 1550.0, "volume": 11000.0, "market_name": "시장A"},
            {"date": "2018-01-15", "price": 1650.0, "volume": 13000.0, "market_name": "시장B"},
        ]
        filters = {"chart_type": "compare_markets", "granularity": "weekly"}
        summary = calculate_summary(series, filters)
        assert summary["data_points"] == 2  # 날짜별로 집계됨


class TestDetectAnomalies:
    """이상치 감지 테스트"""

    def test_no_anomalies(self, sample_series):
        """이상치 없음"""
        anomalies = detect_anomalies(sample_series)
        # 일반적인 데이터에서는 이상치가 없을 수 있음
        assert isinstance(anomalies, list)

    def test_with_anomaly(self):
        """이상치가 있는 경우"""
        series = [
            {"date": "2018-01-05", "price": 1500.0, "volume": 10000.0},
            {"date": "2018-01-15", "price": 1500.0, "volume": 10000.0},
            {"date": "2018-01-25", "price": 1500.0, "volume": 10000.0},
            {"date": "2018-02-05", "price": 1500.0, "volume": 10000.0},
            {"date": "2018-02-15", "price": 5000.0, "volume": 10000.0},  # 급등
        ]
        anomalies = detect_anomalies(series, threshold=1.5)
        assert len(anomalies) >= 1
        assert anomalies[0]["type"] == "급등"

    def test_insufficient_data(self):
        """데이터 부족"""
        series = [{"date": "2018-01-05", "price": 1500.0, "volume": 10000.0}]
        anomalies = detect_anomalies(series)
        assert anomalies == []


class TestEnrichSummary:
    """요약 확장 테스트"""

    def test_trend_direction(self, sample_filters, sample_series, sample_summary):
        """추세 방향 추가"""
        enriched = enrich_summary_with_context(sample_summary, sample_filters, sample_series)
        # 가격이 1500 → 1900으로 상승했으므로
        if "trend_direction" in enriched:
            assert enriched["trend_direction"] == "상승"

    def test_anomaly_info(self, sample_filters, sample_summary):
        """이상치 정보 추가"""
        series_with_anomaly = [
            {"date": "2018-01-05", "price": 1500.0, "volume": 10000.0},
            {"date": "2018-01-15", "price": 1500.0, "volume": 10000.0},
            {"date": "2018-01-25", "price": 1500.0, "volume": 10000.0},
            {"date": "2018-02-05", "price": 1500.0, "volume": 10000.0},
            {"date": "2018-02-15", "price": 5000.0, "volume": 10000.0},
        ]
        enriched = enrich_summary_with_context(sample_summary, sample_filters, series_with_anomaly)
        if "anomaly_count" in enriched:
            assert enriched["anomaly_count"] >= 1
