"""Real browser control via Playwright (Chromium)."""

import re
from pathlib import Path
from playwright.sync_api import sync_playwright
from .base import Tool, ToolResult


class Browser:
    def __init__(self, headless=True):
        self._pw = sync_playwright().start()
        self._b = self._pw.chromium.launch(headless=headless)
        self.page = self._b.new_page()
        self.page.set_default_timeout(8000)

    def close(self):
        try:
            self._b.close()
            self._pw.stop()
        except Exception:
            pass

    # ---- helpers used by guardrails/verifier ----
    def form_values(self) -> dict:
        try:
            return self.page.evaluate(
                "() => Object.fromEntries([...document.querySelectorAll('form input')].map(i=>[i.name,i.value]))"
            )
        except Exception:
            return {}

    def is_submit(self, selector: str) -> bool:
        try:
            return self.page.evaluate(
                "(s)=>{const e=document.querySelector(s);return !!e && (e.type==='submit' || (e.tagName==='BUTTON' && !!e.closest('form')))}",
                selector,
            )
        except Exception:
            return False

    def snapshot(self) -> dict:
        p = self.page
        return {
            "url": p.url,
            "title": p.title(),
            "text": re.sub(r"\n{2,}", "\n", p.inner_text("body"))[:1800],
            "alerts": [e.inner_text() for e in p.query_selector_all("[role=alert], [role=status]")],
            "inputs": p.evaluate(
                "()=>[...document.querySelectorAll('input,select,textarea')].map(i=>({selector:'#'+i.id,name:i.name,value:i.value}))"
            ),
            "buttons": p.evaluate(
                "()=>[...document.querySelectorAll('button,input[type=submit],a')].map((b,i)=>({selector:b.id?'#'+b.id:(b.getAttribute('href')?'a[href=\"'+b.getAttribute('href')+'\"]':(b.type==='submit'?'button[type=\"submit\"]':b.tagName.toLowerCase()+':nth-of-type('+(i+1)+')')),text:(b.innerText||b.value||'').trim(),type:b.type||b.tagName.toLowerCase()}))"
            ),
        }


def _guard(fn):
    def wrapper(ctx, **kw):
        try:
            return fn(ctx, **kw)
        except Exception as e:
            msg = str(e).split("\n")[0][:300]
            return ToolResult(
                False,
                error=f"Browser action failed: {msg}",
                hint="Call read_page to see which selectors/buttons actually exist, then adapt.",
            )

    return wrapper


@_guard
def open_page(ctx, url):
    r = ctx.browser.page.goto(url)
    return ToolResult(True, {"url": ctx.browser.page.url, "status": r.status if r else None})


@_guard
def read_page(ctx):
    return ToolResult(True, ctx.browser.snapshot())


@_guard
def type_text(ctx, selector, text):
    """Fill a real, visible form control and return actionable errors instead of waiting on bad selectors."""
    page = ctx.browser.page
    requested = str(selector or "").strip()
    value = str(text if text is not None else "")

    # Fail closed: small local LLMs sometimes literally type placeholders such as
    # "<amount>" or "<due_date>". Never put these into a real payable form.
    placeholder = value.strip().casefold()
    if not placeholder or (placeholder.startswith("<") and placeholder.endswith(">")) or placeholder in {
        "amount", "due_date", "invoice_no", "vendor", "<amount>", "<due_date>",
        "<invoice_no>", "<vendor>", "tbd", "n/a"
    }:
        return ToolResult(
            False,
            error=f"Refusing to type an empty or placeholder value into {requested!r}: {value!r}.",
            hint="Read the invoice PDF, remember the extracted field, and type the actual value. Never submit placeholders.",
        )

    if page.url == "about:blank":
        return ToolResult(
            False,
            error="Browser is on about:blank; the form is not open.",
            hint="Call open_page with the configured New Payable URL, then read_page.",
        )
    if not requested or ("<" in requested and ">" in requested):
        return ToolResult(
            False,
            error=f"Invalid placeholder selector: {requested!r}.",
            hint="Call read_page and use a real selector from its inputs list.",
        )

    try:
        field = page.locator(requested)
        count = field.count()
        if count == 0:
            available = page.evaluate(
                "() => [...document.querySelectorAll('input,select,textarea')].map(e => ({id:e.id,name:e.name,type:e.type||e.tagName.toLowerCase(),label:e.labels?.[0]?.innerText?.trim()||''}))"
            )
            return ToolResult(
                False,
                error=f"No field matches selector {requested!r}.",
                hint=f"Use only existing fields from read_page. Available fields: {available}",
            )
        if count > 1:
            return ToolResult(
                False,
                error=f"Selector {requested!r} matches {count} elements; it must be unique.",
                hint="Use a unique id or selector from read_page.",
            )

        field.wait_for(state="visible", timeout=8000)
        if not field.is_enabled():
            return ToolResult(False, error=f"Field {requested!r} is disabled.", hint="Read the page and check whether the form is ready.")
        field.fill(value, timeout=8000)
        actual = field.input_value(timeout=2000) if field.evaluate("e => e.tagName === 'INPUT' || e.tagName === 'TEXTAREA'") else value
        if actual != value:
            return ToolResult(False, error=f"Field {requested!r} did not retain the requested value.", hint="Read the page and inspect field type and validation messages.")
        return ToolResult(True, {"typed": value, "into": requested, "verified": True})
    except Exception as e:
        msg = str(e).split("\n")[0][:240]
        return ToolResult(
            False,
            error=f"Could not fill {requested!r}: {msg}",
            hint="Call read_page, confirm the current URL and actual field selector, then retry once with a real visible input.",
        )


