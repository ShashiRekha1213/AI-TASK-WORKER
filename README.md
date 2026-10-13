# Autonomous AI Task Worker

### LLM-Assisted Invoice Processing with Guardrails and Independent Verification

## Overview

The **Autonomous AI Task Worker** is a prototype that accepts a finance
task in natural language and executes an invoice-processing workflow
against a simulated company payables application.

For example, a user can ask the agent to find an invoice, extract its
details, check for an existing payable, enter eligible data into the web
application, and verify whether the record was saved correctly.

The project demonstrates how an AI-assisted agent can coordinate file
search, PDF extraction, browser automation, human clarification, policy
checks, and independent verification in a single workflow.

> **Project status:** Prototype for demonstration and testing. The
> included payables application is a simulated local environment, not a
> production finance system.

## Key Features

-   **Natural-language task input:** Describe an invoice-processing task
    in plain English.
-   **Multi-vendor invoice folder:** Work with sample PDF invoices for
    vendors including Acme, Globex, Hooli, Initech, and Umbrella.
-   **PDF discovery and extraction:** Search invoice files and extract
    invoice details using the project's PDF-reading tools.
-   **Payables duplicate checks:** Compare candidate invoices with
    records already present in the simulated payables system.
-   **Browser automation:** Use Playwright and Chromium to interact with
    the local payables web interface.
-   **Human-in-the-loop interaction:** Ask for clarification,
    confirmation, or approval when the workflow should not continue
    autonomously.
-   **Submission guardrails:** Check required facts, form values,
    duplicate status, invoice selection, extraction confidence, and
    approval requirements before submission.
-   **Independent verification:** Re-read the saved record and compare
    it with the source invoice instead of relying only on the agent's
    claim.
-   **Run evidence:** Save step-by-step logs and screenshots for
    debugging and review.
-   **Multiple execution modes:** Local MLX model, offline heuristic
    policy, and optional Claude API mode.

## How It Works

1.  **Receive a task** --- The user enters a natural-language goal in
    the command line or Streamlit interface.
2.  **Find relevant PDFs** --- The agent searches the `data/invoices/`
    directory for matching invoice files.
3.  **Read and extract details** --- The PDF tools extract the fields
    needed for the payable, such as vendor, invoice number, amount, and
    due date.
4.  **Remember validated facts** --- Extracted facts are stored in the
    agent state for subsequent validation.
5.  **Check existing records** --- The agent consults the payables
    system to identify existing entries and avoid duplicate submissions.
6.  **Resolve uncertainty** --- The agent can ask the user to clarify
    ambiguous invoice selection, confirm uncertain details, or approve
    an invoice above the configured threshold.
7.  **Fill the web form** --- Playwright drives Chromium to enter the
    required values into the simulated payables application.
8.  **Apply guardrails** --- Code-enforced checks run before submission
    to prevent missing or inconsistent fields and other prohibited
    actions.
9.  **Verify the outcome** --- The verifier reads the system state again
    and compares the saved record with the source PDF.
10. **Report the result** --- The agent returns a status and summary,
    with logs and screenshots available for inspection.

## Architecture

``` text
Natural-language task
        |
        v
Agent loop (agent/loop.py)
        |
        +--> Brain / action policy (agent/brains.py)
        |       |-- Local MLX Mistral + safety controller
        |       |-- Offline heuristic policy
        |       `-- Optional Claude API brain
        |
        v
Guardrails (agent/guardrails.py)
        |
        v
Tool registry (tools/registry.py)
        |-- File search and PDF reading
        |-- Payables lookup and fact memory
        |-- Playwright browser interaction
        `-- Human clarification / approval
        |
        v
Simulated company payables app
(Flask + SQLite; company_app/)
        |
        v
Independent verifier (agent/verifier.py)
        |
        +--> Final status and checks
        `--> Run logs and screenshots (runs/)
