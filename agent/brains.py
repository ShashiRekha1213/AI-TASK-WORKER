"""Decision-makers. Both implement:  decide(state) -> Decision   and   observe(decision, results).

ClaudeBrain    : the real LLM agent (Anthropic tool use). Decides every step itself.
MLXBrain       : LLM agent running LOCALLY (mlx-community Mistral via mlx-lm). No API key, no network.
HeuristicBrain : OFFLINE deterministic policy that drives the exact same tools/guardrails/verifier.
                 It exists so the harness + test-suite can run without an API key or network.
                 It is NOT an LLM and is far less flexible; use --brain claude for the real thing.
"""

import re, uuid
from dataclasses import dataclass, field
import config
from tools import registry


@dataclass
class Call:
    name: str
    input: dict
    id: str = field(default_factory=lambda: "call_" + uuid.uuid4().hex[:8])


@dataclass
class Decision:
    thought: str = ""
    calls: list = field(default_factory=list)


def C(_tool, /, **kw):
    return Call(_tool, kw)


# --------------------------------------------------------------------------- Claude
class ClaudeBrain:
    def __init__(self, goal):
        import anthropic
        from dotenv import load_dotenv

        load_dotenv()
        self.client = anthropic.Anthropic()
        self.messages = [{"role": "user", "content": goal}]

    def decide(self, state):
        from agent.prompts import SYSTEM_PROMPT

        resp = self.client.messages.create(
            model=config.MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=registry.schemas(),
            messages=self.messages,
        )
        self.messages.append({"role": "assistant", "content": resp.content})
        thought = " ".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [Call(b.name, dict(b.input), b.id) for b in resp.content if b.type == "tool_use"]
        return Decision(thought, calls)

    def observe(self, decision, results):
        blocks = [
            {"type": "tool_result", "tool_use_id": c.id, "content": r.to_text(), "is_error": not r.ok}
            for c, r in zip(decision.calls, results)
        ]
        self.messages.append({"role": "user", "content": blocks})

    def nudge(self):
        self.messages.append(
            {"role": "user", "content": "You must end by calling the finish tool with a status and summary."}
        )


# --------------------------------------------------------------------------- MLX (local Mistral)
MLX_TOOL_PROTOCOL = """

HOW TO CALL TOOLS (you are a local model without native tool-calling):
Reply with ONE short sentence of reasoning, then exactly ONE tool call as a JSON object on its own line:
{"tool": "<tool_name>", "args": {<arguments>}}
Rules: valid JSON only, double quotes, no code fences, one call per reply. After each call you will receive
the tool result as a message starting with TOOL_RESULT. Always finish by calling the finish tool.
Never invent invoice values. Use only the fields extracted from the selected PDF and remembered facts.
The New Payable form has vendor (#vendor), invoice number (#invoice_no), amount (#amount), and due date (#due_date).
There is NO invoice-date input on this form. Do not try to fill #invoice_date.
Use only real selectors listed by read_page. Never invent placeholder selectors.
After a user answers a question, use that answer; do not ask the same question again.

AVAILABLE TOOLS:
"""


def _tool_catalog():
    import json

    lines = []
    for t in registry.schemas():
        props = t["input_schema"].get("properties", {})
        req = set(t["input_schema"].get("required", []))
        args = ", ".join(f"{k}{'' if k in req else '?'}: {v.get('type', 'any')}" for k, v in props.items())
        lines.append(f"- {t['name']}({args}) -- {t['description']}")
    return "\n".join(lines)


def extract_tool_call(text):
    """Pull the first {"tool":..., "args":...} JSON object out of free-form model text.
    Returns (thought, name, args) or (text, None, None) if nothing parseable was found."""
    import json

    dec, i = json.JSONDecoder(), 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return text.strip(), None, None
        try:
            obj, end = dec.raw_decode(text[i:])
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and isinstance(obj.get("tool") or obj.get("name"), str):
            name = obj.get("tool") or obj.get("name")
            args = obj.get("args") or obj.get("arguments") or obj.get("input") or {}
            if isinstance(args, dict):
                return text[:i].strip(), name, args
        i += 1


