"""
쿼리 모듈: 필터 → 데이터프레임 필터링/집계
- chart_type별 처리
- intent별 처리 (high_avg_price, high_price_change, high_volatility)
- granularity별 집계
"""
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from .data_loader import load_data
from .schema import FilterRequest, SeriesPoint


# ============================================================
# 필터 적용
# ============================================================

def apply_filters(df: pd.DataFrame, filters: Dict) -> Tuple[pd.DataFrame, List[str]]:
    """
    필터를 데이터프레임에 적용

    Args:
        df: 원본 데이터프레임
        filters: FilterRequest dict

    Returns:
        (filtered_df, warnings)
    """
    warnings = []
    result = df.copy()

    # 품목명 필터 (필수)
    item_name = filters.get("item_name")
    if item_name:
        result = result[result["item_name"] == item_name]
        if len(result) == 0:
            warnings.append(f"품목 '{item_name}'에 해당하는 데이터가 없습니다.")
            return result, warnings

    # 품종명 필터 (선택)
    variety_name = filters.get("variety_name")
    if variety_name:
        result = result[result["variety_name"] == variety_name]
        if len(result) == 0:
            warnings.append(f"품종 '{variety_name}'에 해당하는 데이터가 없어 전체로 대체합니다.")
            result = df[df["item_name"] == item_name]

    # 시장명 필터 (선택)
    market_name = filters.get("market_name")
    chart_type = filters.get("chart_type", "trend")

    # compare_markets가 아닌 경우에만 시장 필터 적용
    if market_name and chart_type != "compare_markets":
        result = result[result["market_name"] == market_name]
        if len(result) == 0:
            warnings.append(f"시장 '{market_name}'에 해당하는 데이터가 없어 전국도매시장으로 대체합니다.")
            result = df[df["item_name"] == item_name]
            if variety_name:
                result = result[result["variety_name"] == variety_name]

    # 날짜 범위 필터
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")

    if date_from:
        date_from_dt = pd.to_datetime(date_from)
        result = result[result["date"] >= date_from_dt]

    if date_to:
        date_to_dt = pd.to_datetime(date_to)
        result = result[result["date"] <= date_to_dt]

    if len(result) == 0:
        warnings.append("지정된 기간에 해당하는 데이터가 없습니다.")

    return result, warnings


# ============================================================
# 집계 함수
# ============================================================

def aggregate_by_granularity(
    df: pd.DataFrame,
    granularity: str = "weekly",
    group_by_market: bool = False
) -> pd.DataFrame:
    """
    granularity에 따른 집계

    Args:
        df: 필터링된 데이터프레임
        granularity: "daily" | "weekly"
        group_by_market: 시장별로 그룹화할지 여부

    Returns:
        집계된 데이터프레임
    """
    if len(df) == 0:
        return df

    df = df.copy()

    # 주간 집계를 위한 주차 컬럼 생성
    if granularity == "weekly":
        df["week"] = df["date"].dt.to_period("W").apply(lambda x: x.start_time)
        group_col = "week"
    else:
        # daily: 데이터가 순(旬) 단위이므로 대표일 기준
        group_col = "date"

    # 그룹 키 설정
    if group_by_market:
        group_keys = [group_col, "market_name"]
    else:
        group_keys = [group_col]

    # 집계
    agg_funcs = {
        "price_kg": "mean",
        "volume_kg": "sum",
        "amount_krw": "sum"
    }

    # 존재하는 컬럼만 집계
    agg_funcs = {k: v for k, v in agg_funcs.items() if k in df.columns}

    result = df.groupby(group_keys, as_index=False).agg(agg_funcs)

    # date 컬럼 정리
    if granularity == "weekly":
        result = result.rename(columns={"week": "date"})

    result = result.sort_values("date").reset_index(drop=True)
    return result


# ============================================================
# chart_type별 처리
# ============================================================

def query_trend(df: pd.DataFrame, filters: Dict) -> Tuple[List[Dict], List[str]]:
    """
    trend 차트: 시계열 가격/반입량 추세
    """
    warnings = []
    filtered, filter_warnings = apply_filters(df, filters)
    warnings.extend(filter_warnings)

    if len(filtered) == 0:
        return [], warnings

    granularity = filters.get("granularity", "weekly")
    aggregated = aggregate_by_granularity(filtered, granularity, group_by_market=False)

    series = []
    for _, row in aggregated.iterrows():
        point = {
            "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else None,
            "price": round(row["price_kg"], 2) if pd.notna(row.get("price_kg")) else None,
            "volume": round(row["volume_kg"], 2) if pd.notna(row.get("volume_kg")) else None,
            "market_name": None
        }
        series.append(point)

    return series, warnings


