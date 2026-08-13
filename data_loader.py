"""데이터 로드 및 캐싱. CSV(변환본)와 XLSX(사내 원본) 둘 다 지원."""
import pandas as pd
import streamlit as st

from utils import COL_DATE, COL_BPU, COL_MATCH, COL_LOWEST, METRIC_COLS
from excel_converter import convert_excel_to_long

DEFAULT_DATA_PATH = "ep_data_long.csv"


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    df[COL_DATE] = pd.to_datetime(df[COL_DATE])
    for col in [COL_BPU, COL_MATCH, COL_LOWEST]:
        df[col] = df[col].astype("category")  # 반복 문자열 -> category로 메모리 절감
    for col in METRIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    return df.sort_values(COL_DATE).reset_index(drop=True)


@st.cache_data(ttl=3600, max_entries=5, show_spinner="데이터를 불러오는 중...")
def load_data(uploaded_file=None, file_name=None) -> pd.DataFrame:
    """
    데이터를 로드한다.
    - uploaded_file 없음: 기본 CSV(ep_data_long.csv) 사용
    - uploaded_file 이 .xlsx: 사내 원본 엑셀 -> 자동 변환
    - uploaded_file 이 .csv: 이미 변환된 long-format CSV로 간주
    file_name: 업로드 파일명(확장자 판별용). Streamlit UploadedFile은 .name 속성 사용.

    max_entries=5: 이 함수는 업로드 파일마다 별도 캐시 항목이 쌓이는데(파일이 다르면
    캐시 키도 달라짐), 계속 다른 파일을 올리면 캐시가 무한정 쌓여 메모리를 차지할 수
    있어서 최근 5개까지만 남기고 오래된 항목은 자동으로 비운다.
    """
    if uploaded_file is None:
        df = pd.read_csv(DEFAULT_DATA_PATH)
        return _finalize(df)

    name = (file_name or getattr(uploaded_file, "name", "") or "").lower()

    if name.endswith(".xlsx") or name.endswith(".xls"):
        df = convert_excel_to_long(uploaded_file)  # 사내 원본 엑셀 자동 변환
    else:
        df = pd.read_csv(uploaded_file)  # 이미 변환된 CSV

    return _finalize(df)



TRAFFIC_DATA_PATH = "ep_traffic.csv"


