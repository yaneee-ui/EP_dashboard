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
TRAFFIC_DATA_PATH_FIXED = "ep_traffic_2025.csv"


def _read_traffic_csv(path):
    df = pd.read_csv(path)
    df["날짜"] = pd.to_datetime(df["날짜"])
    return df


@st.cache_data(ttl=3600, show_spinner="트래픽 데이터를 불러오는 중...")
def load_traffic_data() -> pd.DataFrame:
    """EP실적 데이터 (트래픽/거래액/구매객수/CR/객단가) 로드.
    다른 로더(load_category_data 등)와 동일하게 문자열은 category, 숫자는 float32로
    캐스팅해서 메모리를 줄인다 — 예전엔 이 최적화가 이 로더에만 빠져 있었음.

    25년 데이터는 더 이상 바뀌지 않는 '고정' 값이라, 매번 변환·업로드할 때마다
    같이 넣지 않아도 되도록 두 파일로 나눠서 관리한다:
      - ep_traffic_2025.csv (고정 아카이브, 한 번만 올려두면 됨 — 있으면만 사용)
      - ep_traffic.csv (계속 갱신하는 최신 데이터 — 26년만 있어도 되고, 예전처럼
        전체 기간을 다 담고 있어도 됨)
    두 파일을 합칠 때 날짜+BPU+회원구분이 겹치면(예: ep_traffic.csv에 실수로 25년
    데이터가 같이 들어있는 경우) 최신 파일(ep_traffic.csv) 쪽 값을 우선한다."""
    import os

    frames = []
    if os.path.exists(TRAFFIC_DATA_PATH_FIXED):
        frames.append(_read_traffic_csv(TRAFFIC_DATA_PATH_FIXED))
    if os.path.exists(TRAFFIC_DATA_PATH):
        frames.append(_read_traffic_csv(TRAFFIC_DATA_PATH))

    if not frames:
        return pd.DataFrame(columns=["날짜", "BPU", "회원구분", "CR", "객단가", "거래액", "구매객수", "트래픽"])

    df = pd.concat(frames, ignore_index=True)
    _dedup_keys = [c for c in ["날짜", "BPU", "회원구분"] if c in df.columns]
    if _dedup_keys:
        # 마지막(= ep_traffic.csv, 최신 갱신본)에 나온 값이 우선하도록 keep="last"
        df = df.drop_duplicates(subset=_dedup_keys, keep="last")

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
CATEGORY_DATA_PATH_FIXED = "ep_category_2025.csv"
CATEGORY_DATA_PATH_FIXED_GZ = "ep_category_2025.csv.gz"

_CATEGORY_EMPTY_COLS = ["날짜", "BPU", "카테고리", "브랜드", "회원구분", "트래픽", "거래액", "구매객수", "CR", "객단가"]


def _read_category_csv_file(path):
    """gz든 아니든 안전하게 읽는다 (깨진 gzip이면 일반 텍스트로 폴백).
    실패하면 None을 반환(호출부에서 에러 메시지 표시 여부를 결정)."""
    import gzip

    if path.endswith(".gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8-sig") as f:
                return pd.read_csv(f)
        except Exception:
            # gzip 손상 시 zlib.error/EOFError/UnicodeDecodeError 등 다양한 예외가 날 수
            # 있어서(테스트로 확인함), 폭넓게 잡고 '압축 안 된 일반 CSV일 수도 있다'고
            # 보고 텍스트로 재시도한다.
            try:
                return pd.read_csv(path, encoding="utf-8-sig")
            except Exception:
                return None
    return pd.read_csv(path)


