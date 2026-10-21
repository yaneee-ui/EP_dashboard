"""변환기(convert_*.py) 공용 — 새로 올린 원본 파일이 '정상'인지 저장 전에 검사한다.

2026-10-21에 카테고리·브랜드 상세 없이 '전체' 행만 들어 있는 상세실적 파일이 올라와서, 그대로
변환하면 기존 24만 행이 통째로 사라질 뻔했다. 같은 일을 막으려고, 새로 만든 데이터가 이미 저장된
출력 파일보다 눈에 띄게 빈약하면 저장하지 않고 경고를 띄운 채 종료한다(종료 코드 2).
정말 의도한 변경이면 `python convert_xxx.py --force`로 건너뛴다.
"""
import sys

import pandas as pd


def guard(name, out_path, new_df, dims=(), date_col="날짜", min_row_ratio=0.9, min_dim_ratio=0.8, check_last_date=True):
    """new_df(이번에 원본에서 만든 데이터)를 out_path(이미 저장된 파일)와 비교해서
    다음 중 하나라도 해당하면 경고 후 종료:
      - 새 데이터의 마지막 날짜가 기존보다 이전
      - 같은 날짜들에서 행 수가 기존의 min_row_ratio 미만
      - dims 컬럼(예: 카테고리/브랜드/BPU)의 종류 수가 기존의 min_dim_ratio 미만"""
    if "--force" in sys.argv:
        return
    try:
        old = pd.read_csv(out_path, parse_dates=[date_col])
    except Exception:
        return  # 기존 파일이 없거나 못 읽으면 비교할 게 없다
    if old.empty or new_df.empty:
        if new_df.empty:
            abort(name, ["새 데이터가 비어 있어요."])
        return

    problems = []
    # 기존 날짜를 보존하며 병합하는 변환기(쿠폰/전체실적/EP채널)는 일부 기간만 담긴 파일도 정상이라 생략
    if check_last_date and new_df[date_col].max() < old[date_col].max():
        problems.append(
            f"마지막 날짜가 기존({old[date_col].max():%Y-%m-%d})보다 이전({new_df[date_col].max():%Y-%m-%d})이에요."
        )

    old_same = old[old[date_col].isin(set(new_df[date_col].unique()))]
    if len(old_same) and len(new_df[new_df[date_col] <= old[date_col].max()]) < min_row_ratio * len(old_same):
        problems.append(
            f"같은 날짜 기준 행 수가 기존 {len(old_same):,}행 → 새 파일 "
            f"{len(new_df[new_df[date_col] <= old[date_col].max()]):,}행으로 크게 줄었어요."
        )

    for c in dims:
        if c in old.columns and c in new_df.columns:
            o, n = old_same[c].nunique(), new_df[c].nunique()
            if o >= 3 and n < min_dim_ratio * o:
                problems.append(f"'{c}' 종류가 기존 {o}개 → 새 파일 {n}개로 줄었어요.")

    if problems:
        abort(name, problems)


def abort(name, problems):
    bar = "=" * 64
    print(f"\n{bar}\n⚠️  [{name}] 올라온 원본 파일이 정상이 아닌 것 같아요 — 저장하지 않고 중단했어요.\n{bar}")
    for p in problems:
        print(f"  - {p}")
    print("  기존 파일은 그대로예요. 원본을 다시 내려받아 올려주세요.")
    print("  (정말 의도한 변경이면 이 변환기를 `--force` 옵션과 함께 다시 실행하세요.)\n")
    sys.exit(2)