def query_compare_markets(df: pd.DataFrame, filters: Dict) -> Tuple[List[Dict], List[str]]:
    """
    compare_markets 차트: 시장별 비교
    """
    warnings = []
    filtered, filter_warnings = apply_filters(df, filters)
    warnings.extend(filter_warnings)

    if len(filtered) == 0:
        return [], warnings

    top_n = filters.get("top_n_markets", 5)
    granularity = filters.get("granularity", "weekly")

    # 상위 N개 시장 선정 (거래금액 기준)
    market_totals = filtered.groupby("market_name")["amount_krw"].sum().sort_values(ascending=False)
    top_markets = market_totals.head(top_n).index.tolist()

    if len(top_markets) == 0:
        warnings.append("비교할 시장이 없습니다.")
        return [], warnings

    filtered = filtered[filtered["market_name"].isin(top_markets)]
    aggregated = aggregate_by_granularity(filtered, granularity, group_by_market=True)

    series = []
    for _, row in aggregated.iterrows():
        point = {
            "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else None,
            "price": round(row["price_kg"], 2) if pd.notna(row.get("price_kg")) else None,
            "volume": round(row["volume_kg"], 2) if pd.notna(row.get("volume_kg")) else None,
            "market_name": row["market_name"]
        }
        series.append(point)

    return series, warnings


def query_volume_price(df: pd.DataFrame, filters: Dict) -> Tuple[List[Dict], List[str]]:
    """
    volume_price 차트: 가격과 반입량 함께 표시 (trend와 동일 데이터, UI에서 다르게 렌더링)
    """
    return query_trend(df, filters)


def query_volatility(df: pd.DataFrame, filters: Dict) -> Tuple[List[Dict], List[str]]:
    """
    volatility 차트: 변동성 시계열
    """
    warnings = []
    filtered, filter_warnings = apply_filters(df, filters)
    warnings.extend(filter_warnings)

    if len(filtered) == 0:
        return [], warnings

    granularity = filters.get("granularity", "weekly")
    aggregated = aggregate_by_granularity(filtered, granularity, group_by_market=False)

    # rolling std 계산 (4주 = 약 4포인트)
    window = 4 if granularity == "weekly" else 14
    if len(aggregated) >= window:
        aggregated["volatility"] = aggregated["price_kg"].rolling(window=window, min_periods=2).std()
    else:
        aggregated["volatility"] = aggregated["price_kg"].std()
        warnings.append(f"데이터가 부족하여 전체 기간 변동성을 계산했습니다.")

    series = []
    for _, row in aggregated.iterrows():
        point = {
            "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else None,
            "price": round(row["price_kg"], 2) if pd.notna(row.get("price_kg")) else None,
            "volume": round(row["volume_kg"], 2) if pd.notna(row.get("volume_kg")) else None,
            "market_name": None,
            "volatility": round(row["volatility"], 2) if pd.notna(row.get("volatility")) else None
        }
        series.append(point)

    return series, warnings


# ============================================================
# intent별 처리
# ============================================================

def query_high_avg_price(df: pd.DataFrame, filters: Dict) -> Tuple[List[Dict], List[str]]:
    """
    high_avg_price: 평균가격이 높은 시장 Top-N
    """
    warnings = []
    filtered, filter_warnings = apply_filters(df, filters)
    warnings.extend(filter_warnings)

    if len(filtered) == 0:
        return [], warnings

    # chart_type을 compare_markets로 자동 보정
    filters["chart_type"] = "compare_markets"
    warnings.append("'비싼' 분석을 위해 시장별 비교 차트로 표시합니다.")

    # 시장별 평균가격 기준으로 top_n 선정
    top_n = filters.get("top_n_markets", 5)
    market_avg = filtered.groupby("market_name")["price_kg"].mean().sort_values(ascending=False)
    top_markets = market_avg.head(top_n).index.tolist()

    if len(top_markets) == 0:
        return [], warnings

    filtered = df[
        (df["item_name"] == filters.get("item_name")) &
        (df["market_name"].isin(top_markets))
    ]

    # 날짜 필터 재적용
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from:
        filtered = filtered[filtered["date"] >= pd.to_datetime(date_from)]
    if date_to:
        filtered = filtered[filtered["date"] <= pd.to_datetime(date_to)]

    granularity = filters.get("granularity", "weekly")
    aggregated = aggregate_by_granularity(filtered, granularity, group_by_market=True)

    series = []
    for _, row in aggregated.iterrows():
        point = {
            "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else None,
            "price": round(row["price_kg"], 2) if pd.notna(row.get("price_kg")) else None,
            "volume": round(row["volume_kg"], 2) if pd.notna(row.get("volume_kg")) else None,
            "market_name": row["market_name"]
        }
        series.append(point)

    return series, warnings


