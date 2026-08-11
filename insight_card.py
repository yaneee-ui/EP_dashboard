"""인사이트 카드 모듈: 좌측 자동 요약(API 미사용, 무료) + 우측 AI 인사이트·메모(GitHub 저장).

app.py에서 분리한 이유: app.py가 너무 커져서(3800줄+), 작은 수정 하나에도 관련 없는
다른 페이지 코드까지 같이 봐야 하는 비효율이 있었음. 이 모듈은 완결된 기능 단위라
분리 리스크가 낮아서 가장 먼저 뽑아냄. 페이지 1/2에서
`from insight_card import render_insight_card`로 가져다 씀.
"""
import streamlit as st
import pandas as pd

from utils import format_delta_html
from ai_insights import generate_insights


def generate_auto_summary(payload, period_label="", extra_sections=None):
    """이미 계산된 증감률 숫자만으로 규칙 기반 요약을 만든다. API 호출이 없어서 무료·즉시.
    payload: [{"name","value","prev_label","prev_delta","yoy_label","yoy_delta"}, ...] — KPI 카드용.
    extra_sections: [{"header": str, "items": payload와 동일 구조}, ...] — BPU별 비교, 카테고리별
    톱무버 등 KPI 카드 밖의 다른 표 내용도 같이 담을 때 씀. 없으면 실적 섹션만 표시.
    HTML로 반환한다 — 카드 전체가 unsafe_allow_html로 그려지는데 마크다운 **볼드**를
    섞어 쓰면 일부만 볼드되는 등 렌더링이 깨지는 문제가 있어서, 처음부터 <b> 태그로 만든다.
    색상(▲초록/▼빨강)은 나머지 대시보드 전체에서 쓰는 format_delta_html을 그대로 재사용해서
    스타일을 통일한다."""
    if not payload and not extra_sections:
        return "<div style='color:#9ca3af;'>표시할 데이터가 없습니다.</div>"

    def _section_html(header, items):
        _rows = []
        for item in items:
            _bits = [f"<b>{item['name']}</b> {item.get('value', '-')}"]
            _pd_ = item.get("prev_delta")
            if _pd_ is not None:
                _bits.append(f"{item.get('prev_label', '전기간')} {format_delta_html(_pd_)}")
            _yd_ = item.get("yoy_delta")
            if _yd_ is not None:
                _bits.append(f"{item.get('yoy_label', '전년')} {format_delta_html(_yd_)}")
            _rows.append(f"<div style='margin:5px 0;'>{' · '.join(_bits)}</div>")
        _hdr = f"<div style='font-size:0.78rem;color:#6b7280;font-weight:700;margin:10px 0 6px;'>□ {header}</div>"
        return _hdr + "".join(_rows)

    _blocks = []
    if payload:
        _blocks.append(_section_html(f"실적{' — ' + period_label if period_label else ''}", payload))
    for sec in (extra_sections or []):
        if sec.get("items"):
            _blocks.append(_section_html(sec["header"], sec["items"]))
    # 첫 섹션 위 여백은 필요 없어서(카드 안에 이미 패딩이 있음) 제거
    return "".join(_blocks).replace("margin:10px 0 6px;", "margin:0 0 6px;", 1)


