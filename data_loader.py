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


@st.cache_data(ttl=3600, show_spinner="데이터를 불러오는 중...")
def load_data(uploaded_file=None, file_name=None) -> pd.DataFrame:
    """
    데이터를 로드한다.
    - uploaded_file 없음: 기본 CSV(ep_data_long.csv) 사용
    - uploaded_file 이 .xlsx: 사내 원본 엑셀 -> 자동 변환
    - uploaded_file 이 .csv: 이미 변환된 long-format CSV로 간주
    file_name: 업로드 파일명(확장자 판별용). Streamlit UploadedFile은 .name 속성 사용.
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

