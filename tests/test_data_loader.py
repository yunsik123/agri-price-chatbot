"""
데이터 로더 테스트
"""
import pytest
from src.data_loader import (
    parse_period_raw,
    load_data,
    get_dim_dict,
    find_best_match,
    validate_and_correct_filter,
    get_data_date_range,
    get_default_date_range
)


class TestParsePeriodRaw:
    """시점 파싱 테스트"""

    def test_parse_upper(self):
        """상순 파싱"""
        start, end, repr_date = parse_period_raw("201801상순")
        assert start == "2018-01-01"
        assert end == "2018-01-10"
        assert repr_date == "2018-01-05"

    def test_parse_middle(self):
        """중순 파싱"""
        start, end, repr_date = parse_period_raw("201806중순")
        assert start == "2018-06-11"
        assert end == "2018-06-20"
        assert repr_date == "2018-06-15"

    def test_parse_lower(self):
        """하순 파싱"""
        start, end, repr_date = parse_period_raw("201802하순")
        assert start == "2018-02-21"
        assert end == "2018-02-28"  # 2월은 28일까지
        assert repr_date == "2018-02-25"

    def test_parse_invalid(self):
        """잘못된 형식"""
        start, end, repr_date = parse_period_raw("invalid")
        assert start is None


class TestLoadData:
    """데이터 로딩 테스트"""

    def test_load_data_success(self):
        """데이터 로딩 성공"""
        df = load_data()
        assert df is not None
        assert len(df) > 0
        assert "item_name" in df.columns
        assert "price_kg" in df.columns
        assert "date" in df.columns

    def test_column_mapping(self):
        """컬럼 매핑 확인"""
        df = load_data()
        expected_cols = ["item_name", "variety_name", "market_name", "price_kg", "volume_kg"]
        for col in expected_cols:
            assert col in df.columns

    def test_date_conversion(self):
        """날짜 변환 확인"""
        df = load_data()
        assert df["date"].dtype == "datetime64[ns]"


class TestGetDimDict:
    """dim 사전 테스트"""

    def test_dim_dict_structure(self):
        """사전 구조 확인"""
        dim_dict = get_dim_dict()
        assert "item_names" in dim_dict
        assert "variety_names" in dim_dict
        assert "market_names" in dim_dict

    def test_dim_dict_content(self):
        """사전 내용 확인"""
        dim_dict = get_dim_dict()
        assert "감자" in dim_dict["item_names"]
        assert "전국도매시장" in dim_dict["market_names"]


class TestFindBestMatch:
    """유사도 매칭 테스트"""

    def test_exact_match(self):
        """정확히 일치"""
        candidates = ["감자", "고구마", "양파"]
        best, top3 = find_best_match("감자", candidates)
        assert best == "감자"

    def test_partial_match(self):
        """부분 일치"""
        candidates = ["수미감자", "대지감자", "분감자"]
        best, top3 = find_best_match("수미", candidates)
        assert best == "수미감자"

    def test_no_match(self):
        """일치 없음"""
        candidates = ["감자", "고구마"]
        best, top3 = find_best_match("xyz123", candidates)
        # threshold 미만이면 None
        assert len(top3) == 2


class TestValidateAndCorrectFilter:
    """필터 검증/보정 테스트"""

    def test_valid_filter(self):
        """유효한 필터"""
        corrected, warnings = validate_and_correct_filter(
            item_name="감자",
            variety_name="수미",
            market_name="전국도매시장"
        )
        assert corrected["item_name"] == "감자"
        assert corrected["market_name"] == "전국도매시장"

    def test_item_correction(self):
        """품목명 보정"""
        corrected, warnings = validate_and_correct_filter(
            item_name="감자류",  # 비슷한 이름
            variety_name=None,
            market_name=None
        )
        # 보정되었거나 경고가 있어야 함
        assert corrected["item_name"] is not None
        assert corrected["market_name"] == "전국도매시장"  # 기본값


class TestDateRange:
    """날짜 범위 테스트"""

    def test_get_data_date_range(self):
        """데이터 날짜 범위"""
        date_from, date_to = get_data_date_range()
        assert date_from is not None
        assert date_to is not None
        assert date_from < date_to

    def test_get_default_date_range(self):
        """기본 날짜 범위"""
        date_from, date_to = get_default_date_range(90)
        assert date_from is not None
        assert date_to is not None
