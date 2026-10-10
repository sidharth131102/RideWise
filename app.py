"""RideWise Assist - Streamlit chat UI (login, chat, persistent history).

Run:  streamlit run app.py
"""
from __future__ import annotations

import datetime as _dt
import html
import re

import streamlit as st

from ridewise import auth, chat_store
from ridewise import db_scope as ds
from ridewise import orchestrator as orch
from ridewise.config import settings
from ridewise.contracts import Session
from ridewise.i18n import LANGUAGES
from ridewise.llm import get_llm

st.set_page_config(page_title="RideWise Assist", page_icon="🛵", layout="wide")

CSS = """
<style>
.block-container {max-width: 900px; padding-top: 2rem;}
.rw-chip {display:inline-block;padding:2px 9px;border-radius:999px;font-size:0.70rem;
  font-weight:600;letter-spacing:.03em;text-transform:uppercase;margin-right:6px;}
.rw-db{background:#E0F2FE;color:#075985;}
.rw-policy{background:#DCFCE7;color:#166534;}
.rw-calc{background:#FEF9C3;color:#854D0E;}
.rw-web{background:#F3E8FF;color:#6B21A8;}
sup.cite{color:#0F766E;font-weight:700;margin:0 1px;}
.rw-note{background:#FFF7ED;border:1px solid #FED7AA;color:#9A3412;
  padding:6px 10px;border-radius:8px;font-size:0.82rem;margin-top:8px;}
.rw-hero{font-size:2rem;font-weight:800;margin-bottom:0;}
.rw-sub{color:#64748B;margin-top:0;}
section[data-testid="stSidebar"] {background:#F8FAFC;}
.rw-convo-active button {border-color:#0F766E !important;color:#0F766E !important;font-weight:600;}
</style>
"""


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
def init_state():
    st.session_state.setdefault("session", None)
    st.session_state.setdefault("conversations", [])
    st.session_state.setdefault("active_id", None)
    st.session_state.setdefault("pending_prompt", None)
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


# --------------------------------------------------------------------------- #
# rendering helpers
# --------------------------------------------------------------------------- #
def answer_html(text: str) -> str:
    safe = html.escape(text)
    safe = re.sub(r"\[S(\d+)\]", r"<sup class='cite'>[\1]</sup>", safe)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    return safe.replace("\n", "<br>")


def render_assistant(msg: dict, sess: Session, is_last: bool):
    st.markdown(answer_html(msg["text"]), unsafe_allow_html=True)
    for w in msg.get("warnings", []):
        st.markdown(f"<div class='rw-note'>{html.escape(w)}</div>", unsafe_allow_html=True)
    cits = msg.get("citations", [])
    queries = msg.get("queries", [])
    cols = st.columns([1, 1, 1, 5])
    if cits:
        with cols[0].popover("Sources"):
            for c in cits:
                st.markdown(f"<span class='rw-chip rw-{c['kind']}'>{c['kind']}</span> "
                            f"**[{c['ref']}]** {html.escape(c['label'])}", unsafe_allow_html=True)
    if sess.role == "agent" and queries:
        with cols[1].popover("SQL"):
            for q in queries:
                st.code(q["sql"], language="sql")
                st.caption(f"{q['row_count']} row(s)")
    if msg.get("summary"):
        with cols[2].popover("Copy"):
            st.code(msg["summary"])
    # follow-up pills only on the last assistant message
    if is_last and msg.get("followups"):
        st.caption("Suggested follow-ups")
        fcols = st.columns(len(msg["followups"]))
        for i, f in enumerate(msg["followups"]):
            if fcols[i].button(f, key=f"fu_{msg.get('ts', 0)}_{i}", use_container_width=True):
                st.session_state.pending_prompt = f
                st.rerun()