def generate_auto_summary_plain(payload, period_label="", extra_sections=None):
    """generate_auto_summary와 동일한 내용을 HTML 태그 없는 평문으로 만든다.
    (복사 버튼으로 클립보드에 붙여넣을 때 태그가 그대로 보이지 않게 하기 위함)"""
    if not payload and not extra_sections:
        return "표시할 데이터가 없습니다."

    def _section_plain(header, items):
        lines = [f"□ {header}"]
        for item in items:
            _bits = [f"{item['name']} {item.get('value', '-')}"]
            _pd_ = item.get("prev_delta")
            if _pd_ is not None:
                _arrow = "▲" if _pd_ >= 0 else "▼"
                _bits.append(f"{item.get('prev_label', '전기간')} {_arrow}{abs(_pd_):.1f}%")
            _yd_ = item.get("yoy_delta")
            if _yd_ is not None:
                _arrow2 = "▲" if _yd_ >= 0 else "▼"
                _bits.append(f"{item.get('yoy_label', '전년')} {_arrow2}{abs(_yd_):.1f}%")
            lines.append(" · ".join(_bits))
        return "\n".join(lines)

    _blocks = []
    if payload:
        _blocks.append(_section_plain(f"실적{' — ' + period_label if period_label else ''}", payload))
    for sec in (extra_sections or []):
        if sec.get("items"):
            _blocks.append(_section_plain(sec["header"], sec["items"]))
    return "\n\n".join(_blocks)


MEMO_FILE_PATH = "data/insight_memos.json"


def _github_conf():
    """secrets에 GITHUB_TOKEN / GITHUB_REPO(예: 'yani/ep_dashboard')가 설정돼 있는지 확인."""
    try:
        token = st.secrets.get("GITHUB_TOKEN")
        repo = st.secrets.get("GITHUB_REPO")
    except Exception:
        return None, None
    if not token or not repo:
        return None, None
    return token, repo


@st.cache_data(ttl=30, show_spinner=False)
def _load_all_memos():
    """GitHub 저장소의 메모 JSON 파일을 통째로 읽어온다. 연결 안 돼 있으면 빈 dict."""
    import requests, base64, json as _json
    token, repo = _github_conf()
    if not token or not repo:
        return {}
    url = f"https://api.github.com/repos/{repo}/contents/{MEMO_FILE_PATH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            content = base64.b64decode(resp.json()["content"]).decode("utf-8")
            return _json.loads(content)
        return {}
    except Exception:
        return {}


def load_memo(key):
    """특정 key(조회조건 조합)의 저장된 메모 텍스트. 없으면 None."""
    memos = _load_all_memos()
    entry = memos.get(key)
    return entry.get("text") if entry else None