@st.cache_data(ttl=3600, show_spinner="카테고리 데이터를 불러오는 중...")
def load_category_data() -> pd.DataFrame:
    """카테고리/브랜드별 실적 데이터 로드 (전체 기간). 카테고리 레벨은 세그먼트별, 브랜드 레벨은 전체만.
    gzip 압축본(.csv.gz)이 있으면 그걸 우선 쓴다 — 카테고리×브랜드 조합이 많으면 비압축
    CSV가 25MB를 넘어 GitHub 웹 업로드 제한에 걸리기 쉬워서, 컨버터가 이제 압축본을
    만들어준다.

    25년 데이터는 더 이상 바뀌지 않는 '고정' 값이라, 매번 변환·업로드할 때마다 같이
    넣지 않아도 되도록 두 파일로 나눠서 관리한다:
      - ep_category_2025.csv(.gz) (고정 아카이브, 한 번만 올려두면 됨 — 있으면만 사용)
      - ep_category.csv(.gz) (계속 갱신하는 최신 데이터 — 26년만 있어도 되고, 예전처럼
        전체 기간을 다 담고 있어도 됨)
    두 파일을 합칠 때 날짜+BPU+카테고리+브랜드+회원구분이 겹치면(예: 최신 파일에 실수로
    25년 데이터가 같이 들어있는 경우) 최신 파일 쪽 값을 우선한다."""
    import os

    def _pick_path(gz_path, plain_path):
        if os.path.exists(gz_path):
            return gz_path
        if os.path.exists(plain_path):
            return plain_path
        return None

    _fixed_path = _pick_path(CATEGORY_DATA_PATH_FIXED_GZ, CATEGORY_DATA_PATH_FIXED)
    _current_path = _pick_path(CATEGORY_DATA_PATH_GZ, CATEGORY_DATA_PATH)

    frames = []
    _read_failed_path = None
    for _p in [_fixed_path, _current_path]:
        if _p is None:
            continue
        _df = _read_category_csv_file(_p)
        if _df is None:
            _read_failed_path = _p
            continue
        frames.append(_df)

    if _read_failed_path is not None and not frames:
        st.error(
            f"'{_read_failed_path}' 파일을 읽을 수 없어요 — GitHub에 올릴 때 파일이 깨졌을 "
            "가능성이 높아요(바이너리 파일이 텍스트로 잘못 변환된 경우가 흔해요). "
            "컨버터에서 파일을 다시 받아서, 그대로(수정 없이) 업로드해보세요."
        )
        return pd.DataFrame(columns=_CATEGORY_EMPTY_COLS)
    elif _read_failed_path is not None:
        st.warning(f"'{_read_failed_path}' 파일은 못 읽었지만, 나머지 파일로 계속 진행할게요.")

    if not frames:
        return pd.DataFrame(columns=_CATEGORY_EMPTY_COLS)

    df = pd.concat(frames, ignore_index=True)
    df["날짜"] = pd.to_datetime(df["날짜"])
    _dedup_keys = [c for c in ["날짜", "BPU", "카테고리", "브랜드", "회원구분"] if c in df.columns]
    if _dedup_keys and len(frames) > 1:
        # 마지막(=현재 파일, 최신 갱신본)에 나온 값이 우선하도록 keep="last"
        df = df.drop_duplicates(subset=_dedup_keys, keep="last")

    _cat_cols = ["BPU", "카테고리", "브랜드"]
    if "회원구분" in df.columns:
        _cat_cols.append("회원구분")
    for col in _cat_cols:
        df[col] = df[col].astype("category")
    for col in ["트래픽", "거래액", "구매객수", "CR", "객단가"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
    return df.sort_values("날짜").reset_index(drop=True)


PRODUCT_DATA_PATH = "ep_product.csv"
PRODUCT_DATA_PATH_GZ = "ep_product.csv.gz"

_PRODUCT_EMPTY_COLS = ["날짜", "BPU", "카테고리", "브랜드", "상품코드", "상품명", "거래액"]


@st.cache_data(ttl=3600, show_spinner="상품 데이터를 불러오는 중...")
def load_product_data() -> pd.DataFrame:
    """상품(SKU) 단위 거래액 데이터 로드 — 카테고리별 상위 상품 랭킹에 사용.
    gzip 압축본(.csv.gz)이 있으면 그걸 우선 쓴다 (상품 단위는 행이 훨씬 많아서
    카테고리 데이터처럼 비압축 CSV가 커지기 쉬움). 파일이 없으면 빈 DataFrame 반환."""
    import os

    path = PRODUCT_DATA_PATH_GZ if os.path.exists(PRODUCT_DATA_PATH_GZ) else PRODUCT_DATA_PATH
    if not os.path.exists(path):
        return pd.DataFrame(columns=_PRODUCT_EMPTY_COLS)

    df = _read_category_csv_file(path)  # gz/일반 CSV 안전 읽기 (카테고리 로더와 로직 공유)
    if df is None:
        st.error(f"'{path}' 파일을 읽을 수 없어요. 컨버터에서 다시 받아서 그대로(수정 없이) 업로드해보세요.")
        return pd.DataFrame(columns=_PRODUCT_EMPTY_COLS)

    df["날짜"] = pd.to_datetime(df["날짜"])
    for col in ["BPU", "카테고리", "브랜드", "상품코드", "상품명"]:
        if col in df.columns:
            df[col] = df[col].astype("category")
    df["거래액"] = pd.to_numeric(df["거래액"], errors="coerce").astype("float32")
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
