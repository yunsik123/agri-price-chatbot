"""
pytest 설정 및 fixture
"""
import os
import sys
import pytest
import pandas as pd

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_filters():
    """테스트용 기본 필터"""
    return {
        "item_name": "감자",
        "variety_name": "수미",
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


@pytest.fixture
def sample_series():
    """테스트용 시계열 데이터"""
    return [
        {"date": "2018-01-05", "price": 1500.0, "volume": 10000.0, "market_name": None},
        {"date": "2018-01-15", "price": 1600.0, "volume": 12000.0, "market_name": None},
        {"date": "2018-01-25", "price": 1550.0, "volume": 11000.0, "market_name": None},
        {"date": "2018-02-05", "price": 1700.0, "volume": 13000.0, "market_name": None},
        {"date": "2018-02-15", "price": 1650.0, "volume": 12500.0, "market_name": None},
        {"date": "2018-02-25", "price": 1800.0, "volume": 14000.0, "market_name": None},
        {"date": "2018-03-05", "price": 1750.0, "volume": 13500.0, "market_name": None},
        {"date": "2018-03-15", "price": 1900.0, "volume": 15000.0, "market_name": None},
    ]


@pytest.fixture
def sample_summary():
    """테스트용 요약 통계"""
    return {
        "latest_price": 1900.0,
        "latest_volume": 15000.0,
        "wow_price_pct": 8.57,
        "wow_volume_pct": 11.11,
        "mom_price_pct": 26.67,
        "volatility_14d": 150.5,
        "data_points": 8,
        "missing_rate": 0.0
    }


@pytest.fixture
def test_questions():
    """테스트용 질문 목록"""
    return [
        "감자 수미, 최근 6개월 가격 추세 보여줘",
        "양파, 전국도매시장, 2019년 가격과 반입량 같이 보여줘",
        "배추, 최근 3개월 변동성(급등락) 큰 구간 알려줘",
        "마늘, 시장별 비교해줘(상위 5개 시장)",
        "대파, 최근 한달 가격이 전월 대비 얼마나 올랐어?"
    ]
