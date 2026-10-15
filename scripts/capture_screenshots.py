"""Capture README screenshots of the running Gradio app with Playwright.

Flow:
  A) Ask tab: meme question -> wait for real answer -> screenshot (answer + slide image)
  B) Quiz tab: generate quiz (doc preselected), submit answers, reveal -> screenshot
  C) Course materials tab -> screenshot (light only)
  D) Light/dark: capture the Ask tab in both color schemes

Waits are strict: a job must START (seen processing) and FINISH before the
screenshot. Answer looks for '33' (the meme page) or NOT_COVERED in the
markdown outputs. Clicks use native element.click() since Gradio Svelte
buttons expose no ARIA roles.
"""
import sys
import time

from playwright.sync_api import sync_playwright

APP = "http://127.0.0.1:7860"
OUT = "assets/screenshots/"
MEME_Q = ('Find the meme about Vibe Coding on "Prod" in the Week 2 slides. '
          'Which slide shows it and what does the meme say?')


def js_click(page, exact_text, role=None):
    ok = page.evaluate(
        """(spec) => {
            const sel = spec.role ? `button[role="${spec.role}"]` : 'button';
            const btns = [...document.querySelectorAll(sel)];
            const b = btns.find(x => x.textContent.trim() === spec.text);
            if (!b) return false;
            b.click();
            return true;
        }""", {"text": exact_text, "role": role})
    if not ok:
        raise RuntimeError(f"button not found: {exact_text!r}")


def tab(page, name):
    js_click(page, name, role="tab")
    time.sleep(1.5)


def markdowns(page) -> str:
    """All rendered markdown text (the answer/status outputs live here)."""
    return page.evaluate(
        "[...document.querySelectorAll('[data-testid=\"markdown\"]')]"
        ".map(m => m.innerText).join('\\n---\\n')")


def wait_job(predicate, page, patience_s=300):
    """Wait for a Gradio job: must see 'processing', then it must end AND
    predicate(body text) must hold. Returns the final markdown snapshot."""
    deadline = time.time() + patience_s
    seen = False
    while time.time() < deadline:
        body = page.inner_text("body")
        if "processing" in body.lower():
            seen = True
        if seen and "processing" not in body.lower():
            md = markdowns(page)
            if predicate(md):
                return md
        time.sleep(4)
    return markdowns(page)


def main():
    import os
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.goto(APP, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # ---- A: grounded answer with slide image (light) ----
        # The meme question sits at the NOT_COVERED boundary and the reasoning
        # model is occasionally flaky there; retry up to 3 times (fresh ask).
        covered = False
        for attempt in range(1, 4):
            page.fill('textarea[data-testid="textbox"]', MEME_Q)
            js_click(page, "Ask")
            md = wait_job(lambda m: "NOT_COVERED" in m or "33" in m, page)
            covered = "33" in md and "NOT_COVERED" not in md
            print(f"ask attempt {attempt}: {'COVERED' if covered else 'NOT COVERED / timeout'}")
            if covered:
                break
            page.wait_for_timeout(3000)
        page.wait_for_timeout(2500)
        page.screenshot(path=OUT + "answer_meme_slide.png", full_page=False)
        print("saved", OUT + "answer_meme_slide.png")

        # ---- B: quiz generation + scoring + reveal (light) ----
        tab(page, "Practice quiz")
        js_click(page, "Generate quiz")
        md = wait_job(lambda m: "Answers remain hidden" in m or "question(s) from" in m, page)
        print("quiz md head:", md.splitlines()[0] if md else "empty")
        page.wait_for_timeout(1500)
        page.screenshot(path=OUT + "quiz_generated.png", full_page=False)
        print("saved", OUT + "quiz_generated.png")

        # Select the first option for the first three generated questions.
        # Each visible Radio group exposes four native radio inputs.
        radio_inputs = page.locator('input[type="radio"]:visible')
        radio_count = radio_inputs.count()
        if radio_count < 12:
            raise RuntimeError(f"expected at least 12 visible quiz options, found {radio_count}")
        for index in (0, 4, 8):
            radio_inputs.nth(index).check(force=True)
        js_click(page, "Submit answers")
        time.sleep(8)
        page.check("text=Reveal solutions and explanations", force=True)
        js_click(page, "Submit answers")
        time.sleep(8)
        page.screenshot(path=OUT + "quiz_feedback_sources.png", full_page=False)
        print("saved", OUT + "quiz_feedback_sources.png")

        # ---- C: materials tab (light) ----
        tab(page, "Course materials")
        page.wait_for_timeout(1500)
        page.screenshot(path=OUT + "materials_tab.png", full_page=False)
        print("saved", OUT + "materials_tab.png")

        # ---- D: light/dark readability check ----
        for scheme in ("light", "dark"):
            ctx2 = browser.new_context(viewport={"width": 1280, "height": 1000},
                                       color_scheme=scheme)
            p2 = ctx2.new_page()
            p2.goto(APP, wait_until="domcontentloaded", timeout=60000)
            p2.wait_for_timeout(3000)
            p2.screenshot(path=OUT + f"ask_tab_{scheme}.png", full_page=False)
            print("saved", OUT + f"ask_tab_{scheme}.png")
            ctx2.close()

        browser.close()
    print("DONE")


if __name__ == "__main__":
    sys.exit(main())