# --------------------------------------------------------------------------- #
# views
# --------------------------------------------------------------------------- #
def login_view():
    left, mid, right = st.columns([1, 2, 1])
    with mid:
        st.markdown("<div class='rw-hero'>🛵 RideWise Assist</div>", unsafe_allow_html=True)
        st.markdown("<p class='rw-sub'>Read-only support assistant · answers from your "
                    "records and our policies</p>", unsafe_allow_html=True)
        if not get_llm().configured:
            st.info("No LLM configured — **offline mode** (answers composed from evidence; "
                    "NL→SQL analytics need the LLM). Set LLM_API_KEY in .env.")
        with st.container(border=True):
            lang = st.selectbox("Language", list(LANGUAGES),
                                format_func=lambda k: LANGUAGES[k], key="language")
            tab_cust, tab_agent = st.tabs(["🧑 Customer", "🧑‍💼 Support agent"])
            with tab_cust:
                cid = st.text_input("Customer ID", placeholder="e.g. CUST0001")
                last4 = st.text_input("Last 4 digits of registered phone",
                                      max_chars=4, placeholder="e.g. 2345", type="password")
                if st.button("Start as customer", type="primary", use_container_width=True):
                    sess, err = auth.start_customer_session(cid, last4, settings.db_path, lang)
                    if err:
                        st.error(err)
                    else:
                        after_login(sess)
                        st.rerun()
                st.caption("Verify with your Customer ID and the last 4 digits of your "
                           "registered mobile number.")
            with tab_agent:
                st.write("Operational access across RideWise (customer contact PII masked).")
                staff_id = st.text_input("Staff ID", placeholder="e.g. agent")
                staff_pw = st.text_input("Password", type="password")
                if st.button("Start as support agent", type="primary", use_container_width=True):
                    sess, err = auth.agent_login(staff_id, staff_pw, lang)
                    if err:
                        st.error(err)
                    else:
                        after_login(sess)
                        st.rerun()
                if not settings.agent_pw_hash:
                    st.caption("No staff password set yet. Run "
                               "`python scripts/set_agent_password.py`.")
        st.caption("🔒 Read-only · the assistant never books, cancels, pays or refunds.")


def sidebar(sess: Session):
    with st.sidebar:
        role = ("Customer · " + (sess.customer_id or "")) if sess.role == "customer" \
            else "Support agent"
        st.markdown(f"**🛵 RideWise Assist**")
        st.markdown(f"<span class='rw-chip rw-db'>{role}</span>", unsafe_allow_html=True)
        if not get_llm().configured:
            st.markdown("<span class='rw-chip rw-calc'>Offline answers</span>",
                        unsafe_allow_html=True)
        if st.button("➕ New conversation", use_container_width=True, type="primary"):
            start_new_conversation()
            st.rerun()

        st.divider()
        st.caption("History")
        convos = sorted(st.session_state.conversations,
                        key=lambda c: c.get("updated_at", 0), reverse=True)
        shown = [c for c in convos if c.get("messages") or c["id"] == st.session_state.active_id]
        if not shown:
            st.caption("No conversations yet.")
        for c in shown:
            when = _dt.datetime.fromtimestamp(c.get("updated_at", 0)).strftime("%d %b %H:%M")
            label = f"{c['title']}  ·  {when}"
            active = c["id"] == st.session_state.active_id
            wrap = st.container()
            if active:
                wrap.markdown("<div class='rw-convo-active'>", unsafe_allow_html=True)
            if wrap.button(label, key=f"conv_{c['id']}", use_container_width=True):
                st.session_state.active_id = c["id"]
                st.rerun()
            if active:
                wrap.markdown("</div>", unsafe_allow_html=True)

        st.divider()
        if st.button("🗑️ Clear history", use_container_width=True):
            chat_store.clear_all(sess)
            st.session_state.conversations = []
            start_new_conversation()
            st.rerun()
        if st.button("Sign out", use_container_width=True):
            sign_out()
            st.rerun()


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

    if not convo["messages"]:
        st.info("Ask about " + ("your bookings, payments, charges, or our policies."
                                 if sess.role == "customer"
                                 else "any customer's records, fleet status, payments, or policies."))

    assistant_idxs = [i for i, m in enumerate(convo["messages"]) if m["role"] == "assistant"]
    last_assistant = assistant_idxs[-1] if assistant_idxs else -1
    for i, m in enumerate(convo["messages"]):
        with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else "🛵"):
            if m["role"] == "assistant":
                render_assistant(m, sess, is_last=(i == last_assistant))
            else:
                st.write(m["content"])

    prompt = st.chat_input("Type your question…")
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
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    if st.session_state.session is None:
        login_view()
    else:
        chat_view(st.session_state.session)


main()
