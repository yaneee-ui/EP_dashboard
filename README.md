# 📊 마케팅 실적 현황 대시보드

BPU(사업부) × 원부매칭여부 × 최저가여부로 필터링하는 EP 실적 대시보드.

## 데이터 갱신 방법 (중요)
사내에서 받은 **Data.xlsx를 그대로** 앱 우측 상단 "데이터 업로드"에 올리면
자동으로 변환되어 대시보드에 반영됩니다. 별도 변환 작업이 필요 없습니다.

- 지원 형식: .xlsx (사내 원본), .csv (이미 변환된 long-format)
- 기본 표시 데이터: ep_data_long.csv (2025-01-01 ~ 2026-07-08)

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 파일 구성 (flat 구조)
- app.py : 메인
- data_loader.py : 데이터 로드 (xlsx 자동 변환 포함)
- excel_converter.py : Data.xlsx -> long-format 변환 로직
- filters.py / kpi.py / charts.py / comparison_table.py / utils.py / styles.py
- ep_data_long.csv : 기본 데이터
- convert_long.py : (선택) 터미널에서 수동 변환용 스크립트

## 주요 기능
- 상단 필터바: BPU / 원부매칭여부 / 최저가여부 + 일·주·월 토글 + 데이터 업로드
- KPI 카드 7개: 총결제·순결제 등, 각각 전일비/전주평균비/전년동일비
- 지표 추이: 2026년 메인선 + 2025년 전년 비교선(실제 날짜 매칭)
- 사업부별 추이 비교 / 사업부별 실적 비교 테이블
