"""
피처 모듈: 요약지표 계산
- WoW (Week-over-Week)
- MoM (Month-over-Month)
- 변동성 (volatility_14d)
- 데이터 품질 지표
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional

from .query import get_filtered_dataframe
from .schema import SummaryStats


def calculate_pct_change(current: float, previous: float) -> Optional[float]:
    """백분율 변화 계산"""
    if previous is None or previous == 0 or pd.isna(previous):
        return None
    if current is None or pd.isna(current):
        return None
    return round(((current - previous) / previous) * 100, 2)


def calculate_summary(series: List[Dict], filters: Dict) -> Dict:
    """
    series 데이터로부터 요약 통계 계산

    Args:
        series: 시계열 데이터 리스트
        filters: 필터 정보

    Returns:
        SummaryStats dict
    """
    if not series:
        return SummaryStats(
            latest_price=None,
            latest_volume=None,
            wow_price_pct=None,
            wow_volume_pct=None,
            mom_price_pct=None,
            volatility_14d=None,
            data_points=0,
            missing_rate=1.0
        ).model_dump()

    # DataFrame으로 변환
    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    # compare_markets의 경우 시장별로 그룹화되어 있으므로 전체 집계
    if filters.get("chart_type") == "compare_markets" and "market_name" in df.columns:
        # 날짜별로 평균 계산
        df = df.groupby("date", as_index=False).agg({
            "price": "mean",
            "volume": "sum"
        })

    # 데이터 포인트 수
    data_points = len(df)

    # 결측치 비율
    price_missing = df["price"].isna().sum() / len(df) if len(df) > 0 else 1.0
    volume_missing = df["volume"].isna().sum() / len(df) if len(df) > 0 else 1.0
    missing_rate = round((price_missing + volume_missing) / 2, 4)

    # 최신 값
    latest_row = df.iloc[-1] if len(df) > 0 else None
    latest_price = round(latest_row["price"], 2) if latest_row is not None and pd.notna(latest_row.get("price")) else None
    latest_volume = round(latest_row["volume"], 2) if latest_row is not None and pd.notna(latest_row.get("volume")) else None

    # WoW (Week-over-Week) 계산
    # granularity에 따라 1주 전 데이터 찾기
    granularity = filters.get("granularity", "weekly")
    wow_price_pct = None
    wow_volume_pct = None

    if granularity == "weekly" and len(df) >= 2:
        current_price = df.iloc[-1]["price"]
        previous_price = df.iloc[-2]["price"]
        wow_price_pct = calculate_pct_change(current_price, previous_price)

        current_volume = df.iloc[-1]["volume"]
        previous_volume = df.iloc[-2]["volume"]
        wow_volume_pct = calculate_pct_change(current_volume, previous_volume)

    elif granularity == "daily" and len(df) >= 7:
        current_price = df.iloc[-1]["price"]
        previous_price = df.iloc[-7]["price"]
        wow_price_pct = calculate_pct_change(current_price, previous_price)

        current_volume = df.iloc[-1]["volume"]
        previous_volume = df.iloc[-7]["volume"]
        wow_volume_pct = calculate_pct_change(current_volume, previous_volume)

    # MoM (Month-over-Month) 계산
    # 약 4주 전 데이터 비교
    mom_price_pct = None

    if granularity == "weekly" and len(df) >= 5:
        current_price = df.iloc[-1]["price"]
        previous_price = df.iloc[-5]["price"] if len(df) >= 5 else df.iloc[0]["price"]
        mom_price_pct = calculate_pct_change(current_price, previous_price)

    elif granularity == "daily" and len(df) >= 30:
        current_price = df.iloc[-1]["price"]
        previous_price = df.iloc[-30]["price"]
        mom_price_pct = calculate_pct_change(current_price, previous_price)

    # 변동성 계산 (14일/4주 rolling std)
    volatility_14d = None

    price_series = df["price"].dropna()
    if len(price_series) >= 4:
        # 주간 데이터면 4주, 일간 데이터면 14일
        window = 4 if granularity == "weekly" else 14
        window = min(window, len(price_series))
        rolling_std = price_series.rolling(window=window, min_periods=2).std()
        volatility_14d = round(rolling_std.iloc[-1], 2) if len(rolling_std) > 0 and pd.notna(rolling_std.iloc[-1]) else None

    return SummaryStats(
        latest_price=latest_price,
        latest_volume=latest_volume,
        wow_price_pct=wow_price_pct,
        wow_volume_pct=wow_volume_pct,
        mom_price_pct=mom_price_pct,
        volatility_14d=volatility_14d,
        data_points=data_points,
        missing_rate=missing_rate
    ).model_dump()


def detect_anomalies(series: List[Dict], threshold: float = 2.0) -> List[Dict]:
    """
    이상치/급등락 구간 감지

    Args:
        series: 시계열 데이터
        threshold: 표준편차 배수 기준

    Returns:
        이상치 포인트 리스트
    """
    if len(series) < 5:
        return []

    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    anomalies = []

    # 가격 기준 이상치
    price_series = df["price"].dropna()
    if len(price_series) >= 5:
        mean_price = price_series.mean()
        std_price = price_series.std()

        if std_price > 0:
            for idx, row in df.iterrows():
                if pd.notna(row["price"]):
                    z_score = abs(row["price"] - mean_price) / std_price
                    if z_score > threshold:
                        direction = "급등" if row["price"] > mean_price else "급락"
                        anomalies.append({
                            "date": row["date"].strftime("%Y-%m-%d"),
                            "type": direction,
                            "price": round(row["price"], 2),
                            "z_score": round(z_score, 2)
                        })

    return anomalies


def get_top_markets_by_metric(
    filters: Dict,
    metric: str = "price",
    ascending: bool = False,
    top_n: int = 5
) -> List[Dict]:
    """
    특정 지표 기준 상위 시장 추출

    Args:
        filters: 필터 정보
        metric: "price" | "volume" | "change"
        ascending: 오름차순 정렬 여부
        top_n: 상위 N개

    Returns:
        시장별 지표 리스트
    """
    from .data_loader import load_data
    from .query import apply_filters

    df = load_data()
    filtered, _ = apply_filters(df, filters)

    if len(filtered) == 0:
        return []

    if metric == "price":
        market_stats = filtered.groupby("market_name").agg({
            "price_kg": "mean",
            "volume_kg": "sum"
        }).reset_index()
        market_stats = market_stats.sort_values("price_kg", ascending=ascending)

    elif metric == "volume":
        market_stats = filtered.groupby("market_name").agg({
            "price_kg": "mean",
            "volume_kg": "sum"
        }).reset_index()
        market_stats = market_stats.sort_values("volume_kg", ascending=ascending)

    elif metric == "change":
        # 기간 초/말 가격 변화율
        market_changes = []
        for market in filtered["market_name"].unique():
            market_data = filtered[filtered["market_name"] == market].sort_values("date")
            if len(market_data) >= 2:
                first_price = market_data.iloc[0]["price_kg"]
                last_price = market_data.iloc[-1]["price_kg"]
                if first_price and first_price > 0:
                    change_pct = ((last_price - first_price) / first_price) * 100
                    market_changes.append({
                        "market_name": market,
                        "price_change_pct": round(change_pct, 2),
                        "first_price": round(first_price, 2),
                        "last_price": round(last_price, 2)
                    })

        market_changes.sort(key=lambda x: x["price_change_pct"], reverse=not ascending)
        return market_changes[:top_n]

    else:
        return []

    result = []
    for _, row in market_stats.head(top_n).iterrows():
        result.append({
            "market_name": row["market_name"],
            "avg_price": round(row["price_kg"], 2) if pd.notna(row["price_kg"]) else None,
            "total_volume": round(row["volume_kg"], 2) if pd.notna(row["volume_kg"]) else None
        })

    return result


def enrich_summary_with_context(summary: Dict, filters: Dict, series: List[Dict]) -> Dict:
    """
    summary에 추가 컨텍스트 정보 추가

    Args:
        summary: 기본 요약 통계
        filters: 필터 정보
        series: 시계열 데이터

    Returns:
        확장된 summary
    """
    enriched = summary.copy()

    # 이상치 정보
    anomalies = detect_anomalies(series)
    if anomalies:
        enriched["anomaly_count"] = len(anomalies)
        enriched["anomalies"] = anomalies[:3]  # 상위 3개만

    # 추세 방향
    if len(series) >= 2:
        first_price = series[0].get("price")
        last_price = series[-1].get("price")
        if first_price and last_price:
            if last_price > first_price * 1.05:
                enriched["trend_direction"] = "상승"
            elif last_price < first_price * 0.95:
                enriched["trend_direction"] = "하락"
            else:
                enriched["trend_direction"] = "보합"

    return enriched
