"""Drive NaC VXLAN Builder through the guided tour and save screenshots to docs/tour/shots/.

Starts its own copy of the app on port 8601 with throwaway History, fabric store and export folders,
so it never touches your real data. Needs Playwright with Chrome:

    pip install playwright pillow reportlab && python docs/tour/capture.py && python docs/tour/build_pdf.py
"""

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent
SHOTS = HERE / "shots"
PORT = 8601
BASE = f"http://localhost:{PORT}"
SHOTS.mkdir(exist_ok=True)


def start_app(tmp: Path) -> subprocess.Popen:
    env = {**os.environ, "NACB_HISTORY_DIR": str(tmp / "history"), "NACB_FABRICS_DIR": str(tmp / "fabrics"),
           "NACB_EXPORT_DIR": str(tmp / "export")}
    streamlit = APP / ".venv" / "bin" / "streamlit"
    proc = subprocess.Popen([str(streamlit), "run", str(APP / "app.py"), "--server.port", str(PORT),
                             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                            cwd=APP, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE, timeout=1)
            return proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise SystemExit("the app didn't start")


def idle(page, ms=1200):
    page.wait_for_timeout(300)
    try:
        page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def shot(page, name, top_text=None, bottom_text=None, max_h=None):
    """Screenshot of the main column; optionally only from `top_text` down to just above `bottom_text`."""
    page.mouse.move(2, 2)
    h = page.evaluate("() => document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
    page.set_viewport_size({"width": 1440, "height": min(max(int(h) + 40, 900), 5000)})
    idle(page, 700)
    box = page.locator('[data-testid="stMainBlockContainer"]').bounding_box()
    x, w = box["x"] + 16, box["width"] - 32
    y0, y1 = box["y"] + 24, box["y"] + box["height"]
    main = page.locator('[data-testid="stMain"]')  # not the sidebar, which repeats page names
    if top_text:
        y0 = main.get_by_text(top_text, exact=False).first.bounding_box()["y"] - 14
    if bottom_text:
        y1 = main.get_by_text(bottom_text, exact=False).first.bounding_box()["y"] - 10
    if max_h:
        y1 = min(y1, y0 + max_h)
    page.screenshot(path=str(SHOTS / f"{name}.png"), clip={"x": x, "y": y0, "width": w, "height": max(60, y1 - y0)})
    page.set_viewport_size({"width": 1440, "height": 900})
    idle(page, 300)
    print("saved", name)


def header_shot(page, name):
    bar = page.locator('[data-testid="stLayoutWrapper"]:has(> .st-key-nacb_header)').first
    bar.screenshot(path=str(SHOTS / f"{name}.png"))
    print("saved", name)


def nav(page, title):
    page.locator('[data-testid="stSidebarNav"]').get_by_text(title, exact=True).click()
    idle(page)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        proc = start_app(Path(tmp))
        try:
            run()
        finally:
            proc.terminate()


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme="light")
        page.goto(BASE)
        page.evaluate("() => localStorage.clear()")  # system theme = light here
        page.goto(f"{BASE}/standards_editor")
        idle(page, 2500)

        # 1. Demo mode
        page.get_by_role("tab", name="Demo mode").click()
        idle(page, 600)
        page.get_by_role("button", name="Load demo fabric").click()
        idle(page, 2500)
        shot(page, "01-demo", top_text="Load a simulated fabric")

        # 2. Header and the Fabric page
        nav(page, "1. Fabric")
        header_shot(page, "02-header")
        shot(page, "03-fabric", top_text="Fabric name, design standard", bottom_text="Management services")

        # 3. Switches and topology
        nav(page, "2. Switches")
        shot(page, "04-switches", max_h=1500)
        nav(page, "10. Topology")
        page.wait_for_timeout(1500)
        shot(page, "05-topology")

        # 4. Networks
        nav(page, "8. Networks")
        shot(page, "06-networks", max_h=1100)

        # 5. Day-2: provision ports, click a port, change it, preview
        nav(page, "Day-2 tasks")
        page.get_by_role("tab", name="Provision ports").click()
        idle(page, 1500)
        frame = page.frame_locator('iframe[title*="nacb_portmap"]').first
        frame.locator('[data-switch="demo-leaf-compute1"][data-port="5"]').click()
        idle(page, 2000)
        shot(page, "07-port-panel", top_text="Port map", max_h=1250)
        # an unused port starts as an access port on the first VLAN
        page.get_by_role("textbox", name="Description").last.fill("esx-07")
        page.get_by_role("button", name="Preview changes").click()
        idle(page, 3500)
        shot(page, "08-port-preview", top_text="Preview: Port")
        page.get_by_role("button", name="Apply").click()
        idle(page, 2000)

        # 6. Review & export
        nav(page, "12. Review & export")
        page.get_by_role("button", name="Run nac-validate").click()
        idle(page, 3000)
        shot(page, "09-review", bottom_text="Files")

        # 7. Clone the fabric, then the header switcher
        page.get_by_text("Make a copy of this fabric under a new name").click()
        idle(page, 800)
        shot(page, "10-clone", top_text="Clone fabric")
        page.get_by_role("button", name="Clone fabric").click()
        idle(page, 3000)
        page.locator(".st-key-nacb_header").get_by_role("combobox").click()
        page.wait_for_timeout(800)
        page.screenshot(path=str(SHOTS / "11-switcher.png"), clip={"x": 300, "y": 0, "width": 1140, "height": 330})
        print("saved 11-switcher")
        page.keyboard.press("Escape")
        idle(page, 500)

        # 8. Fabric instances
        nav(page, "1. Fabric")
        shot(page, "12-instances", top_text="Clear fabric")

        # 9. Design standards editor
        nav(page, "Design standards (dev)")
        page.get_by_text("I understand: let me edit the design standards").click()
        idle(page, 1000)
        shot(page, "13-standards", top_text="For developers only", max_h=1800)

        # 10. History
        nav(page, "History")
        shot(page, "14-history", max_h=1000)

        # 11. Dark mode
        page.locator('iframe[srcdoc*="stActiveTheme"]').first.content_frame.locator("button").click()
        idle(page, 3500)
        nav(page, "Day-2 tasks")
        page.get_by_role("tab", name="Provision ports").click()
        idle(page, 1500)
        shot(page, "15-dark", max_h=1500)
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
