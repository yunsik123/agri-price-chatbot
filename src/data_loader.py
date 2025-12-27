"""
데이터 로딩 모듈: CSV 로딩, 컬럼 매핑, 날짜 변환, dim 사전 구축
"""
import os
import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime, date
from functools import lru_cache
from difflib import SequenceMatcher

import pandas as pd

# ============================================================
# 컬럼 매핑: 원본 한글 → 표준 영문
# ============================================================

COLUMN_MAPPING = {
    "시점": "period_raw",
    "시장코드": "market_code",
    "시장명": "market_name",
    "품목코드": "item_code",
    "품목명": "item_name",
    "품종코드": "variety_code",
    "품종명": "variety_name",
    "총반입량(kg)": "volume_kg",
    "총거래금액(원)": "amount_krw",
    "평균가(원/kg)": "price_kg",
    "고가(20%) 평균가": "price_high_20",
    "중가(60%) 평균가": "price_mid_60",
    "중가(60%) 평균가 ": "price_mid_60",  # 공백 포함 버전
    "저가(20%) 평균가": "price_low_20",
    "중간가(원/kg)": "price_median_kg",
    "최저가(원/kg)": "price_min_kg",
    "최고가(원/kg)": "price_max_kg",
    "경매 건수": "auction_cnt",
    "전순 평균가격(원) PreVious SOON": "baseline_prev_period",
    "전달 평균가격(원) PreVious MMonth": "baseline_prev_month",
    "전년 평균가격(원) PreVious YeaR": "baseline_prev_year",
    "평년 평균가격(원) Common Year SOON": "baseline_common_year",
    "연도": "year"
}

# 전역 캐시
_data_cache: Optional[pd.DataFrame] = None
_dim_cache: Optional[Dict[str, List[str]]] = None


# ============================================================
# 날짜 변환 함수
# ============================================================

def parse_period_raw(period_raw: str) -> Tuple[str, str, str]:
    """
    '201801상순' 형태를 (date_start, date_end, date_repr) 튜플로 변환
    - 상순: 1~10일, 대표일 05
    - 중순: 11~20일, 대표일 15
    - 하순: 21~말일, 대표일 25

    Returns:
        (date_start, date_end, date_repr) 모두 YYYY-MM-DD 형식
    """
    match = re.match(r"(\d{4})(\d{2})(상순|중순|하순)", str(period_raw))
    if not match:
        # fallback: 숫자만 있으면 YYYYMM으로 처리
        match2 = re.match(r"(\d{4})(\d{2})", str(period_raw))
        if match2:
            year, month = match2.groups()
            return (f"{year}-{month}-01", f"{year}-{month}-28", f"{year}-{month}-15")
        return (None, None, None)

    year, month, period = match.groups()
    year_int, month_int = int(year), int(month)

    if period == "상순":
        start_day, end_day, repr_day = 1, 10, 5
    elif period == "중순":
        start_day, end_day, repr_day = 11, 20, 15
    else:  # 하순
        start_day = 21
        # 말일 계산
        if month_int == 12:
            next_month = date(year_int + 1, 1, 1)
        else:
            next_month = date(year_int, month_int + 1, 1)
        end_day = (next_month - pd.Timedelta(days=1)).day
        repr_day = 25

    date_start = f"{year}-{month}-{start_day:02d}"
    date_end = f"{year}-{month}-{end_day:02d}"
    date_repr = f"{year}-{month}-{repr_day:02d}"

    return (date_start, date_end, date_repr)


def convert_period_column(df: pd.DataFrame) -> pd.DataFrame:
    """period_raw 컬럼을 date, date_start, date_end로 변환"""
    if "period_raw" not in df.columns:
        return df

    # 변환 적용
    parsed = df["period_raw"].apply(parse_period_raw)
    df["date_start"] = parsed.apply(lambda x: x[0])
    df["date_end"] = parsed.apply(lambda x: x[1])
    df["date"] = parsed.apply(lambda x: x[2])  # 대표일

    # date 컬럼을 datetime으로 변환 (sorting용)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    return df


# ============================================================
# 데이터 로딩
# ============================================================

def get_data_path() -> str:
    """환경변수 또는 기본 경로에서 데이터 파일 경로 반환"""
    default_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "sample_agri_prices.csv"
    )
    return os.environ.get("DATA_PATH", default_path)