```

### Main Components

  -----------------------------------------------------------------------
  Component                           Responsibility
  ----------------------------------- -----------------------------------
  `agent/loop.py`                     Coordinates the
                                      observe--decide--act workflow and
                                      tool execution.

  `agent/brains.py`                   Provides the supported brain
                                      implementations and local-model
                                      interaction.

  `agent/guardrails.py`               Enforces pre-submission safety and
                                      business-rule checks.

  `agent/state.py`                    Maintains facts and workflow state
                                      during a run.

  `agent/verifier.py`                 Independently checks the result
                                      against the payables system and
                                      source invoice.

  `agent/logger.py`                   Records workflow events and run
                                      evidence.

  `tools/file_tools.py`               Searches invoice files and reads
                                      PDF content.

  `tools/browser_tools.py`            Uses Playwright to interact with
                                      the web application.

  `tools/system_tools.py`             Provides system read-back and
                                      fact-memory tools.

  `tools/human_tools.py`              Supports user clarification and
                                      approval interactions.

  `company_app/`                      Local Flask payables application
                                      backed by SQLite.

  `streamlit_app.py`                  Web interface for running tasks and
                                      viewing progress and verification.

  `tests/`                            Workflow scenarios and test
                                      support.
  -----------------------------------------------------------------------

## Technology Stack

-   **Python** --- Agent logic, tools, and workflow orchestration.
-   **MLX / mlx-lm** --- Local language-model inference on supported
    Apple Silicon hardware.
-   **Mistral 7B Instruct (4-bit)** --- Default local model
    configuration.
-   **Streamlit** --- Interactive user interface.
-   **Playwright + Chromium** --- Browser automation.
-   **Flask** --- Simulated company payables web application.
-   **SQLite** --- Local payable-record storage.
-   **PDF extraction utilities** --- Reading invoice text for field
    extraction.

An optional Claude API brain is also available when configured with an
API key. The offline heuristic mode can be used to exercise the tools
and workflow without a language-model API.

## Requirements

-   Python 3.11 or a compatible Python version supported by the
    dependencies.
-   Chromium installed through Playwright.
-   For the local MLX brain: a compatible Apple Silicon Mac and
    `mlx-lm`.
-   For Claude API mode: a valid Anthropic API key configured in the
    environment.
-   Internet access may be required to install packages and download the
    model the first time. Once dependencies and the model are available
    locally, MLX inference runs locally.

## Setup

### 1. Extract the project and enter the directory

``` bash
cd ai-task-worker
```

### 2. Create and activate a virtual environment

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

``` bash
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

### 4. Install MLX support (Apple Silicon only)

``` bash
pip install mlx-lm
```

The default model is configured as:

``` text
mlx-community/Mistral-7B-Instruct-v0.3-4bit
```

If your shell has an older `MLX_MODEL` value exported, clear it before
launching the app so the configured default can be used:

``` bash
unset MLX_MODEL
```

### 5. Start the Streamlit interface

``` bash
streamlit run streamlit_app.py
```

Use the sidebar to select the execution mode and model. Enter a task in
the **Run agent** tab and press **Run**. If the agent requests
clarification or approval, respond in the interface. The UI displays the
action timeline, tool results, screenshots, final status, and
independent verification checks.

The project also includes a local payables application, typically
available at:

``` text
http://127.0.0.1:5055
```

Avoid running multiple copies of the command-line app and Streamlit app
at the same time if both need the same local port.

## Running from the Command Line

Run the offline test scenarios:

``` bash
python run_tests.py
```

Run the local MLX brain on a scenario:

``` bash
python main.py --brain mlx --scenario happy_path --auto-answer
```

Run a custom task with the local model:

``` bash
python main.py --brain mlx \
  "Find the latest invoice from Acme Supplies, extract the amount and due date, check for duplicates, and process it if permitted."
```

Run the offline heuristic policy:

``` bash
python main.py --brain heuristic --scenario happy_path --auto-answer
```

List available scenarios:

``` bash
python main.py --list-scenarios
```

Optional Claude API mode:

``` bash
cp .env.example .env
```

Add your Anthropic API key to `.env`, then run:

``` bash
python main.py --brain claude
```

Do not commit API keys or other secrets to version control.

## Example Tasks

The invoice folder contains sample PDFs from several vendors. Example
prompts include:

-   "Extract the vendor, invoice number, invoice date, due date, and
    total amount from `hooli_2201.pdf`. Do not submit anything yet."
-   "Review all invoices and report possible duplicates against existing
    payables. Do not modify records."
-   "Compare `initech_latest.pdf` and `initech_old.pdf` using the dates
    inside the PDFs, not just their filenames."
-   "Process the latest invoice from Globex if it is not a duplicate and
    all required fields can be validated."