class MLXBrain:
    """Local LLM agent with a deterministic safety/workflow controller.

    The local model is loaded and queried on every step. Its proposed tool call is
    accepted only when it is compatible with the next safe workflow action. If the
    model emits prose-only output, placeholder values, skips PDF extraction, or
    tries to submit before remembering facts, the controller corrects the action.
    This keeps MLX as the selected LLM while preventing common small-model failures.
    """

    MAX_FORMAT_RETRIES = 1

    def __init__(self, goal, generate_fn=None):
        from agent.prompts import SYSTEM_PROMPT

        self.system = SYSTEM_PROMPT + MLX_TOOL_PROTOCOL + _tool_catalog()
        self.messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": goal},
        ]
        self._generate = generate_fn or self._load_mlx()
        self._guide = HeuristicBrain(goal)
        self._expected = None
        self._guide_started = False
        self._tool_history = []

    @staticmethod
    def _load_mlx():
        try:
            from mlx_lm import load, generate
            from mlx_lm.sample_utils import make_sampler
        except ImportError as e:  # pragma: no cover
            raise SystemExit("mlx-lm is not installed (Apple Silicon only): pip install mlx-lm") from e
        print(f"[mlx] loading {config.MLX_MODEL} ...")
        model, tokenizer = load(config.MLX_MODEL)
        sampler = make_sampler(temp=config.MLX_TEMPERATURE)

        def gen(messages):
            prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
            return generate(
                model, tokenizer, prompt=prompt, max_tokens=config.MLX_MAX_TOKENS,
                sampler=sampler, verbose=False
            )

        return gen

    @staticmethod
    def _has_placeholder(value):
        if isinstance(value, dict):
            return any(MLXBrain._has_placeholder(v) for v in value.values())
        if isinstance(value, list):
            return any(MLXBrain._has_placeholder(v) for v in value)
        if not isinstance(value, str):
            return False
        v = value.strip().casefold()
        return (v.startswith("<") and v.endswith(">")) or v in {
            "<amount>", "<due_date>", "<invoice_no>", "<vendor>", "amount",
            "due_date", "invoice_no", "vendor", "tbd", "n/a"
        }

    def decide(self, state):
        # Ask the LLM for its decision, but establish the next safe action from the
        # same workflow's evidence-aware policy. The controller is not allowed to
        # let a model skip reading the PDF or bypass the fact-memory guardrail.
        expected = self._guide.decide(state)
        self._expected = expected
        raw = ""
        thought, name, args = "", None, None
        try:
            raw = str(self._generate(self._chat_messages())).strip()
            thought, name, args = extract_tool_call(raw)
        except Exception as exc:
            thought = f"LLM generation failed ({type(exc).__name__}); using guarded recovery."

        if raw:
            self.messages.append({"role": "assistant", "content": raw})

        expected_names = {c.name for c in expected.calls}
        compatible = bool(name and name in expected_names and isinstance(args, dict))
        if compatible and self._has_placeholder(args):
            compatible = False

        # For multi-action stages (remember all required facts, fill all form fields),
        # execute the complete validated batch. A local model's single incomplete call
        # must not advance the policy past fields it did not fill/remember.
        if compatible and len(expected.calls) == 1:
            expected_call = expected.calls[0]
            compatible = (name == expected_call.name and args == expected_call.input)

        if compatible:
            # Keep the safe, source-grounded arguments. Use the LLM's reasoning as
            # the visible thought, but don't let it replace values with hallucinations.
            return Decision(thought or expected.thought, expected.calls)

        reason = "LLM action was missing, out of sequence, or unsupported; guarded workflow selected the next safe action."
        visible_thought = (thought or expected.thought).strip()
        combined = f"{visible_thought} [{reason}]" if visible_thought else reason
        return Decision(combined, expected.calls)

    def _chat_messages(self):
        """Mistral templates require user/assistant alternation; merge adjacent roles."""
        out = []
        for m in self.messages:
            role = "user" if m["role"] == "system" else m["role"]
            if out and out[-1]["role"] == role:
                out[-1] = {"role": role, "content": out[-1]["content"] + "\n\n" + m["content"]}
            else:
                out.append(dict(m, role=role))
        return out

    def observe(self, decision, results):
        # Advance the controller with the action it actually planned, not a possibly
        # hallucinated proposal from the LLM.
        if self._expected is not None:
            self._guide.observe(self._expected, results)
            self._expected = None
        self._tool_history.extend(
            {"tool": c.name, "input": c.input, "result": r.to_text()}
            for c, r in zip(decision.calls, results)
        )
        parts = [f"TOOL_RESULT ({c.name}): {r.to_text()}" for c, r in zip(decision.calls, results)]
        reminders = [
            "IMPORTANT: use only invoice values returned by read_pdf; never use placeholders. "
            "Remember vendor, invoice_no, amount, and due_date before submitting. "
            "The controller will reject actions that skip required workflow stages."
        ]
        for c, r in zip(decision.calls, results):
            if c.name == "ask_user" and r.ok:
                answer = (r.data or {}).get("user_answer", "")
                reminders.append(
                    f"HUMAN ANSWER MEMORY: Question {c.input.get('question', '')!r}; "
                    f"answer {answer!r}. Do not ask it again; use the answer and continue."
                )
        self.messages.append({"role": "user", "content": "\n".join(parts + reminders)})

    def nudge(self):
        self.messages.append({
            "role": "user",
            "content": 'Return a valid tool call. Required final format: '
                       '{"tool": "finish", "args": {"status": "failed", "summary": "..."}}'
        })