def load_data(force_reload: bool = False) -> pd.DataFrame:
    """
    CSV 데이터 로딩 및 전처리
    - 컬럼 매핑
    - 날짜 변환
    - 캐싱
    """
    global _data_cache

    if _data_cache is not None and not force_reload:
        return _data_cache

    data_path = get_data_path()

    # CSV 로딩 (인코딩 자동 감지)
    for encoding in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            df = pd.read_csv(data_path, encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"파일 인코딩을 감지할 수 없습니다: {data_path}")

    # 컬럼 매핑
    df = df.rename(columns=COLUMN_MAPPING)

    # 날짜 변환
    df = convert_period_column(df)

    # 시장명 정리 (앞의 * 제거)
    if "market_name" in df.columns:
        df["market_name"] = df["market_name"].str.replace(r"^\*", "", regex=True)

    # 숫자 컬럼 타입 변환
    numeric_cols = [
        "volume_kg", "amount_krw", "price_kg",
        "price_high_20", "price_mid_60", "price_low_20",
        "price_median_kg", "price_min_kg", "price_max_kg",
        "auction_cnt", "baseline_prev_period", "baseline_prev_month",
        "baseline_prev_year", "baseline_common_year"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # date 기준 정렬
    if "date" in df.columns:
        df = df.sort_values("date").reset_index(drop=True)

    _data_cache = df
    return df


def get_dim_dict(force_reload: bool = False) -> Dict[str, List[str]]:
    """
    품목/품종/시장 사전 구축
    Returns:
        {
            "item_names": ["감자", "사과", ...],
            "variety_names": ["수미", "후지", ...],
            "market_names": ["전국도매시장", "서울강서도매시장", ...]
        }
    """
    global _dim_cache

    if _dim_cache is not None and not force_reload:
        return _dim_cache

    df = load_data(force_reload)

    _dim_cache = {
        "item_names": sorted(df["item_name"].dropna().unique().tolist()),
        "variety_names": sorted(df["variety_name"].dropna().unique().tolist()),
        "market_names": sorted(df["market_name"].dropna().unique().tolist())
    }

    return _dim_cache


# ============================================================
# 유사도 기반 매칭
# ============================================================

def string_similarity(a: str, b: str) -> float:
    """두 문자열의 유사도 (0~1)"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_best_match(query: str, candidates: List[str], threshold: float = 0.4) -> Tuple[Optional[str], List[str]]:
    """
    query와 가장 유사한 후보 찾기

    Args:
        query: 검색어
        candidates: 후보 목록
        threshold: 최소 유사도 임계값

    Returns:
        (best_match, top3_candidates)
        - best_match: 가장 유사한 값 (threshold 이상일 때만)
        - top3_candidates: 상위 3개 후보
    """
    if not query or not candidates:
        return None, []

    # 정확히 일치하는 경우
    if query in candidates:
        return query, [query]

    # 부분 문자열 매칭 (query가 후보에 포함되거나 반대)
    for candidate in candidates:
        if query in candidate or candidate in query:
            return candidate, [candidate]

    # 유사도 계산
    scores = [(candidate, string_similarity(query, candidate)) for candidate in candidates]
    scores.sort(key=lambda x: x[1], reverse=True)

    top3 = [s[0] for s in scores[:3]]
    best = scores[0] if scores else (None, 0)

    if best[1] >= threshold:
        return best[0], top3
    else:
        return None, top3


def validate_and_correct_filter(
    item_name: str,
    variety_name: Optional[str] = None,
    market_name: Optional[str] = None
) -> Tuple[Dict[str, str], List[str]]:
    """
    필터 값 검증 및 보정

    Returns:
        (corrected_values, warnings)
    """
    dim_dict = get_dim_dict()
    corrected = {}
    warnings = []

    # 품목명 검증 (필수)
    best_item, item_candidates = find_best_match(item_name, dim_dict["item_names"])
    if best_item:
        if best_item != item_name:
            warnings.append(f"품목명 '{item_name}'을 '{best_item}'(으)로 보정했습니다. 후보: {item_candidates}")
        corrected["item_name"] = best_item
    else:
        warnings.append(f"품목명 '{item_name}'을 찾을 수 없습니다. 후보: {item_candidates}")
        # fallback: 첫 번째 후보 또는 원본 유지
        corrected["item_name"] = item_candidates[0] if item_candidates else item_name

    # 품종명 검증 (선택)
    if variety_name:
        # 해당 품목의 품종만 필터링
        df = load_data()
        item_varieties = df[df["item_name"] == corrected["item_name"]]["variety_name"].dropna().unique().tolist()

        if item_varieties:
            best_variety, variety_candidates = find_best_match(variety_name, item_varieties)
            if best_variety:
                if best_variety != variety_name:
                    warnings.append(f"품종명 '{variety_name}'을 '{best_variety}'(으)로 보정했습니다.")
                corrected["variety_name"] = best_variety
            else:
                warnings.append(f"품종명 '{variety_name}'을 찾을 수 없어 전체 집계로 대체합니다. 후보: {variety_candidates}")
                corrected["variety_name"] = None
        else:
            corrected["variety_name"] = None
    else:
        corrected["variety_name"] = None

    # 시장명 검증 (선택)
    if market_name:
        best_market, market_candidates = find_best_match(market_name, dim_dict["market_names"])
        if best_market:
            if best_market != market_name:
                warnings.append(f"시장명 '{market_name}'을 '{best_market}'(으)로 보정했습니다.")
            corrected["market_name"] = best_market
        else:
            warnings.append(f"시장명 '{market_name}'을 찾을 수 없어 전국도매시장으로 대체합니다.")
            corrected["market_name"] = "전국도매시장"
    else:
        corrected["market_name"] = "전국도매시장"

    return corrected, warnings


# ============================================================
# 날짜 범위 유틸리티
# ============================================================

def get_data_date_range() -> Tuple[str, str]:
    """데이터의 날짜 범위 반환 (YYYY-MM-DD, YYYY-MM-DD)"""
    df = load_data()
    min_date = df["date"].min()
    max_date = df["date"].max()
    return (
        min_date.strftime("%Y-%m-%d") if pd.notna(min_date) else None,
        max_date.strftime("%Y-%m-%d") if pd.notna(max_date) else None
    )


def get_default_date_range(days: int = 90) -> Tuple[str, str]:
    """기본 날짜 범위 반환 (최신 날짜로부터 N일 전)"""
    df = load_data()
    max_date = df["date"].max()
    if pd.isna(max_date):
        return None, None

    date_to = max_date.strftime("%Y-%m-%d")
    date_from = (max_date - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    return date_from, date_to