@st.cache_data(ttl=3600, show_spinner="트래픽 데이터를 불러오는 중...")
def load_traffic_data() -> pd.DataFrame:
    """EP실적 데이터 (트래픽/거래액/구매객수/CR/객단가) 로드.
    다른 로더(load_category_data 등)와 동일하게 문자열은 category, 숫자는 float32로
    캐스팅해서 메모리를 줄인다 — 예전엔 이 최적화가 이 로더에만 빠져 있었음."""
    df = pd.read_csv(TRAFFIC_DATA_PATH)
    df["날짜"] = pd.to_datetime(df["날짜"])
    if "BPU" in df.columns:
        df["BPU"] = df["BPU"].astype("category")
    if "회원구분" in df.columns:
        df["회원구분"] = df["회원구분"].astype("category")
    for col in ["트래픽", "거래액", "구매객수", "CR", "객단가"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    return df.sort_values("날짜").reset_index(drop=True)


CATEGORY_DATA_PATH = "ep_category.csv"
CATEGORY_DATA_PATH_GZ = "ep_category.csv.gz"


@st.cache_data(ttl=3600, show_spinner="카테고리 데이터를 불러오는 중...")
def load_category_data() -> pd.DataFrame:
    """카테고리/브랜드별 실적 데이터 로드 (전체 기간). 카테고리 레벨은 세그먼트별, 브랜드 레벨은 전체만.
    gzip 압축본(ep_category.csv.gz)이 있으면 그걸 우선 쓴다 — 카테고리×브랜드 조합이 많으면
    비압축 CSV가 25MB를 넘어 GitHub 웹 업로드 제한에 걸리기 쉬워서, 컨버터가 이제 압축본을
    만들어준다. pandas가 파일 확장자(.gz)를 보고 알아서 압축을 풀어 읽어서 read_csv 호출
    자체는 압축 여부와 무관하게 동일하다."""
    import os
    import gzip

    if os.path.exists(CATEGORY_DATA_PATH_GZ):
        _path = CATEGORY_DATA_PATH_GZ
    elif os.path.exists(CATEGORY_DATA_PATH):
        _path = CATEGORY_DATA_PATH
    else:
        return pd.DataFrame(columns=["날짜", "BPU", "카테고리", "브랜드", "회원구분", "트래픽", "거래액", "구매객수", "CR", "객단가"])

    # gzip 파일이 GitHub 업로드 과정에서 깨지는 경우가 있다(바이너리 파일을 텍스트로
    # 취급해서 줄바꿈 문자가 변환되는 등). 그래서 압축 해제를 먼저 직접 시도해보고,
    # 실패하면 '사실 압축 안 된 일반 CSV일 수도 있다'고 보고 그냥 텍스트로도 시도한다 —
    # 대시보드가 통째로 죽는 것보다는 최대한 읽어보는 게 낫다.
    if _path.endswith(".gz"):
        try:
            with gzip.open(_path, "rt", encoding="utf-8-sig") as f:
                df = pd.read_csv(f)
        except Exception:
            # gzip 손상 시 zlib.error/EOFError/UnicodeDecodeError 등 다양한 예외가 날 수
            # 있어서(테스트로 확인함), 폭넓게 잡고 '압축 안 된 일반 CSV일 수도 있다'고
            # 보고 텍스트로 재시도한다.
            try:
                df = pd.read_csv(_path, encoding="utf-8-sig")
            except Exception:
                st.error(
                    f"'{_path}' 파일을 읽을 수 없어요 — GitHub에 올릴 때 파일이 깨졌을 "
                    "가능성이 높아요(바이너리 파일이 텍스트로 잘못 변환된 경우가 흔해요). "
                    "컨버터에서 파일을 다시 받아서, 그대로(수정 없이) 업로드해보세요."
                )
                return pd.DataFrame(columns=["날짜", "BPU", "카테고리", "브랜드", "회원구분", "트래픽", "거래액", "구매객수", "CR", "객단가"])
    else:
        df = pd.read_csv(_path)

    df["날짜"] = pd.to_datetime(df["날짜"])
    _cat_cols = ["BPU", "카테고리", "브랜드"]
    if "회원구분" in df.columns:
        _cat_cols.append("회원구분")
    for col in _cat_cols:
        df[col] = df[col].astype("category")
    for col in ["트래픽", "거래액", "구매객수", "CR", "객단가"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    return df.sort_values("날짜").reset_index(drop=True)


BRAND_NAMES_PATH = "brand_names.csv"


@st.cache_data(ttl=3600, show_spinner=False)
def load_brand_names() -> dict:
    """브랜드 코드 -> 브랜드명(한글) 매핑 딕셔너리 로드."""
    import os
    if not os.path.exists(BRAND_NAMES_PATH):
        return {}
    df = pd.read_csv(BRAND_NAMES_PATH)
    return dict(zip(df["코드"], df["브랜드명"]))


# 자사/입점 합산용 BPU 그룹 (app.py의 BPU_GROUPS와 동일한 정의를 여기서도 사용)
_COUPON_BPU_GROUPS = {
    "자사": ["e-영업1", "e-영업2"],
    "입점": ["e-영업3", "e-영업4"],
}


def build_coupon_monthly(df_daily: pd.DataFrame) -> pd.DataFrame:
    """일자별 쿠폰 데이터(ep_coupon_daily.csv, e-영업1~4)에서 월별 BPU 집계
    (Total/자사/입점/e-영업1~4)를 파생한다. 예전 ep_coupon.csv를 대체."""
    if df_daily.empty:
        return pd.DataFrame(columns=["연월", "BPU", "쿠폰유형", "쿠폰할인"])
    d = df_daily.copy()
    d["연월"] = d["날짜"].dt.to_period("M").dt.to_timestamp()
    base = d.groupby(["연월", "BPU", "쿠폰유형"], as_index=False)["쿠폰할인"].sum()
    parts = [base]
    for label, members in _COUPON_BPU_GROUPS.items():
        sub = base[base["BPU"].isin(members)].groupby(["연월", "쿠폰유형"], as_index=False)["쿠폰할인"].sum()
        sub["BPU"] = label
        parts.append(sub)
    total = base.groupby(["연월", "쿠폰유형"], as_index=False)["쿠폰할인"].sum()
    total["BPU"] = "Total"
    parts.append(total)
    result = pd.concat(parts, ignore_index=True)
    return result.sort_values(["연월", "쿠폰유형", "BPU"]).reset_index(drop=True)


def build_coupon_monthly_detail(df_daily: pd.DataFrame) -> pd.DataFrame:
    """일자별 쿠폰 데이터에서 월별 쿠폰명별 상세(e-영업1~4)를 파생한다.
    예전 ep_coupon_detail.csv를 대체 (Total/자사/입점은 화면에서 BPU_GROUPS로 즉석 합산)."""
    if df_daily.empty:
        return pd.DataFrame(columns=["연월", "BPU", "쿠폰명", "쿠폰ID", "쿠폰유형", "쿠폰할인"])
    d = df_daily.copy()
    d["연월"] = d["날짜"].dt.to_period("M").dt.to_timestamp()
    result = d.groupby(["연월", "BPU", "쿠폰ID", "쿠폰명", "쿠폰유형"], as_index=False)["쿠폰할인"].sum()
    return result.sort_values(["연월", "쿠폰유형", "쿠폰할인"], ascending=[True, True, False]).reset_index(drop=True)


COUPON_DAILY_PATH = "ep_coupon_daily.csv"


@st.cache_data(ttl=3600, show_spinner=False)
def load_coupon_daily() -> pd.DataFrame:
    """쿠폰명별 일자별 상세 할인 데이터 로드 (있으면 일/주별 조회 가능).
    문자열은 category, 금액은 float32로 캐스팅해서 메모리를 줄인다."""
    import os
    if not os.path.exists(COUPON_DAILY_PATH):
        return pd.DataFrame(columns=["날짜", "BPU", "쿠폰ID", "쿠폰명", "쿠폰유형", "쿠폰할인"])
    df = pd.read_csv(COUPON_DAILY_PATH)
    df["날짜"] = pd.to_datetime(df["날짜"])
    for col in ["BPU", "쿠폰ID", "쿠폰명", "쿠폰유형"]:
        if col in df.columns:
            df[col] = df[col].astype("category")
    df["쿠폰할인"] = pd.to_numeric(df["쿠폰할인"], errors="coerce").astype("float32")
    return df.sort_values("날짜").reset_index(drop=True)
