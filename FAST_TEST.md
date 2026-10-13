# Fast local test

Use the deterministic heuristic brain for the quickest repeatable test. It does not load the MLX model, so it avoids model download/loading and LLM hallucinations.

```bash
source .venv/bin/activate
python run_tests.py --only happy_path --brain heuristic --quiet
```

Expected: `PASS 1/1 happy_path` and exit code 0. The test starts the local payables app, resets the test database, runs the invoice workflow, and verifies the saved record through the app API.

To run all built-in scenarios:

```bash
python run_tests.py --brain heuristic --quiet
```

For the interactive local LLM app, use `streamlit run streamlit_app.py`. The MLX brain is probabilistic; no agent can guarantee zero errors in every possible environment, so always verify the final record.