@_guard
def click(ctx, selector):
    """Click a real page element; recover from common LLM placeholder selectors safely."""
    page = ctx.browser.page
    requested = str(selector or "").strip()

    # LLMs sometimes emit illustrative placeholders instead of a real selector.
    # Never pass those strings to Playwright as CSS selectors.
    placeholder = (
        not requested
        or ("<" in requested and ">" in requested)
        or "submit_button_selector" in requested.lower()
        or requested.lower() in {"submit button", "the submit button", "button selector"}
    )
    if page.url == "about:blank":
        return ToolResult(
            False,
            error="Browser is on about:blank; open the payables page before clicking.",
            hint="Call open_page with the configured payables form URL, then read_page and use a real selector.",
        )

    actual_selector = requested
    if placeholder:
        # Prefer the known app submit button ID; otherwise use a unique submit button.
        if page.locator("#submit-btn").count() == 1:
            actual_selector = "#submit-btn"
        elif page.locator("button[type='submit']").count() == 1:
            actual_selector = "button[type='submit']"
        elif page.locator("input[type='submit']").count() == 1:
            actual_selector = "input[type='submit']"
        else:
            return ToolResult(
                False,
                error=f"Invalid placeholder selector {requested!r}; could not identify one unique submit button.",
                hint="Call read_page and use one of the real selectors returned in the buttons list.",
            )

    page.locator(actual_selector).click()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=2000)
    except Exception:
        # Some form submissions update the page without a full navigation.
        pass
    snap = ctx.browser.snapshot()
    return ToolResult(
        True,
        {"clicked": actual_selector, "requested_selector": requested, "url": snap["url"], "alerts": snap["alerts"]},
    )


@_guard
def screenshot(ctx, name="shot"):
    d = Path(ctx.shots_dir)
    d.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w-]", "_", name)
    f = d / f"{safe_name}.png"
    ctx.browser.page.screenshot(path=str(f))
    ctx.state.evidence.append(str(f))
    return ToolResult(True, {"saved": str(f)})


S = lambda props, req: {"type": "object", "properties": props, "required": req}
TOOLS = [
    Tool("open_page", "Open a URL in the browser.", S({"url": {"type": "string"}}, ["url"]), open_page),
    Tool(
        "read_page",
        "Read the current page: text, alerts/errors, input fields and buttons (with selectors).",
        S({}, []),
        read_page,
    ),
    Tool(
        "type_text",
        "Type text into the field matching a CSS selector (replaces existing value).",
        S({"selector": {"type": "string"}, "text": {"type": "string"}}, ["selector", "text"]),
        type_text,
    ),
    Tool(
        "click",
        "Click the element matching a CSS selector. Clicking a form submit button is irreversible and is guarded.",
        S({"selector": {"type": "string"}}, ["selector"]),
        click,
    ),
    Tool(
        "screenshot",
        "Save a screenshot of the current page as evidence.",
        S({"name": {"type": "string"}}, ["name"]),
        screenshot,
    ),
]
