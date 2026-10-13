"""Step logger: JSONL trace + human-readable markdown run log (the evidence for the submission)."""

import json, time
from pathlib import Path


class RunLogger:
    def __init__(self, run_dir: Path, verbose=True, on_event=None):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.entries, self.verbose = [], verbose
        self.on_event = on_event  # optional UI hook: on_event("step", entry) / on_event("thought", text)

    def log(self, step, thought, tool, args, result, note=""):
        e = {
            "step": step,
            "ts": time.strftime("%H:%M:%S"),
            "thought": thought,
            "tool": tool,
            "args": args,
            "ok": result.ok,
            "blocked": result.blocked,
            "result": (result.error if not result.ok else result.data),
            "note": note,
        }
        self.entries.append(e)
        with open(self.dir / "run_log.jsonl", "a") as fh:
            fh.write(json.dumps(e, default=str) + "\n")
        if self.on_event:
            self.on_event("step", e)
        if self.verbose:
            mark = "OK  " if result.ok else ("BLOCK" if result.blocked else "FAIL")
            short = json.dumps(args, default=str)[:90]
            msg = "" if result.ok else f" -> {str(result.error)[:110]}"
            print(f"  [{step:02d}] {mark} {tool}({short}){msg}")

    def say(self, text):
        if self.on_event and text:
            self.on_event("thought", text)
        if self.verbose and text:
            print(f"       thought: {text[:160]}")

    def write_markdown(self, report):
        L = [
            f"# Run log",
            f"**Goal:** {report['goal']}",
            f"**Final status:** `{report['status']}`",
            f"**Agent summary:** {report['summary']}",
            "",
            "## Steps",
            "| # | tool | args | result |",
            "|---|---|---|---|",
        ]
        for e in self.entries:
            r = "OK" if e["ok"] else ("BLOCKED" if e["blocked"] else "FAILED")
            detail = str(e["result"]).replace("|", "/").replace("\n", " ")[:140]
            note = f" _[{e['note']}]_" if e["note"] else ""
            L.append(
                f"| {e['step']} | `{e['tool']}` | `{json.dumps(e['args'], default=str)[:80]}` | **{r}**{note} {detail} |"
            )
        L += ["", "## Reasoning trace"] + [
            f"- step {e['step']}: {e['thought']}" for e in self.entries if e["thought"]
        ]
        L += ["", "## Human interactions"] + (
            [f"- ({a['kind']}) Q: {a['question']}  \n  A: {a['answer']}" for a in report["asks"]]
            or ["- none"]
        )
        L += [
            "",
            "## Failures & recoveries",
            f"- failures by tool: {report['failures']}",
            f"- recovered: {report['recoveries'] or 'none needed'}",
        ]
        v = report["verification"]
        L += [
            "",
            "## Independent verification",
            f"**Passed:** {v['passed']}  (records before/after: {v['records_before']} -> {v['records_now']})",
        ]
        L += [f"- {'PASS' if ok else 'FAIL'}: {k}" for k, ok in v["checks"].items()]
        L += ["", "## Evidence files"] + [f"- {p}" for p in report["evidence"]]
        (self.dir / "run_log.md").write_text("\n".join(L))
