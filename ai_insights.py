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


def _pick_available_models(client):
    """API에서 실제 사용 가능한 모델 목록을 조회해, generateContent 지원 모델을 우선순위대로 반환.
    (모델 세대가 바뀌어도 코드 수정 없이 동작하도록 하드코딩 대신 동적 조회)"""
    try:
        candidates = []
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" not in actions:
                continue
            name = (m.name or "").replace("models/", "")
            if not name:
                continue
            lower = name.lower()
            # 이미지/임베딩/TTS 등 텍스트 생성용이 아닌 모델 제외
            if any(k in lower for k in ("embedding", "imagen", "image", "tts", "veo", "aqa", "learnlm")):
                continue
            # 무료 티어 친화적인 순서로 점수화 (flash-lite > flash > 그 외, 최신 세대 우선)
            score = 0
            if "flash-lite" in lower:
                score += 100
            elif "flash" in lower:
                score += 90
            elif "pro" in lower:
                score += 10
            if "preview" in lower or "exp" in lower:
                score -= 5  # 안정 버전 우선
            # 버전 숫자가 클수록(최신) 가산점
            import re as _re
            ver = _re.search(r"(\d+(?:\.\d+)?)", name)
            if ver:
                try:
                    score += float(ver.group(1)) * 2
                except Exception:
                    pass
            candidates.append((score, name))
        candidates.sort(key=lambda x: -x[0])
        return [n for _, n in candidates[:6]]
    except Exception:
        # 조회 실패 시 fallback 후보군
        return ["gemini-3-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"]


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

        response = None
        _tried_errors = []
        _models_to_try = _pick_available_models(client)
        if not _models_to_try:
            raise RuntimeError("사용 가능한 Gemini 모델을 찾지 못했습니다. API 키/프로젝트 설정을 확인해주세요.")
        for _model in _models_to_try:
            try:
                response = client.models.generate_content(
                    model=_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.4,
                        max_output_tokens=800,
                    ),
                )
                break
            except Exception as _e:
                _msg = str(_e)
                _short = _msg[:120] + ("..." if len(_msg) > 120 else "")
                _tried_errors.append(f"[{_model}] {_short}")
                continue
        if response is None:
            raise RuntimeError("모든 모델 시도 실패 → " + " | ".join(_tried_errors))
        result = json.loads(response.text)
        st.session_state[cache_key] = result
        return result
    except Exception as e:
        return {"error": str(e)}


def list_available_models_text():
    """진단용: 현재 API 키로 접근 가능한 generateContent 모델 목록을 문자열로 반환."""
    api_key = get_api_key()
    if not api_key:
        return "API 키가 등록되지 않았습니다."
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        rows = []
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions:
                rows.append((m.name or "").replace("models/", ""))
        if not rows:
            return "generateContent를 지원하는 모델이 하나도 조회되지 않았습니다."
        return "\n".join(f"- {r}" for r in rows)
    except Exception as e:
        return f"모델 목록 조회 실패: {e}"


def render_overall_summary_box(result):
    """전체 종합 요약을 상단 박스로 표시."""
    if result is None:
        return
    if result.get("error") == "no_api_key":
        st.info("💡 AI 인사이트를 보려면 사이드바 안내에 따라 Gemini API 키를 등록해주세요.")
        return
    if "error" in result:
        st.warning(f"AI 인사이트 생성 실패: {result['error']}")
        with st.expander("🔍 내 API 키로 사용 가능한 모델 확인하기"):
            st.code(list_available_models_text())
            st.caption(
                "위 목록에 모델이 있는데도 계속 실패한다면 무료 할당량(quota) 문제일 가능성이 높아요. "
                "aistudio.google.com → 사용량/비율 제한 메뉴에서 해당 모델의 무료 한도를 확인해주세요."
            )
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


def generate_ranking_insights(ranking_rows: list, context_label: str, cache_prefix: str):
    """
    카테고리/브랜드 랭킹용 인사이트 생성.
    ranking_rows: [{"name":"남성", "current": 36329408, "prev": 39092344, "share": 32.9, "yoy": -7.0}, ...]
    반환: {"overall_summary": str, "top_movers": [str, ...]} 또는 {"error": ...}
    """
    api_key = get_api_key()
    if not api_key:
        return {"error": "no_api_key"}

    cache_key = f"{cache_prefix}_{_make_cache_key(ranking_rows, context_label)}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        lines = []
        for r in ranking_rows:
            yoy_txt = f"{r['yoy']:+.1f}%" if r.get("yoy") is not None else "비교불가"
            lines.append(
                f"- {r['name']}: 거래액 {r['current']:,.0f} (비중 {r.get('share',0):.1f}%, 전년比 {yoy_txt})"
            )
        rows_text = "\n".join(lines)

        prompt = f"""아래는 이커머스 EP(가격비교) 채널의 거래액 랭킹 데이터입니다. 조건: {context_label}

{rows_text}

위 데이터를 분석해 다음 JSON 형식으로만 응답해주세요 (다른 텍스트 없이 JSON만):
{{
  "overall_summary": "전체 구성과 흐름을 2~3문장으로 요약. 상위 집중도, 성장/부진 항목, 주목할 변화를 포함.",
  "top_movers": [
    "가장 크게 성장한 항목과 그 시사점 (한 문장)",
    "가장 크게 부진한 항목과 그 시사점 (한 문장)",
    "그 외 눈여겨볼 포인트 하나 (한 문장)"
  ]
}}
수치를 과장하지 말고 객관적으로, 마케터가 바로 실무에 쓸 수 있는 톤으로 작성하세요."""

        response = None
        _tried_errors = []
        _models_to_try = _pick_available_models(client)
        if not _models_to_try:
            raise RuntimeError("사용 가능한 Gemini 모델을 찾지 못했습니다.")
        for _model in _models_to_try:
            try:
                response = client.models.generate_content(
                    model=_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.4,
                        max_output_tokens=800,
                    ),
                )
                break
            except Exception as _e:
                _msg = str(_e)
                _tried_errors.append(f"[{_model}] {_msg[:120]}")
                continue
        if response is None:
            raise RuntimeError("모든 모델 시도 실패 → " + " | ".join(_tried_errors))

        result = json.loads(response.text)
        st.session_state[cache_key] = result
        return result
    except Exception as e:
        return {"error": str(e)}


def render_ranking_insight_box(result):
    """랭킹 인사이트를 박스로 표시."""
    if result is None:
        return
    if result.get("error") == "no_api_key":
        st.info("💡 AI 인사이트를 보려면 Gemini API 키를 등록해주세요.")
        return
    if "error" in result:
        st.warning(f"AI 인사이트 생성 실패: {result['error']}")
        with st.expander("🔍 내 API 키로 사용 가능한 모델 확인하기"):
            st.code(list_available_models_text())
        return

    summary = result.get("overall_summary", "")
    movers = result.get("top_movers", []) or []
    movers_html = "".join(f"<li style='margin-bottom:3px;'>{m}</li>" for m in movers)
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#eef2ff,#f5f3ff);border:1px solid #ddd6fe;"
        f"border-radius:10px;padding:14px 18px;margin:8px 0 16px 0;'>"
        f"<div style='font-size:0.78rem;color:#7c3aed;font-weight:700;margin-bottom:4px;'>🤖 AI 인사이트</div>"
        f"<div style='font-size:0.88rem;color:#374151;line-height:1.5;margin-bottom:8px;'>{summary}</div>"
        f"<ul style='font-size:0.82rem;color:#4b5563;margin:0;padding-left:18px;'>{movers_html}</ul>"
        f"</div>",
        unsafe_allow_html=True,
    )
