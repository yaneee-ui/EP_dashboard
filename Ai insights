"""Google Gemini API(무료)를 이용한 실적 요약/인사이트 생성 모듈.

- Streamlit secrets(GEMINI_API_KEY)에서 키를 읽어온다.
- 여러 지표를 한 번에 모아 단일 API 호출로 (전체 종합 요약 + 지표별 한줄 인사이트)를 함께 받아온다.
  (요청 횟수 절약을 위해 지표마다 API를 따로 부르지 않음)
- 결과는 st.session_state에 캐싱되어, 같은 데이터로는 재호출하지 않는다.
"""
import json
import hashlib
import streamlit as st


def get_api_key():
    """Streamlit secrets에서 Gemini API 키를 가져온다. 없으면 None."""
    try:
        return st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None


def _make_cache_key(metrics_payload: list, context_label: str) -> str:
    """동일 데이터 재호출 방지용 캐시 키."""
    raw = context_label + json.dumps(metrics_payload, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def generate_insights(metrics_payload: list, context_label: str, cache_prefix: str):
    """
    metrics_payload: [{"name": "EP UV", "value": "16,475", "prev_label":"전일비", "prev_delta": 7.5,
                        "yoy_label":"전년동요일비", "yoy_delta": -4.6}, ...]
    context_label: 어떤 화면/조건인지 설명하는 문자열 (예: "실적요약 · Total · 일별 · 26년7월19일")
    cache_prefix: session_state 캐시 키 접두어 (페이지별로 다르게 지정)

    반환: {"overall_summary": str, "metric_insights": {지표명: 한줄인사이트}} 또는 {"error": ...}
    """
    api_key = get_api_key()
    if not api_key:
        return {"error": "no_api_key"}

    cache_key = f"{cache_prefix}_{_make_cache_key(metrics_payload, context_label)}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        metrics_text = "\n".join(
            f"- {m['name']}: {m['value']} ({m.get('prev_label','전기간비')} {m.get('prev_delta', 0):+.1f}%, "
            f"{m.get('yoy_label','전년비')} {m.get('yoy_delta', 0):+.1f}%)"
            for m in metrics_payload
        )

        prompt = f"""아래는 이커머스 EP(가격비교) 채널 실적 데이터입니다. 조건: {context_label}

{metrics_text}

위 데이터를 바탕으로 다음 JSON 형식으로만 응답해주세요 (다른 텍스트 없이 JSON만):
{{
  "overall_summary": "전체 실적을 2~3문장으로 종합 요약. 잘된 점, 우려되는 점, 개선 방향을 자연스럽게 포함. 마케터가 바로 읽고 이해할 수 있는 톤으로.",
  "metric_insights": {{
    "지표명1": "그 지표에 대한 한 줄 인사이트(20자 내외, 증감 원인 추정이나 시사점)",
    "지표명2": "..."
  }}
}}
지표명은 위에 나열된 이름을 정확히 그대로 사용하세요. 수치를 과장하지 말고 객관적으로 작성하세요."""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4,
                max_output_tokens=800,
            ),
        )
        result = json.loads(response.text)
        st.session_state[cache_key] = result
        return result
    except Exception as e:
        return {"error": str(e)}


def render_overall_summary_box(result):
    """전체 종합 요약을 상단 박스로 표시."""
    if result is None:
        return
    if result.get("error") == "no_api_key":
        st.info("💡 AI 인사이트를 보려면 사이드바 안내에 따라 Gemini API 키를 등록해주세요.")
        return
    if "error" in result:
        st.warning(f"AI 인사이트 생성 실패: {result['error']}")
        return
    summary = result.get("overall_summary", "")
    if summary:
        st.markdown(
            f"<div style='background:linear-gradient(135deg,#eef2ff,#f5f3ff);border:1px solid #ddd6fe;"
            f"border-radius:10px;padding:14px 18px;margin:8px 0 16px 0;'>"
            f"<div style='font-size:0.78rem;color:#7c3aed;font-weight:700;margin-bottom:4px;'>🤖 AI 종합 인사이트</div>"
            f"<div style='font-size:0.88rem;color:#374151;line-height:1.5;'>{summary}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_metric_insight(result, metric_name):
    """특정 지표의 한줄 인사이트를 KPI 카드 아래 등에 표시."""
    if result is None or "error" in result:
        return
    insight = result.get("metric_insights", {}).get(metric_name)
    if insight:
        st.markdown(
            f"<div style='font-size:0.72rem;color:#7c3aed;margin-top:4px;padding-top:4px;"
            f"border-top:1px dashed #e5e7eb;'>🤖 {insight}</div>",
            unsafe_allow_html=True,
        )
