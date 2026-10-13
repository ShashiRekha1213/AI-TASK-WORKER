from dataclasses import dataclass, field


@dataclass
class AgentState:
    """Working memory for one run."""

    goal: str
    facts: dict = field(default_factory=dict)  # vendor, invoice_no, amount, due_date ...
    seen_invoices: dict = field(
        default_factory=dict
    )  # filename -> extracted fields (source-of-truth for verifier)
    asks: list = field(default_factory=list)  # every human interaction
    flags: dict = field(default_factory=dict)  # clarified / approve_granted / confirm_granted / declined
    failures: dict = field(default_factory=dict)  # tool -> consecutive failure count
    recoveries: list = field(default_factory=list)  # (tool, 'failed N times then succeeded')
    evidence: list = field(default_factory=list)  # screenshot paths
    baseline: list = field(default_factory=list)  # payables before the run
    steps: int = 0
    final: dict | None = None  # set by finish()
