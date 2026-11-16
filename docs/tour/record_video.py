"""Record docs/nac-vxlan-builder-walkthrough.mp4: a narrated (captioned) walkthrough of the app.

Starts its own copy of the app (throwaway data, like capture.py), drives it with Playwright while
recording the browser, shows a caption bar and a visible cursor for each step, then converts the
recording to H.264 MP4. Needs Playwright with Chrome and its ffmpeg (`playwright install ffmpeg`),
plus imageio-ffmpeg for the MP4 conversion:

    pip install playwright imageio-ffmpeg && playwright install ffmpeg
    python docs/tour/record_video.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture  # noqa: E402  (reuses its app start-up and helpers)

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "nac-vxlan-builder-walkthrough.mp4"
SIZE = {"width": 1440, "height": 900}

OVERLAY_JS = """
([title, text]) => {
  let bar = document.getElementById('nacb-caption');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'nacb-caption';
    bar.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483647;' +
      'max-width:1100px;padding:14px 22px;border-radius:12px;background:rgba(17,24,39,.92);color:#fff;' +
      'font:16px/1.4 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.35);' +
      'transition:opacity .3s';
    document.body.appendChild(bar);
  }
  bar.innerHTML = '<div style="font-weight:700;font-size:18px;margin-bottom:2px">' + title + '</div>' + text;
  bar.style.opacity = '1';
}
"""
CARD_JS = """
([title, sub]) => {
  let c = document.getElementById('nacb-card');
  if (!c) {
    c = document.createElement('div');
    c.id = 'nacb-card';
    c.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:flex;flex-direction:column;' +
      'align-items:center;justify-content:center;background:#0f172a;color:#fff;text-align:center;' +
      'font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;transition:opacity .5s';
    document.body.appendChild(c);
  }
  c.innerHTML = '<div style="font-size:52px;font-weight:800">' + title + '</div>' +
                '<div style="font-size:22px;opacity:.8;margin-top:14px;max-width:900px">' + sub + '</div>';
  c.style.opacity = '1';
}
"""
CURSOR_JS = """
([x, y]) => {
  let d = document.getElementById('nacb-cursor');
  if (!d) {
    d = document.createElement('div');
    d.id = 'nacb-cursor';
    d.style.cssText = 'position:fixed;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;' +
      'background:rgba(255,75,75,.35);border:2px solid #ff4b4b;z-index:2147483647;pointer-events:none;' +
      'transition:left .6s ease,top .6s ease;left:720px;top:450px';
    document.body.appendChild(d);
  }
  d.style.left = x + 'px'; d.style.top = y + 'px';
}
"""


class Director:
    def __init__(self, page):
        self.page = page

    def wait(self, ms):
        self.page.wait_for_timeout(ms)

    def say(self, title, text, ms=3500):
        self.page.evaluate(OVERLAY_JS, [title, text])
        self.wait(ms)

    def card(self, title, sub, ms=3500):
        self.page.evaluate(CARD_JS, [title, sub])
        self.wait(ms)
        self.page.evaluate("() => { const c = document.getElementById('nacb-card'); if (c) c.remove(); }")

    def point(self, locator, click=True, ms=700):
        """Move the visible cursor to an element (scrolling it into view), then click it."""
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.page.evaluate(CURSOR_JS, [x, y])
        self.wait(ms)
        if click:
            self.page.mouse.click(x, y)
            capture.idle(self.page, 900)

    def point_in_frame(self, frame_el, inner, ms=700):
        """Same, for an element inside an iframe (the port map)."""
        frame_el.scroll_into_view_if_needed()
        fb = frame_el.bounding_box()
        ib = frame_el.content_frame.locator(inner).bounding_box()
        x, y = ib["x"] + ib["width"] / 2, ib["y"] + ib["height"] / 2  # already page coordinates
        self.page.evaluate(CURSOR_JS, [x, y])
        self.wait(ms)
        self.page.mouse.click(x, y)
        capture.idle(self.page, 1500)
        return fb

    def scroll(self, dy, ms=1200):
        self.page.evaluate("dy => document.querySelector('[data-testid=\"stMain\"]').scrollBy({top: dy, behavior: 'smooth'})", dy)
        self.wait(ms)

    def top(self):
        self.page.evaluate("() => document.querySelector('[data-testid=\"stMain\"]').scrollTo({top: 0})")
        self.wait(300)

    def hide(self):
        self.page.evaluate("() => { const b = document.getElementById('nacb-caption'); if (b) b.style.opacity = '0'; }")

    def nav(self, title):
        self.hide()  # a step's caption shouldn't linger over the next page
        self.point(self.page.locator('[data-testid="stSidebarNav"]').get_by_text(title, exact=True))
        capture.idle(self.page, 800)
        self.top()


def record(video_dir: Path) -> Path:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(video_dir), record_video_size=SIZE,
                                  color_scheme="light")
        page = ctx.new_page()
        d = Director(page)
        page.goto(capture.BASE)
        page.evaluate("() => localStorage.clear()")
        page.goto(f"{capture.BASE}/standards_editor")
        capture.idle(page, 2000)

        d.card("NaC VXLAN Builder", "Build and edit Cisco Network as Code VXLAN EVPN data models "
               "(cisco.nac_dc_vxlan, Nexus Dashboard) without hand-editing YAML", 4500)

        # Demo mode
        d.say("1 · Demo mode", "Design standards → Demo mode loads a simulated fabric with sample values.")
        d.point(page.get_by_role("tab", name="Demo mode"))
        d.point(page.get_by_role("button", name="Load demo fabric"))
        capture.idle(page, 1500)
        d.say("1 · Demo mode", "demo-dc1 opens as its own fabric: 16 switches, two tenants, vPC host ports and VRF-lite. "
              "It can be exported or deleted here.", 4000)

        # Header + Fabric
        d.nav("1. Fabric")
        d.point(page.locator(".st-key-nacb_header"), click=False)
        d.say("2 · The header", "Always visible: the fabric you're editing, its standard, error count, the NaC version, "
              "a fabric switcher and a light/dark button.", 4500)
        d.scroll(380)
        d.say("2 · Design standards", "Settings the standard fixes are grayed out: fabric type, route reflectors, "
              "anycast MAC, overlay mode and more.", 4000)

        # Switches + topology
        d.nav("2. Switches")
        d.say("3 · Switches", "Counters check the fabric against its standard. Every switch has a Nexus 9300 model, so "
              "port numbering follows the hardware.", 3500)
        d.scroll(700, 2200)
        d.nav("10. Topology")
        capture.idle(page, 1200)
        d.say("4 · Topology", "Spines, compute and storage leaf pairs, three border pairs and the VRF-lite handoff.", 4000)

        # Day-2: click a port, edit, preview
        d.nav("Day-2 tasks")
        d.point(page.get_by_role("tab", name="Provision ports"))
        capture.idle(page, 1200)
        frame = page.locator('iframe[title*="nacb_portmap"]').first
        frame.scroll_into_view_if_needed()
        d.say("5 · Port map", "Each switch's front panel: green = enabled in the YAML, red = disabled, gray = not in "
              "the YAML. Click a port to edit it.", 4000)
        d.point_in_frame(frame, '[data-switch="demo-leaf-compute1"][data-port="5"]')
        panel = page.locator('[data-testid="stMain"]').get_by_text("Ethernet1/5 on demo-leaf-compute1")
        panel.scroll_into_view_if_needed()
        d.say("5 · Port settings", "Mode, enabled, edge port, description and VLANs. Only VLANs that are networks in "
              "the data model can be picked.", 3500)
        desc = page.get_by_role("textbox", name="Description").last
        d.point(desc)
        desc.type("esx-07", delay=120)
        d.point(page.get_by_role("button", name="Preview changes"))
        capture.idle(page, 2500)
        page.locator('[data-testid="stMain"]').get_by_text("Preview: Port").first.scroll_into_view_if_needed()
        d.say("6 · Preview", "Nothing changes until you apply: the preview lists the change and any new issues, and "
              "shows the port map afterwards (blue outline).", 4000)
        d.scroll(520, 1500)
        d.say("6 · Preview", "On macOS it also runs nac-validate on the result, and shows the YAML diff line by line.", 4000)
        d.scroll(450, 1500)
        d.point(page.get_by_role("button", name="Apply"))
        capture.idle(page, 1500)

        # Review & export, clone, switch
        d.nav("12. Review & export")
        d.point(page.get_by_role("button", name="Run nac-validate"))
        capture.idle(page, 2500)
        d.say("7 · Review & export", "Checks and nac-validate (schema and Cisco's rules), then download a zip or write to "
              "export/<fabric>/ or a NaC repo, with a diff first.", 4000)
        d.point(page.get_by_text("Make a copy of this fabric under a new name"))
        d.say("8 · Clone", "Clone copies the fabric under a new name and renames every switch everywhere it's used.", 3000)
        d.point(page.get_by_role("button", name="Clone fabric"))
        capture.idle(page, 2500)
        d.top()
        d.point(page.locator(".st-key-nacb_header").get_by_role("combobox"))
        d.say("8 · Switch fabrics", "Every fabric is saved as you go. The header's dropdown switches between them.", 3500)
        page.keyboard.press("Escape")
        capture.idle(page, 500)

        # Fabric instances
        d.nav("1. Fabric")
        d.scroll(5000, 1800)  # the box is at the bottom of the page
        d.point(page.locator('[data-testid="stMain"]').get_by_text("Fabric instances").first, click=False)
        d.say("9 · Fabric instances", "The Fabric page lists every saved fabric; tick some and type Yes to delete them.", 4000)

        # Dark mode
        d.top()
        toggle = page.locator('iframe[srcdoc*="stActiveTheme"]').first
        d.point(toggle, click=False)
        toggle.content_frame.locator("button").click()
        capture.idle(page, 3000)
        d.say("10 · Dark mode", "One click switches light and dark mode, and the browser remembers it.", 3500)

        d.card("NaC VXLAN Builder", "github.com/dcantor/nac-vxlan-builder · MIT license", 4000)
        video = Path(page.video.path())
        ctx.close()
        browser.close()
        return video


def to_mp4(webm: Path, out: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-preset", "slow",
                    "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)], check=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        proc = capture.start_app(Path(tmp))
        try:
            webm = record(Path(tmp) / "video")
            to_mp4(webm, OUT)
        finally:
            proc.terminate()
    print("wrote", OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    sys.exit(main())
