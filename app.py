"""RideWise Assist - Streamlit chat UI (login, chat, persistent history, voice).

Run:  streamlit run app.py
"""
from __future__ import annotations

import datetime as _dt
import html
import re

import streamlit as st

from ridewise import auth, chat_store, stt
from ridewise import db_scope as ds
from ridewise import orchestrator as orch
from ridewise.config import settings
from ridewise.contracts import Session
from ridewise.i18n import LANGUAGES
from ridewise.llm import get_llm

st.set_page_config(page_title="RideWise Assist", page_icon="🛵", layout="wide",
                   initial_sidebar_state="expanded")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Material+Symbols+Rounded:opsz,wght@20..48,400..700&display=swap');

:root{
  --rw-teal:#0F766E; --rw-teal-d:#115E59; --rw-ink:#0F172A; --rw-mut:#64748B;
  --rw-line:#E2E8F0; --rw-bg:#F8FAFC;
}
html, body, [class*="css"], .stMarkdown, .stButton>button, input, textarea {
  font-family:'Inter',system-ui,sans-serif;}
.block-container {max-width: 880px; padding-top: 1.2rem; padding-bottom: 6rem;}
#MainMenu, footer {visibility:hidden;}

.ms{font-family:'Material Symbols Rounded';font-weight:500;vertical-align:-3px;
  font-size:1.05em;line-height:1;}

/* chips */
.rw-chip {display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:999px;
  font-size:0.70rem;font-weight:600;letter-spacing:.02em;text-transform:uppercase;margin-right:6px;}
