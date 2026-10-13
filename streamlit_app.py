"""Streamlit interface for the AI task worker.

    streamlit run streamlit_app.py

The agent runs in a background thread (Playwright and MLX both need to live in ONE thread), streams its steps
into the page, and when it needs a human (clarify / confirm / approve) it blocks until you answer in the UI.
"""

import json
import queue
import threading
import time
import traceback
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from agent import loop
from company_app import db
from company_app.app import start_server
from scripts.generate_invoices import main as gen_invoices
from tests.scenarios import SCENARIOS, setup_scenario
from tools.browser_tools import Browser
from tools.human_tools import ScriptedHuman
from tools.system_tools import fetch_payables

st.set_page_config(page_title="AI Task Worker", page_icon="🧾", layout="wide")

DEFAULT_GOAL = (
    "Find the latest invoice from Acme Supplies, extract the amount and due date, "
    "enter it into the internal payables system, and tell me once it is done."
)
GOOD_STATUS = {"COMPLETED", "ALREADY_DONE", "DECLINED_BY_USER"}


# ----------------------------------------------------------------------------- background run
class Cancelled(Exception):
    pass


class RunHandle:
    """Shared between the UI thread (reads) and the agent thread (writes)."""

    def __init__(self, run_name):
        self.run_name = run_name
        self.run_dir = Path(config.RUNS_DIR) / run_name
        self.events = []  # ("thought", str) | ("step", dict) | ("ask", dict)
        self.pending = None  # {"question", "kind", "options"} while waiting for the human
        self.answers = queue.Queue()
        self.report = None
        self.error = None
        self.phase = "Starting..."
        self.done = False
        self.cancel = threading.Event()

    def on_event(self, kind, payload):
        if self.cancel.is_set():
            raise Cancelled()
        self.phase = "Agent is working"
        self.events.append((kind, payload))


class UIHuman:
    """Human-in-the-loop channel: blocks the agent thread until the Streamlit page supplies an answer."""

    def __init__(self, handle):
        self.h = handle

    def ask(self, question, kind="clarify", options=None):
        self.h.pending = {"question": question, "kind": kind, "options": options or []}
        self.h.phase = "Waiting for your answer"
        while True:
            if self.h.cancel.is_set():
                self.h.pending = None
                return "no"
            try:
                ans = self.h.answers.get(timeout=0.3)
                break
            except queue.Empty:
                continue
        self.h.pending = None
        self.h.events.append(("ask", {"kind": kind, "question": question, "answer": ans}))
        return ans


def _worker(h, cfg):
    browser = None
    try:
        config.MAX_STEPS = cfg["max_steps"]
        config.MLX_MODEL = cfg["model"]
        sc = cfg["scenario"]
        if sc:
            setup_scenario(sc)
        elif not cfg["keep_db"]:
            db.reset()
        human = ScriptedHuman(sc["answers"]) if (sc and cfg["auto_answer"]) else UIHuman(h)
        h.phase = "Starting browser..."
        browser = Browser(headless=True)
        h.phase = "Loading model / planning (first step can take a while for local models)..."
        h.report = loop.run(
            cfg["goal"], human, browser, brain=cfg["brain"], run_name=h.run_name, verbose=False, on_event=h.on_event
        )
    except Cancelled:
        h.error = "Run stopped by user."
    except BaseException as e:  # SystemExit (e.g. mlx-lm missing) included
        h.error = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
    finally:
        if browser:
            browser.close()
        h.pending, h.done, h.phase = None, True, "Finished"


@st.cache_resource
def get_server():
    if not config.INVOICE_DIR.exists() or not list(config.INVOICE_DIR.glob("*.pdf")):
        gen_invoices()
    return start_server()


# ----------------------------------------------------------------------------- rendering helpers
def render_step(e):
    icon = "⛔" if e["blocked"] else ("✅" if e["ok"] else "❌")
    note = f" · _{e['note']}_" if e["note"] else ""
    with st.expander(f"{icon} {e['step']:02d} · `{e['tool']}`{note}", expanded=not e["ok"]):
        if e["thought"]:
            st.caption(f"💭 {e['thought']}")
        st.code(json.dumps(e["args"], indent=2, default=str), language="json")
        res = e["result"]
        st.markdown("**Result**")
        if isinstance(res, (dict, list)):
            st.json(res, expanded=False)
        else:
            st.text(str(res)[:1500])


def render_events(events):
    last_thought = None
    for kind, p in events:
        if kind == "thought":
            last_thought = p
        elif kind == "step":
            render_step(p)
        elif kind == "ask":
            with st.chat_message("user"):
                st.markdown(f"**Agent asked ({p['kind']}):** {p['question']}")
                st.markdown(f"**You:** {p['answer']}")
    return last_thought


def render_question(h, q):
    with st.chat_message("assistant"):
        st.warning(f"**The agent needs your input ({q['kind']})**")
        st.markdown(q["question"])
        if q["options"]:
            cols = st.columns(len(q["options"]))
            for c, opt in zip(cols, q["options"]):
                if c.button(opt, key=f"opt_{opt}", width="stretch"):
                    h.answers.put(opt)
                    st.rerun()
        if q["kind"] in ("approve", "confirm"):
            c1, c2 = st.columns(2)
            if c1.button("✅ Yes, go ahead", type="primary", width="stretch"):
                h.answers.put("yes")
                st.rerun()
            if c2.button("❌ No, decline", width="stretch"):
                h.answers.put("no")
                st.rerun()
        with st.form("answer_form", clear_on_submit=True):
            txt = st.text_input("Or type an answer", placeholder="e.g. use invoice GLX-0412")
            if st.form_submit_button("Send") and txt.strip():
                h.answers.put(txt.strip())
                st.rerun()


