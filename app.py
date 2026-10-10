"""RideWise Assist - Streamlit chat UI.

Run:  streamlit run app.py
"""
from __future__ import annotations

import html

import streamlit as st

from ridewise import auth
from ridewise import db_scope as ds
from ridewise import orchestrator as orch
from ridewise.config import settings
from ridewise.i18n import LANGUAGES
from ridewise.llm import get_llm

st.set_page_config(page_title="RideWise Assist", page_icon="🛵", layout="centered")

CSS = """
<style>
.block-container {max-width: 860px;}
.rw-chip {display:inline-block;padding:2px 8px;border-radius:999px;font-size:0.70rem;
  font-weight:600;letter-spacing:.03em;text-transform:uppercase;margin-right:6px;}
.rw-db{background:#E0F2FE;color:#075985;}
.rw-policy{background:#DCFCE7;color:#166534;}
.rw-calc{background:#FEF9C3;color:#854D0E;}
.rw-web{background:#F3E8FF;color:#6B21A8;}
sup.cite{color:#0F766E;font-weight:700;}
.rw-note{background:#FFF7ED;border:1px solid #FED7AA;color:#9A3412;
  padding:6px 10px;border-radius:8px;font-size:0.82rem;margin-top:6px;}
</style>
"""


def init_state():
    st.session_state.setdefault("session", None)
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("language", "en")


def answer_html(text: str) -> str:
    import re
    safe = html.escape(text)
    safe = re.sub(r"\[S(\d+)\]", r"<sup class='cite'>[\1]</sup>", safe)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    return safe.replace("\n", "<br>")


def login_view():
    st.markdown("<h1 style='margin-bottom:0'>🛵 RideWise Assist</h1>", unsafe_allow_html=True)
    st.caption("Read-only support assistant for RideWise rentals · answers from your records and our policies")
    if not get_llm().configured:
        st.info("No LLM configured — running in **offline mode** (answers composed directly "
                "from evidence; NL→SQL analytics need the LLM). Set LLM_API_KEY in .env.")
    with st.container(border=True):
        lang = st.selectbox("Language", list(LANGUAGES), format_func=lambda k: LANGUAGES[k],
                            key="language")
        tab_cust, tab_agent = st.tabs(["Customer", "Support agent"])
        with tab_cust:
            cid = st.text_input("Customer ID", placeholder="e.g. CUST0001")
            if st.button("Start as customer", type="primary", use_container_width=True):
                sess, err = auth.start_customer_session(cid, settings.db_path, lang)
                if err:
                    st.error(err)
                else:
                    st.session_state.session = sess
                    st.session_state.messages = []
                    st.rerun()
        with tab_agent:
            st.write("Start a support-desk session with operational access (customer PII masked).")
            if st.button("Start as support agent", type="primary", use_container_width=True):
                st.session_state.session = auth.start_agent_session(lang)
                st.session_state.messages = []
                st.rerun()
    st.caption("🔒 Read-only · the assistant never books, cancels, pays or refunds.")


def header(sess):
    c1, c2, c3 = st.columns([5, 2, 2])
    with c1:
        role = "Customer · " + (sess.customer_id or "") if sess.role == "customer" else "Support agent"
        badges = f"<span class='rw-chip rw-db'>{role}</span>"
        if not get_llm().configured:
            badges += "<span class='rw-chip rw-calc'>Offline answers</span>"
        st.markdown(f"**🛵 RideWise Assist**&nbsp;&nbsp;{badges}", unsafe_allow_html=True)
    with c2:
        if st.button("New conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
    with c3:
        if st.button("Sign out", use_container_width=True):
            st.session_state.session = None
            st.session_state.messages = []
            st.rerun()


def render_answer(msg: dict, sess):
    st.markdown(answer_html(msg["text"]), unsafe_allow_html=True)
    for w in msg.get("warnings", []):
        st.markdown(f"<div class='rw-note'>{html.escape(w)}</div>", unsafe_allow_html=True)
    cits = msg.get("citations", [])
    queries = msg.get("queries", [])
    cols = st.columns([1, 1, 4])
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


def chat_view(sess):
    header(sess)
    st.divider()
    if not st.session_state.messages:
        st.info("Ask about " + ("your bookings, payments, charges, or our policies."
                                 if sess.role == "customer"
                                 else "any customer's records, fleet status, payments, or our policies."))
    for m in st.session_state.messages:
        with st.chat_message(m["role"], avatar="🧑" if m["role"] == "user" else "🛵"):
            if m["role"] == "assistant":
                render_answer(m, sess)
            else:
                st.write(m["content"])

    prompt = st.chat_input("Type your question…")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        history = [{"role": m["role"], "content": m.get("content", m.get("text", ""))}
                   for m in st.session_state.messages[:-1]]
        with st.chat_message("assistant", avatar="🛵"):
            with st.spinner("Thinking…"):
                scoped = ds.build(sess, settings.db_path)
                try:
                    ans = orch.answer(sess, scoped, prompt, history)
                finally:
                    scoped.close()
        st.session_state.messages.append({
            "role": "assistant", "text": ans.text, "content": ans.text,
            "warnings": ans.warnings,
            "citations": [c.model_dump() for c in ans.citations],
            "queries": [q.model_dump() for q in ans.queries],
            "followups": ans.followups})
        st.rerun()


def main():
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    if st.session_state.session is None:
        login_view()
    else:
        chat_view(st.session_state.session)


main()