.rw-chip .ms{font-size:0.95em;}
.rw-db{background:#E0F2FE;color:#075985;}
.rw-policy{background:#DCFCE7;color:#166534;}
.rw-calc{background:#FEF9C3;color:#854D0E;}
.rw-web{background:#F3E8FF;color:#6B21A8;}
.rw-role{background:#CCFBF1;color:#115E59;}
.rw-off{background:#FEE2E2;color:#991B1B;}
.rw-on{background:#DCFCE7;color:#166534;}
sup.cite{color:var(--rw-teal);font-weight:700;margin:0 1px;}

/* header bar */
.rw-head{display:flex;align-items:center;justify-content:space-between;
  padding:12px 18px;border:1px solid var(--rw-line);border-radius:16px;
  background:linear-gradient(180deg,#FFFFFF, #FBFDFC);margin-bottom:14px;}
.rw-head .t{font-weight:700;font-size:1.05rem;color:var(--rw-ink);display:flex;align-items:center;gap:8px;}
.rw-head .t .ms{color:var(--rw-teal);font-size:1.3rem;}

/* chat bubbles */
[data-testid="stChatMessage"]{border-radius:16px;padding:6px 14px;margin-bottom:6px;
  border:1px solid transparent;}
[data-testid="stChatMessageAvatarUser"]{background:var(--rw-teal) !important;}
.rw-note{background:#FFF7ED;border:1px solid #FED7AA;color:#9A3412;
  padding:7px 11px;border-radius:10px;font-size:0.82rem;margin-top:8px;display:flex;gap:6px;align-items:center;}

/* login */
.rw-login-card{border:1px solid var(--rw-line);border-radius:22px;overflow:hidden;
  box-shadow:0 10px 30px rgba(15,23,42,.06);}
.rw-hero{background:linear-gradient(135deg,var(--rw-teal),#0E7490);color:#fff;
  padding:26px 28px 22px;}
.rw-hero .logo{width:52px;height:52px;border-radius:14px;background:rgba(255,255,255,.18);
  display:flex;align-items:center;justify-content:center;font-size:28px;margin-bottom:10px;}
.rw-hero h1{font-size:1.6rem;font-weight:800;margin:0;color:#fff;}
.rw-hero p{margin:4px 0 0;color:#D1FAE5;font-size:0.92rem;}

/* sidebar */
section[data-testid="stSidebar"]{background:var(--rw-bg);border-right:1px solid var(--rw-line);}
.rw-brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:1.1rem;
  color:var(--rw-ink);margin-bottom:2px;}
.rw-brand .ms{color:var(--rw-teal);font-size:1.5rem;}
.rw-sec{font-size:0.72rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  color:var(--rw-mut);margin:10px 2px 4px;}
.rw-convo-active button{border-color:var(--rw-teal) !important;color:var(--rw-teal) !important;
  font-weight:600;background:#ECFDF5 !important;}

/* pills row (followups) */
.rw-fu-label{font-size:0.75rem;color:var(--rw-mut);margin:10px 0 2px;display:flex;gap:6px;align-items:center;}

/* buttons: softer */
.stButton>button{border-radius:12px;}
.stChatInput textarea{border-radius:14px !important;}
.rw-foot{color:var(--rw-mut);font-size:0.78rem;display:flex;gap:6px;align-items:center;justify-content:center;margin-top:8px;}
</style>
"""

ICON = {"db": "database", "policy": "description", "calc": "calculate", "web": "public"}


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
def init_state():
    st.session_state.setdefault("session", None)
    st.session_state.setdefault("conversations", [])
    st.session_state.setdefault("active_id", None)
    st.session_state.setdefault("pending_prompt", None)
    st.session_state.setdefault("stt_draft", None)
    st.session_state.setdefault("language", "en")


def active_convo():
    for c in st.session_state.conversations:
        if c["id"] == st.session_state.active_id:
            return c
    return None


def start_new_conversation():
    convo = chat_store.new_conversation()
    st.session_state.conversations.insert(0, convo)
    st.session_state.active_id = convo["id"]


def after_login(sess: Session):
    st.session_state.session = sess
    st.session_state.conversations = chat_store.load_all(sess)
    if st.session_state.conversations:
        st.session_state.active_id = st.session_state.conversations[0]["id"]
    else:
        start_new_conversation()


def sign_out():
    st.session_state.session = None
    st.session_state.conversations = []
    st.session_state.active_id = None
    st.session_state.pending_prompt = None
    st.session_state.stt_draft = None


# --------------------------------------------------------------------------- #
# rendering helpers
# --------------------------------------------------------------------------- #
def ms(name: str) -> str:
    return f"<span class='ms'>{name}</span>"


def answer_html(text: str) -> str:
    safe = html.escape(text)
    safe = re.sub(r"\[S(\d+)\]", r"<sup class='cite'>[\1]</sup>", safe)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    return safe.replace("\n", "<br>")


def chip(kind: str, label: str) -> str:
    return (f"<span class='rw-chip rw-{kind}'>{ms(ICON.get(kind, 'label'))}"
            f"{html.escape(label)}</span>")


def render_assistant(msg: dict, sess: Session, is_last: bool):
    st.markdown(answer_html(msg["text"]), unsafe_allow_html=True)
    for w in msg.get("warnings", []):
        st.markdown(f"<div class='rw-note'>{ms('info')}{html.escape(w)}</div>",
                    unsafe_allow_html=True)
    cits = msg.get("citations", [])
    queries = msg.get("queries", [])
    cols = st.columns([1.1, 1, 1, 5])
    if cits:
        with cols[0].popover("Sources", icon=":material/menu_book:"):
            for c in cits:
                st.markdown(f"{chip(c['kind'], c['kind'])} **[{c['ref']}]** "
                            f"{html.escape(c['label'])}", unsafe_allow_html=True)
    if sess.role == "agent" and queries:
        with cols[1].popover("SQL", icon=":material/database:"):
            for q in queries:
                st.code(q["sql"], language="sql")
                st.caption(f"{q['row_count']} row(s)")
    if msg.get("summary"):
        with cols[2].popover("Copy", icon=":material/content_copy:"):
            st.code(msg["summary"])
    if is_last and msg.get("followups"):
        st.markdown(f"<div class='rw-fu-label'>{ms('lightbulb')} Suggested follow-ups</div>",
                    unsafe_allow_html=True)
        fcols = st.columns(len(msg["followups"]))
        for i, f in enumerate(msg["followups"]):
            if fcols[i].button(f, key=f"fu_{msg.get('ts', 0)}_{i}",
                               use_container_width=True):
                st.session_state.pending_prompt = f
                st.rerun()


# --------------------------------------------------------------------------- #
# views
# --------------------------------------------------------------------------- #
def login_view():
    left, mid, right = st.columns([1, 1.4, 1])
    with mid:
        st.markdown("<div class='rw-login-card'>", unsafe_allow_html=True)
        st.markdown(
            "<div class='rw-hero'><div class='logo'>🛵</div>"
            "<h1>RideWise Assist</h1>"
            "<p>Read-only support — answers from your records and our policies</p></div>",
            unsafe_allow_html=True)
        with st.container():
            st.write("")
            lang = st.selectbox("Language", list(LANGUAGES),
                                format_func=lambda k: LANGUAGES[k], key="language")
            if not get_llm().configured:
                st.info("Offline mode — answers are composed from evidence; "
                        "NL→SQL analytics need the LLM (set LLM_API_KEY in .env).",
                        icon=":material/wifi_off:")
            tab_cust, tab_agent = st.tabs(["Customer", "Support agent"])
            with tab_cust:
                cid = st.text_input("Customer ID", placeholder="e.g. CUST0001",
                                    key="cid")
                last4 = st.text_input("Last 4 digits of registered phone", max_chars=4,
                                      placeholder="••••", type="password", key="last4")
                if st.button("Start as customer", type="primary",
                             use_container_width=True, icon=":material/login:"):
                    sess, err = auth.start_customer_session(cid, last4, settings.db_path, lang)
                    if err:
                        st.error(err, icon=":material/error:")
                    else:
                        after_login(sess)
                        st.rerun()
                st.caption("Verify with your Customer ID and the last 4 digits of your "
                           "registered mobile number.")
            with tab_agent:
                staff_id = st.text_input("Staff ID", placeholder="e.g. agent", key="sid")
                staff_pw = st.text_input("Password", type="password", key="spw")
                if st.button("Start as support agent", type="primary",
                             use_container_width=True, icon=":material/badge:"):
                    sess, err = auth.agent_login(staff_id, staff_pw, lang)
                    if err:
                        st.error(err, icon=":material/error:")
                    else:
                        after_login(sess)
                        st.rerun()
                if not settings.agent_pw_hash:
                    st.caption("No staff password set. Run "
                               "`python scripts/set_agent_password.py`.")
            st.write("")
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='rw-foot'>{ms('lock')} Read-only · never books, "
                    f"cancels, pays or refunds</div>", unsafe_allow_html=True)


def sidebar(sess: Session):
    with st.sidebar:
        st.markdown(f"<div class='rw-brand'>{ms('two_wheeler')} RideWise Assist</div>",
                    unsafe_allow_html=True)
        role = ("Customer · " + (sess.customer_id or "")) if sess.role == "customer" \
            else "Support agent"
        status = (chip("role", role)
                  + ("<span class='rw-chip rw-on'>Online</span>" if get_llm().configured
                     else "<span class='rw-chip rw-off'>Offline</span>"))
        st.markdown(status, unsafe_allow_html=True)
        st.write("")

        # language selector (applies to the assistant's replies)
        langs = list(LANGUAGES)
        cur = sess.language if sess.language in langs else "en"
        new_lang = st.selectbox("Reply language", langs, index=langs.index(cur),
                                format_func=lambda k: LANGUAGES[k], key="chat_lang")
        if new_lang != sess.language:
            sess.language = new_lang
            st.rerun()

        if st.button("New conversation", use_container_width=True, type="primary",
                     icon=":material/add_comment:"):
            start_new_conversation()
            st.rerun()

        st.markdown("<div class='rw-sec'>History</div>", unsafe_allow_html=True)
        convos = sorted(st.session_state.conversations,
                        key=lambda c: c.get("updated_at", 0), reverse=True)
        shown = [c for c in convos if c.get("messages") or c["id"] == st.session_state.active_id]
        if not shown:
            st.caption("No conversations yet.")
        for c in shown:
            when = _dt.datetime.fromtimestamp(c.get("updated_at", 0)).strftime("%d %b · %H:%M")
            active = c["id"] == st.session_state.active_id
            wrap = st.container()
            if active:
                wrap.markdown("<div class='rw-convo-active'>", unsafe_allow_html=True)
            if wrap.button(f"{c['title']}", key=f"conv_{c['id']}", use_container_width=True,
                           icon=":material/chat_bubble:", help=f"Last updated {when}"):
                st.session_state.active_id = c["id"]
                st.rerun()
            if active:
                wrap.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='rw-sec'>Session</div>", unsafe_allow_html=True)
        if st.button("Clear history", use_container_width=True, icon=":material/delete:"):
            chat_store.clear_all(sess)
            st.session_state.conversations = []
            start_new_conversation()
            st.rerun()
        if st.button("Sign out", use_container_width=True, icon=":material/logout:"):
            sign_out()
            st.rerun()
        if settings.stt_configured():
            st.caption("🎙️ Voice input is on — tap the mic in the chat bar.")


def header_bar(sess: Session, convo: dict):
    title = html.escape(convo["title"]) if convo.get("messages") else "New conversation"
    read_only = "<span class='rw-chip rw-role'>" + "Read-only</span>"
    voice = "<span class='rw-chip rw-on'>🎙 Voice</span>" if settings.stt_configured() else ""
    st.markdown(
        f"<div class='rw-head'><div class='t'>{ms('forum')}{title}</div>"
        f"<div>{read_only}{voice}</div></div>", unsafe_allow_html=True)


def handle_turn(sess: Session, convo: dict, prompt: str):
    import time
    convo["messages"].append({"role": "user", "content": prompt, "ts": time.time()})
    if convo["title"] == "New conversation":
        convo["title"] = chat_store.title_from(prompt)
    history = [{"role": m["role"], "content": m.get("content", m.get("text", ""))}
               for m in convo["messages"][:-1]]
    scoped = ds.build(sess, settings.db_path)
    try:
        ans = orch.answer(sess, scoped, prompt, history)
    finally:
        scoped.close()
    convo["messages"].append({
        "role": "assistant", "text": ans.text, "content": ans.text,
        "warnings": ans.warnings,
        "citations": [c.model_dump() for c in ans.citations],
        "queries": [q.model_dump() for q in ans.queries],
        "followups": ans.followups, "summary": ans.summary, "ts": time.time()})
    convo["updated_at"] = time.time()
    chat_store.save_all(sess, st.session_state.conversations)


def chat_view(sess: Session):
    sidebar(sess)
    convo = active_convo()
    if convo is None:
        start_new_conversation()
        convo = active_convo()
    header_bar(sess, convo)

    if not convo["messages"]:
        hint = ("your bookings, payments, charges, or our policies."
                if sess.role == "customer"
                else "any customer's records, fleet status, payments, or policies.")
        st.info(f"Ask about {hint}", icon=":material/chat:")

    assistant_idxs = [i for i, m in enumerate(convo["messages"]) if m["role"] == "assistant"]
    last_assistant = assistant_idxs[-1] if assistant_idxs else -1
    for i, m in enumerate(convo["messages"]):
        with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else "🛵"):
            if m["role"] == "assistant":
                render_assistant(m, sess, is_last=(i == last_assistant))
            else:
                st.write(m["content"])

    # voice draft card ("Heard you say"), edited by the user, never auto-sent
    if st.session_state.stt_draft is not None:
        with st.container(border=True):
            st.markdown(f"{ms('graphic_eq')} **Heard you say** "
                        f"({LANGUAGES.get(sess.language, sess.language)}) — edit if needed",
                        unsafe_allow_html=True)
            edited = st.text_area("draft", value=st.session_state.stt_draft,
                                  key="stt_edit", label_visibility="collapsed")
            c1, c2, _ = st.columns([1, 1, 5])
            if c1.button("Send", type="primary", use_container_width=True,
                         icon=":material/send:"):
                st.session_state.stt_draft = None
                st.session_state.pending_prompt = edited
                st.rerun()
            if c2.button("Discard", use_container_width=True, icon=":material/close:"):
                st.session_state.stt_draft = None
                st.rerun()

    ci = st.chat_input("Ask about a booking, a charge, or a policy…",
                       accept_audio=settings.stt_configured())
    prompt = None
    if ci is not None:
        if isinstance(ci, str):
            prompt = ci
        else:  # ChatInputValue (accept_audio=True)
            audio = getattr(ci, "audio", None)
            text = (getattr(ci, "text", "") or "").strip()
            if audio is not None and not text:
                data = audio.getvalue() if hasattr(audio, "getvalue") else audio.read()
                with st.spinner("Transcribing…"):
                    heard, err = stt.transcribe(
                        data, sess.language, filename=getattr(audio, "name", "audio.wav"))
                if err or not heard:
                    st.toast(f"Could not transcribe: {err or 'empty audio'}")
                else:
                    st.session_state.stt_draft = heard
                    st.rerun()
            elif text:
                prompt = text

    pending = st.session_state.pending_prompt
    if pending:
        st.session_state.pending_prompt = None
        prompt = pending

    if prompt:
        with st.chat_message("user", avatar="🧑"):
            st.write(prompt)
        with st.chat_message("assistant", avatar="🛵"):
            with st.spinner("Thinking…"):
                handle_turn(sess, convo, prompt)
        st.rerun()


def main():
    from ridewise import tracing
    tracing.configure()      # no-op unless LANGSMITH_TRACING=true + key present
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    if st.session_state.session is None:
        login_view()
    else:
        chat_view(st.session_state.session)


main()
