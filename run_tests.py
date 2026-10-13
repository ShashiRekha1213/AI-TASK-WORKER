"""Run all scenarios and write runs/TEST_REPORT.md.
python run_tests.py                 # offline heuristic brain (no API key needed)
python run_tests.py --brain claude  # real LLM agent
python run_tests.py --only happy_path
"""

import argparse, shutil
from pathlib import Path
import config
from agent import loop
from company_app.app import start_server
from tools.browser_tools import Browser
from tools.human_tools import ScriptedHuman
from scripts.generate_invoices import main as gen_invoices
from tests.scenarios import SCENARIOS, setup_scenario, evaluate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", choices=["claude", "mlx", "heuristic"], default="heuristic")
    ap.add_argument("--only")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--runs", type=int, default=1, help="repeat each scenario N times")
    a = ap.parse_args()
    gen_invoices()
    shutil.rmtree(config.RUNS_DIR, ignore_errors=True)
    config.RUNS_DIR.mkdir(exist_ok=True)
    srv, browser = start_server(), Browser()
    results = []
    try:
        for sc in SCENARIOS:
            if a.only and sc["name"] != a.only:
                continue
            passes, last_checks, last_rep = 0, [], None
            for i in range(a.runs):
                setup_scenario(sc)
                human = ScriptedHuman(sc["answers"])
                rep = loop.run(
                    sc["goal"],
                    human,
                    browser,
                    brain=(sc["rogue"]() if "rogue" in sc else a.brain),
                    run_name=f"{sc['name']}_{i+1}",
                    verbose=not a.quiet,
                )
                checks = evaluate(sc, rep)
                passes += all(ok for _, ok in checks)
                last_checks, last_rep = checks, rep
            results.append((sc, passes, a.runs, last_checks, last_rep))
    finally:
        browser.close()
        srv.stop()

    L = [
        f"# Test report  (brain = {a.brain}, runs per scenario = {a.runs})",
        "",
        "| Scenario | What it tests | Result | Final status |",
        "|---|---|---|---|",
    ]
    for sc, p, n, checks, rep in results:
        L.append(
            f"| `{sc['name']}` | {sc['desc']} | {'PASS' if p == n else 'FAIL'} ({p}/{n}) | {rep['status']} |"
        )
    L += ["", "## Check details (last run of each scenario)"]
    for sc, p, n, checks, rep in results:
        L += (
            [f"### {sc['name']}", f"_Agent summary:_ {rep['summary']}", ""]
            + [f"- {'PASS' if ok else 'FAIL'}: {c}" for c, ok in checks]
            + [f"- run log: `{Path(rep['run_dir']).name}/run_log.md`", ""]
        )
    (config.RUNS_DIR / "TEST_REPORT.md").write_text("\n".join(L))
    total = sum(p == n for _, p, n, _, _ in results)
    print("\n" + "=" * 70)
    for sc, p, n, _, rep in results:
        print(f"{'PASS' if p == n else 'FAIL'} {p}/{n}  {sc['name']:28} -> {rep['status']}")
    print(f"\n{total}/{len(results)} scenarios passed.  Report: {config.RUNS_DIR/'TEST_REPORT.md'}")
    raise SystemExit(0 if total == len(results) else 1)


if __name__ == "__main__":
    main()