-   "Audit all invoice PDFs and report invoices that need approval or
    clarification."

For financial workflows, start with read-only audit prompts before
enabling submission tasks.

## Guardrails and Verification

The project is designed to keep important checks in code rather than
relying exclusively on model instructions. Before a submission, the
workflow checks relevant conditions including:

-   Required invoice facts are available.
-   Values entered into the form match the remembered invoice facts.
-   The candidate is not already recorded as a duplicate.
-   The correct/latest invoice has been selected or ambiguity has been
    resolved.
-   Low-confidence extraction is confirmed when required.
-   Invoices above the configured approval threshold receive the
    required approval.

The default approval threshold in the project configuration is
**10,000** in the invoice's numeric amount units. The sample application
is for demonstration and does not provide real payment execution or
real-world authorization.

The final status is determined using independent verification. Possible
statuses include `COMPLETED`, `ALREADY_DONE`, `DECLINED_BY_USER`,
`NOT_COMPLETED`, `INCOMPLETE`, and `FAILED_VERIFICATION`.

## Testing and Evidence

Run the included test suite:

``` bash
python run_tests.py
```

The repository includes scenarios for normal processing, ambiguous
latest invoices, low-confidence PDF extraction, changed submit buttons,
temporary server errors, approval decisions, missing vendors, duplicate
records, and attempts to bypass safeguards.

Run artifacts are written under `runs/`, including run logs and
screenshots. The test report is written to `runs/TEST_REPORT.md` when
generated by the test runner.

**Testing note:** Local-model behavior depends on hardware, model
downloads, and model output. The MLX integration's parsing/plumbing
tests do not by themselves prove that every end-to-end task will succeed
with a real model. Validate actual runs on the target machine and review
the logs and verifier results before presenting performance claims.

## Limitations

-   This is a prototype that operates on a local simulated payables
    system; it is not connected to a production ERP, accounting
    platform, or bank.
-   PDF extraction quality depends on the structure and readability of
    each invoice. Scanned PDFs may require OCR support that is not
    included in every workflow.
-   A compact local language model can produce invalid tool calls or
    misunderstand ambiguous requests. The safety controller constrains
    actions, but it does not eliminate all model or software failures.
-   Vendor names, filenames, and invoice numbers are different
    identifiers. A user-provided filename should be resolved to the
    corresponding PDF before vendor-specific processing.
-   The local MLX brain requires compatible Apple Silicon hardware.
    Claude API mode requires credentials and may incur API costs.
-   Approval thresholds and workflow rules are configurable
    demonstration rules and should be reviewed before adaptation to any
    real business process.

## Future Enhancements

-   Add OCR for scanned invoices and improve extraction confidence
    scoring.
-   Support more invoice layouts and structured extraction with
    field-level evidence.
-   Add configurable vendor policies, currencies, approval routing, and
    audit trails.
-   Improve filename, vendor-name, and invoice-number resolution.
-   Add robust recovery for ambiguous matches, missing fields, and
    changing web forms.
-   Expand automated tests and benchmark real-model success rates across
    repeated runs.
-   Integrate with authorized production accounting systems only after
    security, access control, and compliance review.

## Security and Responsible Use

-   Use only test or appropriately authorized invoice data.
-   Keep API keys and credentials out of source control and run logs.
-   Review invoice details and approvals before submission.
-   Do not use the prototype to initiate real payments or make
    production financial decisions without a proper security,
    reliability, and compliance assessment.

## Project Structure

``` text
ai-task-worker/
├── agent/                 # Agent loop, brains, guardrails, state, verifier, logging
├── company_app/            # Simulated Flask payables application and SQLite database
├── data/
│   └── invoices/           # Sample invoice PDFs
├── runs/                   # Run logs, screenshots, and test reports (generated)
├── scripts/                # Sample invoice generation utilities
├── tests/                  # Test scenarios and brain tests
├── tools/                  # File, browser, system, and human-interaction tools
├── config.py               # Runtime configuration
├── main.py                 # Command-line entry point
├── streamlit_app.py        # Streamlit user interface
├── run_tests.py            # Scenario test runner
├── requirements.txt        # Python dependencies
└── README.md
```

## License

No license is specified in the provided project files. Add the
appropriate license and attribution details before distributing the
project publicly or commercially.