def render_screenshots(run_dir):
    shots = sorted((run_dir / "screenshots").glob("*.png"), key=lambda p: p.stat().st_mtime)
    if shots:
        st.subheader("Browser screenshots")
        cols = st.columns(min(3, len(shots)))
        for i, s in enumerate(shots):
            cols[i % len(cols)].image(str(s), caption=s.stem, width="stretch")


def render_report(rep):
    ok = rep["status"] in GOOD_STATUS
    (st.success if ok else st.error)(f"**{rep['status']}** — {rep['summary']}")
    v = rep["verification"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Steps", rep["steps"])
    c2.metric("Human interactions", len(rep["asks"]))
    c3.metric("Records before → after", f"{v['records_before']} → {v['records_now']}")
    st.markdown("**Independent verification** (re-read from the system and compared with the source PDF)")
    st.dataframe(
        pd.DataFrame([{"check": k, "result": "PASS" if ok_ else "FAIL"} for k, ok_ in v["checks"].items()]),
        hide_index=True,
        width="stretch",
    )
    if rep["failures"] or rep["recoveries"]:
        st.info(f"Failures: {rep['failures'] or 'none'} · Recoveries: {rep['recoveries'] or 'none'}")
    md = Path(rep["run_dir"]) / "run_log.md"
    if md.exists():
        st.download_button("⬇️ Download run log (markdown)", md.read_text(), file_name=f"{md.parent.name}.md")


def payables_table():
    try:
        rows = fetch_payables()
    except Exception as e:
        st.error(f"Payables system unreachable: {e}")
        return
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No payables recorded yet.")


# ----------------------------------------------------------------------------- page
get_server()
h = st.session_state.get("handle")
running = bool(h and not h.done)
pending = None

st.title("🧾 AI Task Worker")
st.caption("Give the agent a finance task. It reads invoice PDFs, drives a real browser, asks you when unsure, and is independently verified.")

with st.sidebar:
    st.header("Settings")
    brain = st.radio(
        "Brain",
        ["mlx", "heuristic"],
        index=0,  # default to the local LLM; guarded workflow repairs invalid model actions
        format_func={
            "mlx": "Local LLM (MLX Mistral + safety controller)",
            "heuristic": "Offline heuristic (no LLM)",
        }.get,
        disabled=running,
    )
    model = st.text_input("MLX model", config.MLX_MODEL, disabled=running or brain != "mlx")
    max_steps = st.slider("Max agent steps", 10, 80, config.MAX_STEPS, disabled=running)
    st.divider()
    names = ["(custom goal)"] + [s["name"] for s in SCENARIOS]
    pick = st.selectbox("Test scenario", names, disabled=running)
    scenario = next((s for s in SCENARIOS if s["name"] == pick), None)
    if scenario:
        st.caption(scenario["desc"])
    auto_answer = st.checkbox("Auto-answer questions (scripted user)", disabled=running or not scenario)
    keep_db = st.checkbox("Keep existing payables (custom goal)", disabled=running or bool(scenario))
    if "rogue" in (scenario or {}):
        st.warning("This scenario uses a scripted rogue brain; the selected brain is ignored.")

tab_run, tab_sys = st.tabs(["Run agent", "Payables system"])

with tab_sys:
    st.caption("The simulated internal system the agent writes into (also at " + config.APP_URL + ").")
    payables_table()
    if st.button("Reset payables database", disabled=running):
        db.reset()
        st.rerun()

with tab_run:
    goal = st.text_area(
        "Task",
        scenario["goal"] if scenario else DEFAULT_GOAL,
        height=90,
        disabled=running,
        key=f"goal_{pick}",
    )
    c1, c2 = st.columns([1, 5])
    if c1.button("▶ Run", type="primary", disabled=running or not goal.strip()):
        h = RunHandle(time.strftime("ui_%Y%m%d_%H%M%S"))
        st.session_state["handle"] = h
        cfg = dict(
            goal=goal.strip(), brain=brain, model=model, max_steps=max_steps, scenario=scenario,
            auto_answer=auto_answer, keep_db=keep_db,
        )
        if scenario and "rogue" in scenario:
            cfg["brain"] = scenario["rogue"]()
        threading.Thread(target=_worker, args=(h, cfg), daemon=True).start()
        st.rerun()
    if running and c2.button("⏹ Stop"):
        h.cancel.set()

    if h:
        st.divider()
        events = list(h.events)
        pending = h.pending  # snapshot once so render and polling decisions agree
        if not h.done:
            st.info(f"⏳ {h.phase}")
        thought = render_events(events)
        if not h.done and thought and not pending:
            st.caption(f"💭 Latest thought: {thought}")
        if pending:
            render_question(h, pending)
        if h.error:
            st.error(h.error.split("\n\n")[0])
            with st.expander("Details"):
                st.code(h.error)
        if h.report:
            render_report(h.report)
        render_screenshots(h.run_dir)

# poll while the agent works (not while a question is on screen, so the answer form isn't wiped)
if h and not h.done and not pending:
    time.sleep(1)
    st.rerun()
