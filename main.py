"""CLI:  python main.py "Find the latest invoice from Acme Supplies, extract the amount and due date, enter it into the payables system, and tell me when done."
python main.py --scenario tie_for_latest          (set up a built-in scenario, you answer the agent's questions)
python main.py --list-scenarios
"""

import argparse, sys
from agent import loop
from company_app.app import start_server
from company_app import db
from tools.browser_tools import Browser
from tools.human_tools import CLIHuman, ScriptedHuman
from scripts.generate_invoices import main as gen_invoices
import config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("goal", nargs="?")
    ap.add_argument(
        "--brain", 
        choices=["mlx", "heuristic"],
        default="mlx",
        help="mlx = local mlx-community Mistral; heuristic = offline deterministic policy",
    )
    ap.add_argument("--scenario")
    ap.add_argument("--list-scenarios", action="store_true")
    ap.add_argument(
        "--auto-answer", action="store_true", help="use the scenario's scripted user instead of prompting you"
    )
    ap.add_argument("--keep-db", action="store_true", help="don't reset the payables DB before running")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    a = ap.parse_args()

    from tests.scenarios import SCENARIOS, setup_scenario

    if a.list_scenarios:
        for s in SCENARIOS:
            print(f"{s['name']:24} {s['desc']}")
        return
    if not config.INVOICE_DIR.exists() or not list(config.INVOICE_DIR.glob("*.pdf")):
        gen_invoices()
    srv = start_server()
    human, goal = CLIHuman(), a.goal
    if a.scenario:
        sc = next(s for s in SCENARIOS if s["name"] == a.scenario)
        setup_scenario(sc)
        goal = goal or sc["goal"]
        if a.auto_answer:
            human = ScriptedHuman(sc["answers"])
    elif not a.keep_db:
        db.reset()
    if not goal:
        ap.error("give a goal or --scenario")
    browser = Browser(headless=not a.headed)
    try:
        rep = loop.run(goal, human, browser, brain=a.brain)
    finally:
        browser.close()
        srv.stop()
    print(f"\nFull log: {rep['run_dir']}/run_log.md")
    sys.exit(0 if rep["status"] in ("COMPLETED", "ALREADY_DONE", "DECLINED_BY_USER") else 1)


if __name__ == "__main__":
    main()