# --------------------------------------------------------------------------- Heuristic
def parse_vendor(goal):
    m = re.search(
        r"(?:invoices?|bills?)\s+(?:from|of|by)\s+(.+?)(?:\s*[,.;]|\s+(?:and|then|extract)\b|$)", goal, re.I
    )
    return m.group(1).strip() if m else None


class HeuristicBrain:
    FIELDS = [
        ("vendor", "#vendor"),
        ("invoice_no", "#invoice_no"),
        ("amount", "#amount"),
        ("due_date", "#due_date"),
    ]

    def __init__(self, goal):
        self.goal, self._last, self._started = goal, None, False
        self.gen = self._policy()

    def decide(self, state):
        try:
            return next(self.gen) if not self._started else self.gen.send(self._last)
        except StopIteration:
            return Decision("policy exhausted", [])
        finally:
            self._started = True

    def observe(self, decision, results):
        self._last = results

    def nudge(self):
        pass

    def _finish(self, status, summary, thought=""):
        return Decision(thought, [C("finish", status=status, summary=summary)])

    def _policy(self):
        vendor = parse_vendor(self.goal)
        if not vendor:
            r = yield Decision(
                "Goal names no vendor; I must ask.",
                [C("ask_user", question="Which vendor's invoice should I process?", kind="clarify")],
            )
            vendor = r[0].data["user_answer"]
        r = yield Decision(
            f"Plan: find '{vendor}' invoices -> read all -> pick latest -> check duplicates -> enter in portal -> verify.",
            [C("search_files", query=vendor)],
        )
        files = r[0].data["matches"] if r[0].ok else []
        if not files and len(vendor.split()) > 1:
            r = yield Decision(
                "No match; alternative strategy: search by first word of the vendor name.",
                [C("search_files", query=vendor.split()[0])],
            )
            files = r[0].data["matches"] if r[0].ok else []
        if not files:
            yield self._finish(
                "failed",
                f"No invoice found for vendor '{vendor}' in the invoice folder (also tried a partial name). Nothing was entered.",
                "Not found; reporting instead of guessing.",
            )
            return

        results = yield Decision(
            f"Found {len(files)} candidate file(s); reading each.", [C("read_pdf", path=f) for f in files]
        )
        invs = [dict(r.data["fields"], file=f) for f, r in zip(files, results) if r.ok]
        if not invs:
            yield self._finish(
                "failed", "Invoices were found but none could be read (no text layer?). Needs OCR or a human."
            )
            return
        dated = [i for i in invs if i.get("invoice_date") and i.get("amount") is not None]
        if not dated:
            yield self._finish(
                "failed",
                "Invoice PDFs were found, but none had both a readable invoice date and amount. Nothing was entered.",
                "Cannot safely select the latest invoice without extracted date and amount.",
            )
            return
        newest = max(i["invoice_date"] for i in dated)
        tied = [i for i in dated if i["invoice_date"] == newest]
        chosen = tied[0]
        if len(tied) > 1:
            opts = [f"{i['invoice_no']} ({i['amount']:,.2f})" for i in tied]
            r = yield Decision(
                f"{len(tied)} invoices share the latest date {newest}: cannot choose safely -> ask.",
                [
                    C(
                        "ask_user",
                        question=f"Invoices {', '.join(opts)} are all dated {newest}. Which one should I enter?",
                        kind="clarify",
                        options=opts,
                    )
                ],
            )
            ans = r[0].data["user_answer"].upper()
            pick = [i for i in tied if i["invoice_no"] in ans]
            if not pick:
                yield self._finish(
                    "failed",
                    f"Could not tell which of {[i['invoice_no'] for i in tied]} to use from the answer {ans!r}.",
                )
                return
            chosen = pick[0]

        facts = {
            "vendor": chosen["vendor"],
            "invoice_no": chosen["invoice_no"],
            "amount": chosen["amount"],
            "due_date": chosen["due_date"],
        }
        yield Decision(
            f"Latest = {chosen['invoice_no']} ({chosen['invoice_date']}). Storing facts.",
            [C("remember", key=k, value=v) for k, v in facts.items()],
        )

        r = yield Decision(
            "Duplicate check before touching the form.", [C("get_payables", vendor=chosen["vendor"])]
        )
        if r[0].ok and any(p["invoice_no"] == chosen["invoice_no"] for p in r[0].data["payables"]):
            yield self._finish(
                "already_done",
                f"{chosen['invoice_no']} for {chosen['vendor']} is already in the payables system; I did not enter it again.",
            )
            return

        yield Decision(
            "Opening the New Payable form.", [C("open_page", url=f"{config.APP_URL}/payables/new")]
        )
        yield Decision("Reading page structure.", [C("read_page")])
        fill = [
            C("type_text", selector=sel, text=(f"{facts[k]:.2f}" if k == "amount" else facts[k]))
            for k, sel in self.FIELDS
        ]
        yield Decision(
            "Filling the form from remembered facts.", fill + [C("screenshot", name="form_filled")]
        )

        submit_sel, saved, attempts, last_alerts = (
            "#submit-btn",
            False,
            0,
            "",
        )  # selector remembered from previous runs
        while attempts < 4 and not saved:
            attempts += 1
            r = (
                yield Decision(
                    f"Submitting (attempt {attempts}) via {submit_sel}.", [C("click", selector=submit_sel)]
                )
            )[0]
            if r.blocked:
                why = r.error or ""
                status = (
                    "declined_by_user"
                    if "declined" in why.lower()
                    else ("already_done" if "Duplicate" in why else "failed")
                )
                yield self._finish(status, f"Submission blocked by guardrail: {why}")
                return
            if not r.ok:
                pr = (
                    yield Decision(
                        "Click failed; the page may have changed. Re-reading it to find the real submit button.",
                        [C("read_page")],
                    )
                )[0]
                btns = [b for b in (pr.data["buttons"] if pr.ok else []) if b["type"] == "submit"]
                if not btns:
                    yield self._finish("failed", f"Could not find a submit button. Last error: {r.error}")
                    return
                submit_sel = btns[0]["selector"]
                continue
            last_alerts = " | ".join(r.data["alerts"])
            if "saved successfully" in last_alerts.lower():
                saved = True
                break
            pr = (
                yield Decision(
                    f"Page shows an error: {last_alerts!r}. Re-reading to see if my inputs survived.",
                    [C("read_page")],
                )
            )[0]
            if not any(w in last_alerts.lower() for w in ("try again", "503", "temporar")):
                yield self._finish("failed", f"Form rejected the data: {last_alerts}")
                return
            vals = {i["name"]: i["value"] for i in pr.data["inputs"]} if pr.ok else {}
            refill = [
                C("type_text", selector=sel, text=(f"{facts[k]:.2f}" if k == "amount" else facts[k]))
                for k, sel in self.FIELDS
                if not vals.get(k)
            ]
            if refill:
                yield Decision("Some fields were cleared; re-typing them.", refill)
        if not saved:
            yield self._finish(
                "failed", f"Could not save after {attempts} attempts. Last message: {last_alerts}"
            )
            return

        r = yield Decision(
            "Saved banner seen. Verifying by reading the record back.",
            [C("get_payables", vendor=chosen["vendor"]), C("screenshot", name="after_submit")],
        )
        row = next(
            (
                p
                for p in (r[0].data["payables"] if r[0].ok else [])
                if p["invoice_no"] == chosen["invoice_no"]
            ),
            None,
        )
        if not row:
            yield self._finish("failed", "Portal said saved but the record is not in the read-back.")
            return
        retry_note = f" It took {attempts} submit attempt(s)." if attempts > 1 else ""
        yield self._finish(
            "success",
            f"Entered {row['vendor']} invoice {row['invoice_no']}: amount {row['amount']:,.2f}, due {row['due_date']} "
            f"(record id {row['id']}). Read-back confirms the saved values.{retry_note}",
        )


def make_brain(name, goal):
    if name == "claude":
        return ClaudeBrain(goal)
    if name == "mlx":
        return MLXBrain(goal)
    return HeuristicBrain(goal)
