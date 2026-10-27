"""Static screenshot gallery for the portfolio's "try it" section.

Drives the local portal (localhost:8096) with headless Chromium at phone width
and writes PNGs into assets/shots/. Nothing here is public: the portal, the labs
and their tokens live on the author's machine. The script only reads token files
from disk; it never prints them.

Before every screenshot it asserts that the visible page text contains no token,
no tunnel hostname and no non-loopback IPv4 address, and it masks anything that
looks like a 32-byte hex key (the lab's well-known anvil dev key). A screenshot
that would leak any of those fails the run instead of being written.

    /tmp/pwenv/bin/python scripts/shots.py

Exit status is the number of problems found.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PORTAL = "http://localhost:8096"
LABS = ["portal", "ckad-sim", "cka-lab", "sec-lab", "chain-lab", "ai-roadmap", "review"]
TOKENS = [t for t in ((Path("/root") / lab / "token.txt").read_text().strip()
                      for lab in LABS if (Path("/root") / lab / "token.txt").exists()) if t]
OUT = Path(__file__).resolve().parents[1] / "assets" / "shots"
OUT.mkdir(parents=True, exist_ok=True)

IPV4 = re.compile(r"\b(?!127\.)(?:\d{1,3}\.){3}\d{1,3}\b")
HOSTS = re.compile(r"trycloudflare\.com|cfargotunnel|\.ngrok\.", re.I)

MASK_KEYS_JS = """() => {
  const re = /0x[0-9a-fA-F]{64}/g;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n, hits = 0;
  while ((n = w.nextNode())) {
    if (re.test(n.nodeValue)) { n.nodeValue = n.nodeValue.replace(re, '0x<key masked>'); hits++; }
  }
  for (const el of document.querySelectorAll('input, textarea')) {
    if (re.test(el.value)) { el.value = el.value.replace(re, '0x<key masked>'); hits++; }
  }
  return hits;
}"""

VISIBLE_TEXT_JS = """() => {
  const parts = [document.body.innerText || ''];
  for (const el of document.querySelectorAll('input, textarea')) parts.push(el.value || '');
  return parts.join('\\n');
}"""


def scroll_to(page, selector: str, offset: int = 64) -> bool:
    found = page.evaluate(
        """([sel, off]) => { const el = document.querySelector(sel); if (!el) return false;
           el.scrollIntoView({block: 'start'}); window.scrollBy(0, -off); return true; }""",
        [selector, offset])
    page.wait_for_timeout(250)
    return bool(found)


def scroll_to_label(page, pattern: str, offset: int = 64) -> bool:
    found = page.evaluate(
        """([pat, off]) => { const re = new RegExp(pat, 'i');
           const el = [...document.querySelectorAll('.lbl')].find(e => re.test(e.textContent));
           if (!el) return false; el.scrollIntoView({block: 'start'}); window.scrollBy(0, -off); return true; }""",
        [pattern, offset])
    page.wait_for_timeout(250)
    return bool(found)


def main() -> int:
    problems: list[str] = []
    posts: list[str] = []
    shots: list[dict] = []

    def snap(page, name: str, full_page: bool = False) -> None:
        page.evaluate("() => { const s = document.getElementById('share'); if (s) s.style.display = 'none'; }")
        masked = page.evaluate(MASK_KEYS_JS)
        text = page.evaluate(VISIBLE_TEXT_JS)
        leaks = []
        for tok in TOKENS:
            if tok in text:
                leaks.append("token")
        if HOSTS.search(text):
            leaks.append("tunnel hostname")
        if IPV4.search(text):
            leaks.append("non-loopback ip")
        if leaks:
            problems.append(f"{name}: would leak {sorted(set(leaks))}; not written")
            return
        path = OUT / f"{name}.png"
        page.screenshot(path=str(path), full_page=full_page)
        shots.append({"file": path.name, "bytes": path.stat().st_size, "keys_masked": masked,
                      "title": page.title(), "view": page.text_content("#main .lbl").strip()
                      if page.query_selector("#main .lbl") else None})

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 414, "height": 896}, device_scale_factor=2,
                                  is_mobile=True, has_touch=True, color_scheme="dark")
        page = ctx.new_page()
        page.on("request", lambda r: posts.append(f"{r.method} {r.url.replace(PORTAL, '')}")
                if r.method != "GET" else None)
        portal_token = (Path("/root/portal/token.txt")).read_text().strip()

        # 01 portal dashboard: one URL in front of every track
        page.goto(f"{PORTAL}/#token={portal_token}", wait_until="load")
        page.wait_for_selector("#app:not(.hidden)", timeout=20000)
        page.wait_for_function("document.querySelectorAll('#tracks a.row').length >= 5", timeout=20000)
        if "token=" in page.url:
            problems.append("dashboard: token still in the address bar")
        snap(page, "01-portal-dashboard")

        # 02 + 03 ckad-sim: drill list, then one drill with its tap actions
        page.goto(f"{PORTAL}/ckad/", wait_until="load")
        page.wait_for_selector("#app:not(.hidden)", timeout=30000)
        page.wait_for_selector("#navDrills", state="visible", timeout=30000)
        page.click("#navDrills")
        page.wait_for_function("document.querySelectorAll('#main button.row').length > 0", timeout=30000)
        snap(page, "02-ckad-drills")
        page.click("#main button.row")
        page.wait_for_selector("#main h1.t", timeout=30000)
        page.wait_for_timeout(600)
        scroll_to_label(page, "action") or scroll_to(page, "#main h1.t")
        snap(page, "03-ckad-drill")

        # 04 ckad-sim: timed exam lobby
        page.click("#navExam")
        page.wait_for_timeout(800)
        snap(page, "04-ckad-exam")

        # 05 cka-lab: drill list
        page.goto(f"{PORTAL}/cka/", wait_until="load")
        page.wait_for_selector("#app:not(.hidden)", timeout=30000)
        page.wait_for_selector("#navDrills", state="visible", timeout=30000)
        page.click("#navDrills")
        page.wait_for_function("document.querySelectorAll('#main button.row').length > 0", timeout=30000)
        snap(page, "05-cka-drills")

        # 06 + 07 sec-lab: lesson path, then the exercise runner and the flag lab of one lesson
        page.goto(f"{PORTAL}/sec/", wait_until="load")
        page.wait_for_selector("#app:not(.hidden)", timeout=30000)
        page.wait_for_function("document.querySelectorAll('#main button.row').length > 0", timeout=30000)
        snap(page, "06-sec-path")
        # a hash-only change is not a navigation, so reload to let the deep link fire on boot
        page.goto(f"{PORTAL}/sec/#lesson=s08", wait_until="load")
        page.reload(wait_until="load")
        page.wait_for_selector("#main h1.t", timeout=30000)
        page.wait_for_timeout(800)
        if scroll_to(page, "#exercise"):
            snap(page, "07-sec-exercise")
        else:
            problems.append("sec: no #exercise block on s08")
        if scroll_to(page, "#lab"):
            snap(page, "08-sec-flag-lab")
        else:
            problems.append("sec: no #lab block on s08")

        # 09 chain-lab: the attack block of the reentrancy lesson
        page.goto(f"{PORTAL}/chain/#lesson=chain-reentrancy", wait_until="load")
        page.reload(wait_until="load")
        page.wait_for_selector("#main h1.t", timeout=30000)
        page.wait_for_timeout(800)
        if page.query_selector("#lab button.row"):
            page.click("#lab button.row")
            page.wait_for_timeout(600)
        if scroll_to(page, "#lab"):
            snap(page, "09-chain-attack")
        else:
            problems.append("chain: no #lab block on chain-reentrancy")

        # 10 ai-roadmap: a lesson with an executable lab
        page.goto(f"{PORTAL}/ai/#lesson=a02", wait_until="load")
        page.reload(wait_until="load")
        page.wait_for_selector("#main h1.t", timeout=30000)
        page.wait_for_timeout(800)
        if scroll_to(page, "#lab"):
            snap(page, "10-ai-lab")
        else:
            problems.append("ai: no #lab block on a02")

        browser.close()

    # /api/session plants the portal cookie; ckad's /api/objects is a kubectl get behind a POST body
    mutating = [u for u in posts if not u.endswith(("/api/session", "/ckad/api/objects"))]
    if mutating:
        problems.append(f"non-GET requests other than /api/session: {mutating}")
    print(json.dumps({"shots": shots, "non_get_requests": posts, "problems": problems}, indent=2))
    print("\nRESULT:", "PASS" if not problems else "FAIL: " + "; ".join(problems))
    return len(problems)


if __name__ == "__main__":
    sys.exit(main())