def save_memo(key, text):
    """메모를 GitHub 저장소 파일에 커밋. (읽기→수정→쓰기, 파일 없으면 새로 생성)
    반환: (성공여부, 메시지)"""
    import requests, base64, json as _json
    token, repo = _github_conf()
    if not token or not repo:
        return False, "GitHub 저장소 연결이 설정되지 않았어요. (secrets에 GITHUB_TOKEN·GITHUB_REPO 필요)"
    url = f"https://api.github.com/repos/{repo}/contents/{MEMO_FILE_PATH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        memos, sha = {}, None
        if resp.status_code == 200:
            data = resp.json()
            sha = data["sha"]
            memos = _json.loads(base64.b64decode(data["content"]).decode("utf-8"))
        elif resp.status_code != 404:
            return False, f"저장소 조회 실패 (HTTP {resp.status_code})"

        memos[key] = {"text": text, "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
        new_content = base64.b64encode(
            _json.dumps(memos, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": f"메모 업데이트: {key}", "content": new_content}
        if sha:
            payload["sha"] = sha
        put_resp = requests.put(url, headers=headers, json=payload, timeout=10)
        if put_resp.status_code in (200, 201):
            _load_all_memos.clear()
            return True, "저장했습니다."
        return False, f"저장 실패 (HTTP {put_resp.status_code})"
    except Exception as e:
        return False, f"저장 중 오류: {e}"


def _extract_ai_text(ai_result):
    """generate_insights() 반환값에서 표시용 텍스트를 방어적으로 뽑아낸다
    (dict/문자열 등 정확한 타입을 몰라도 최대한 합리적으로 처리)."""
    if not ai_result:
        return ""
    if isinstance(ai_result, str):
        return ai_result
    if isinstance(ai_result, dict):
        for k in ("summary", "overall", "overall_summary", "text", "insight"):
            if ai_result.get(k):
                return str(ai_result[k])
        return str(ai_result)
    return str(ai_result)


def render_insight_card(auto_payload, ai_context, ai_cache_key, memo_key, period_label="", extra_sections=None):
    """좌: 자동 요약(API 미사용) / 우: AI 생성·메모(GitHub 저장). 참고 이미지 스타일 구현.
    extra_sections: [{"header": str, "items": [...]}] — KPI 카드 외에 BPU별 비교, 카테고리별
    톱무버 같은 다른 표의 핵심 내용도 요약에 같이 담고 싶을 때 넘긴다 (선택사항).
    반환값: 이번 실행에서 유효한 ai_result (버튼을 안 눌렀어도 같은 조회조건이면 캐시에서
    복원됨) — 호출부가 render_metric_insight(카드별 한줄 인사이트)에 이어서 쓸 수 있게 함."""
    # 원인 불명의 전역 CSS(styles.py)가 버튼 글자에 색/밑줄을 입히는 문제가 있어서,
    # 이 카드 안의 버튼만이라도 강제로 원래 스타일로 되돌린다 (!important로 덮어씀).
    # (참고: 버튼 하단이 잘리던 문제의 진짜 원인은 styles.py의 죽은 CSS 규칙이었고
    # 그건 styles.py에서 직접 제거함 — 여기 남은 건 색상/밑줄 문제 대응용 + 혹시 모를
    # 텍스트 줄바꿈 안전장치만)
    st.markdown(
        """
        <style>
        div[data-testid="stButton"] button,
        div[data-testid="stButton"] button * {
            color: rgb(49, 51, 63) !important;
            text-decoration: none !important;
            -webkit-text-decoration: none !important;
            border-bottom: none !important;
        }
        div[data-testid="stExpander"] div[data-testid="stButton"] button {
            height: 2rem !important;
            min-height: 2rem !important;
            padding: 0.15rem 0.6rem !important;
            line-height: 1.4 !important;
        }
        div[data-testid="stExpander"] div[data-testid="stButton"] button p {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            font-size: 0.82rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _auto_html = generate_auto_summary(auto_payload, period_label, extra_sections)
    # AI 쪽엔 섹션 구분 없이 전부 합쳐서 넘긴다 (KPI + BPU별/카테고리별 핵심 수치까지
    # 반영된 서술형 인사이트를 만들 수 있도록)
    _ai_payload_full = list(auto_payload or [])
    for sec in (extra_sections or []):
        _ai_payload_full.extend(sec.get("items", []))

    # 카드 전체를 st.expander로 감싼다 — 접기/펼치기가 기본 내장돼 있고, 네이티브
    # 컴포넌트라 테두리도 항상 안정적으로 그려진다 (예전엔 <div> 직접 열고 닫는
    # 방식이었는데, 접기/펼치기 요청이 와서 이 참에 더 안정적인 방식으로 교체함).
    with st.expander("📊 인사이트  ·  좌: 자동 요약(토큰 미사용) · 우: AI 인사이트·메모(저장됨)", expanded=True):
        _col_l, _col_r = st.columns(2)

        with _col_l:
            st.markdown("<b style='font-size:0.85rem;'>⚡ 자동 요약</b>", unsafe_allow_html=True)
            _l_btn1, _l_btn2 = st.columns(2)
            with _l_btn1:
                st.button("갱신", key=f"auto_regen::{memo_key}", use_container_width=True, help="자동 요약을 다시 계산해요")
            _copy_state_key = f"show_copy::{memo_key}"
            with _l_btn2:
                if st.button("복사", key=f"autocp::{memo_key}", use_container_width=True):
                    st.session_state[_copy_state_key] = not st.session_state.get(_copy_state_key, False)
            st.markdown(
                f"<div style='background:#f9fafb;border-radius:8px;padding:12px 14px;margin:18px 0 4px;"
                f"font-size:0.82rem;line-height:1.7;color:#374151;min-height:120px;'>{_auto_html}</div>",
                unsafe_allow_html=True,
            )
            if st.session_state.get(_copy_state_key):
                # 네이티브 st.code는 자체 복사 아이콘이 내장돼 있어서(iframe 없이도 동작),
                # 정렬 깨질 위험이 없다 — 오른쪽 위 아이콘을 눌러서 복사하면 됨.
                st.code(generate_auto_summary_plain(auto_payload, period_label, extra_sections), language=None)


        with _col_r:
            st.markdown("<b style='font-size:0.85rem;'>🤖 AI 인사이트 · 메모</b>", unsafe_allow_html=True)
            _r_btn1, _r_btn2 = st.columns(2)
            with _r_btn1:
                _ai_clicked = st.button("AI 생성", key=f"ai_btn::{ai_cache_key}", use_container_width=True)

            # AI 결과 캐싱(조회조건이 바뀌면 이전 결과를 자동 폐기) — 기존 로직과 동일한 패턴
            _ai_result_key = f"ai_raw::{ai_cache_key}"
            _ai_ctx_key = f"ai_ctx::{ai_cache_key}"
            _ai_result = None
            _ai_error = None
            if _ai_clicked:
                with st.spinner("AI 인사이트 생성 중..."):
                    try:
                        _ai_result = generate_insights(_ai_payload_full, ai_context, ai_cache_key)
                    except Exception as e:
                        _ai_error = str(e)
                    st.session_state[_ai_result_key] = _ai_result
                    st.session_state[_ai_ctx_key] = ai_context
            elif st.session_state.get(_ai_ctx_key) == ai_context:
                _ai_result = st.session_state.get(_ai_result_key)
            else:
                st.session_state.pop(_ai_result_key, None)
                st.session_state.pop(_ai_ctx_key, None)

            # 텍스트영역(메모)은 key로만 상태를 관리한다 — key가 있는 위젯은 한번 그려지고 나면
            # value= 인자가 재실행 시 무시되고 st.session_state[key]가 우선하는 Streamlit 특성
            # 때문에, 예전엔 별도 키(_memo_state_key)에만 AI 결과를 넣어서 실제 텍스트영역엔
            # 절대 반영이 안 되던 버그가 있었음. 위젯의 '진짜' key를 직접 세팅해야 함.
            _memo_widget_key = f"memo_ta::{memo_key}"
            if _memo_widget_key not in st.session_state:
                _saved = load_memo(memo_key)
                st.session_state[_memo_widget_key] = _saved or ""
            if _ai_clicked:
                _ai_text = _extract_ai_text(_ai_result)
                if _ai_text:
                    st.session_state[_memo_widget_key] = _ai_text
                elif _ai_error:
                    st.error(f"AI 생성 중 오류가 발생했어요: {_ai_error}")
                else:
                    st.warning("AI가 빈 결과를 반환했어요. 다시 시도해주세요.")

            st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
            _memo_text = st.text_area(
                "메모", key=_memo_widget_key,
                height=120, label_visibility="collapsed",
                placeholder="AI 생성을 누르거나 직접 작성하세요. 저장하면 다음에 열 때 그대로 남습니다.",
            )
            with _r_btn2:
                _save_clicked = st.button("💾 저장", key=f"save_btn::{memo_key}", use_container_width=True)
            if _save_clicked:
                _ok, _msg = save_memo(memo_key, _memo_text)
                (st.success if _ok else st.warning)(_msg)
            _token, _repo = _github_conf()
            if _token and _repo:
                st.caption("🤖 **AI 생성**을 누르면 메모에 채워져요(직접 수정 가능). 메모는 GitHub 저장소에 저장돼요.")
            else:
                st.caption(
                    "⚠️ 메모 저장소가 아직 연결 안 됐어요 — secrets에 `GITHUB_TOKEN`·`GITHUB_REPO`를 "
                    "설정하면 메모가 계속 저장돼요. (지금은 새로고침하면 메모가 사라져요)"
                )
    return _ai_result