def query_high_price_change(df: pd.DataFrame, filters: Dict) -> Tuple[List[Dict], List[str]]:
    """
    high_price_change: 가격 상승률이 큰 시장/구간
    """
    warnings = []
    filtered, filter_warnings = apply_filters(df, filters)
    warnings.extend(filter_warnings)

    if len(filtered) == 0:
        return [], warnings

    # 시장별 기간 초/말 가격 비교
    granularity = filters.get("granularity", "weekly")
    aggregated = aggregate_by_granularity(filtered, granularity, group_by_market=True)

    if len(aggregated) == 0:
        return [], warnings

    # 시장별 상승률 계산
    market_changes = []
    for market in aggregated["market_name"].unique():
        market_data = aggregated[aggregated["market_name"] == market].sort_values("date")
        if len(market_data) >= 2:
            first_price = market_data.iloc[0]["price_kg"]
            last_price = market_data.iloc[-1]["price_kg"]
            if first_price and first_price > 0:
                change_pct = ((last_price - first_price) / first_price) * 100
                market_changes.append((market, change_pct))

    # 상승률 기준 정렬
    market_changes.sort(key=lambda x: x[1], reverse=True)
    top_n = filters.get("top_n_markets", 5)
    top_markets = [m[0] for m in market_changes[:top_n]]

    if len(top_markets) == 0:
        warnings.append("상승률을 계산할 수 있는 시장이 없습니다.")
        return query_trend(df, filters)

    filtered = aggregated[aggregated["market_name"].isin(top_markets)]
    warnings.append("가격 상승률이 높은 시장을 표시합니다.")

    series = []
    for _, row in filtered.iterrows():
        point = {
            "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else None,
            "price": round(row["price_kg"], 2) if pd.notna(row.get("price_kg")) else None,
            "volume": round(row["volume_kg"], 2) if pd.notna(row.get("volume_kg")) else None,
            "market_name": row["market_name"]
        }
        series.append(point)

    return series, warnings


def query_high_volatility(df: pd.DataFrame, filters: Dict) -> Tuple[List[Dict], List[str]]:
    """
    high_volatility: 변동성이 큰 구간/시장
    """
    warnings = []
    filters["chart_type"] = "volatility"
    warnings.append("변동성 분석 차트로 표시합니다.")
    return query_volatility(df, filters)


# ============================================================
# 메인 쿼리 함수
# ============================================================

def execute_query(filters: Dict) -> Tuple[List[Dict], List[str]]:
    """
    필터에 따라 데이터 조회/집계 실행

    Args:
        filters: FilterRequest dict

    Returns:
        (series, warnings)
    """
    df = load_data()
    warnings = []

    # intent에 따른 처리
    intent = filters.get("intent", "normal")

    if intent == "high_avg_price":
        return query_high_avg_price(df, filters)
    elif intent == "high_price_change":
        return query_high_price_change(df, filters)
    elif intent == "high_volatility":
        return query_high_volatility(df, filters)

    # chart_type에 따른 처리
    chart_type = filters.get("chart_type", "trend")

    if chart_type == "trend":
        return query_trend(df, filters)
    elif chart_type == "compare_markets":
        return query_compare_markets(df, filters)
    elif chart_type == "volume_price":
        return query_volume_price(df, filters)
    elif chart_type == "volatility":
        return query_volatility(df, filters)
    else:
        warnings.append(f"알 수 없는 chart_type: {chart_type}, trend로 대체합니다.")
        return query_trend(df, filters)


def get_filtered_dataframe(filters: Dict) -> pd.DataFrame:
    """
    필터 적용된 원본 데이터프레임 반환 (features 계산용)
    """
    df = load_data()
    filtered, _ = apply_filters(df, filters)
    granularity = filters.get("granularity", "weekly")
    return aggregate_by_granularity(filtered, granularity, group_by_market=False)
