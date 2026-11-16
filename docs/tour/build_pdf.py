"""Build docs/nac-vxlan-builder-tour.pdf from the screenshots capture.py saved in docs/tour/shots/."""

import sys
from pathlib import Path

from PIL import Image, ImageChops
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent
SHOTS, TRIM = HERE / "shots", HERE / "trimmed"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "nac-vxlan-builder-tour.pdf"
TRIM.mkdir(exist_ok=True)
sys.path.insert(0, str(APP))

from nacbuilder import NAC_COLLECTION, NAC_VERSION, ND_VERSION, __version__  # noqa: E402
from nacbuilder.checks import check_project  # noqa: E402
from nacbuilder.demo import build_demo  # noqa: E402
from nacbuilder.generate import render_all  # noqa: E402

PAGE = landscape(letter)
MARGIN = 0.5 * inch
FRAME_W, FRAME_H = PAGE[0] - 2 * MARGIN, PAGE[1] - 2 * MARGIN

ss = getSampleStyleSheet()
INK, MUTED, ACCENT = colors.HexColor("#111827"), colors.HexColor("#4b5563"), colors.HexColor("#b91c1c")
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=INK,
                    spaceAfter=4)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK,
                    spaceBefore=6, spaceAfter=3)
BODY = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.5, leading=11, textColor=MUTED)
STEP = ParagraphStyle("step", parent=BODY, fontName="Helvetica-Bold", fontSize=9, textColor=ACCENT)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=12, bulletIndent=2)


def trim(name: str, pad: int = 20) -> Path:
    """Crop the plain margin around a screenshot (white, or dark for dark-mode shots)."""
    im = Image.open(SHOTS / f"{name}.png").convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((2, 2)))
    box = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    if box:
        left, top, right, bottom = box
        im = im.crop((max(0, left - pad), max(0, top - pad), min(im.width, right + pad), min(im.height, bottom + pad)))
    out = TRIM / f"{name}.png"
    im.save(out)
    return out


def img(name: str, max_w: float = FRAME_W, max_h: float = FRAME_H * 0.74) -> Table:
    path = trim(name)
    w, h = Image.open(path).size
    scale = min(max_w / w, max_h / h)
    pic = RLImage(str(path), width=w * scale, height=h * scale)
    t = Table([[pic]], style=[("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d1d5db")),
                              *[(k, (0, 0), (-1, -1), 4) for k in ("TOPPADDING", "BOTTOMPADDING", "LEFTPADDING",
                                                                    "RIGHTPADDING")]])
    t.hAlign = "CENTER"
    return t


def halves(name: str, max_h: float = FRAME_H * 0.74) -> Table:
    """A tall screenshot cut in two and shown side by side, so it stays readable."""
    path = trim(name)
    im = Image.open(path)
    cut = im.height // 2
    parts = []
    for i, box in enumerate(((0, 0, im.width, cut + 20), (0, cut - 20, im.width, im.height))):
        part = SHOTS / f"{name}_part{i}.png"
        im.crop(box).save(part)
        parts.append(img(part.stem, max_w=FRAME_W / 2 - 12, max_h=max_h))
    return two_up(*parts)


def two_up(left, right, gap=0.25 * inch):
    w = (FRAME_W - gap) / 2
    return Table([[left, right]], colWidths=[w + gap / 2] * 2,
                 style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), gap / 2)])


def grid(rows, widths, size=8.5):
    cell = ParagraphStyle("c", parent=SMALL, fontSize=size, leading=size + 2, textColor=INK)
    t = Table([[Paragraph(str(c), cell) for c in r] for r in rows], colWidths=widths)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def page(story, n, title, lead, body, notes=(), caption=None):
    story += [Paragraph(f"STEP {n}", STEP), Paragraph(title, H1), Paragraph(lead, BODY), Spacer(1, 6), body]
    if caption:
        story += [Spacer(1, 3), Paragraph(caption, SMALL)]
    if notes:
        story.append(Spacer(1, 4))
        story += [Paragraph(x, BULLET, bulletText="•") for x in notes]
    story.append(PageBreak())


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 0.3 * inch, "NaC VXLAN Builder · guided tour")
    canvas.drawRightString(PAGE[0] - MARGIN, 0.3 * inch, str(doc.page))
    canvas.restoreState()


demo = build_demo()
roles = {}
for s in demo.switches:
    k = f"{s.leaf_role} leafs" if s.leaf_role else (f"{s.border_set} borders" if s.border_set else f"{s.role}s")
    roles[k] = roles.get(k, 0) + 1
shut = sum(i.enabled is False for i in demo.interfaces)
code = lambda x: f"<font face='Courier'>{x}</font>"  # noqa: E731

story = [Spacer(1, 0.3 * inch),
         Paragraph("NaC VXLAN Builder", ParagraphStyle("t", parent=H1, fontSize=30, leading=34)),
         Paragraph("A guided tour of the app with its built-in demo fabric",
                   ParagraphStyle("s", parent=BODY, fontSize=13, leading=17, textColor=MUTED)),
         Spacer(1, 12),
         Paragraph(
             "NaC VXLAN Builder is a local Streamlit app that builds and edits the YAML data model for Cisco's "
             f"<b>Network as Code VXLAN EVPN</b> collection ({code(NAC_COLLECTION)} {NAC_VERSION}, Nexus Dashboard "
             f"{ND_VERSION}). Every screenshot here was taken from the running app (builder {__version__}), driven "
             "step by step by docs/tour/capture.py; the numbers below come from the same demo fabric.", BODY),
         Spacer(1, 10),
         grid([["Demo fabric", f"{demo.fabric.name}: DC Fabric standard, iBGP VXLAN_EVPN, BGP EVPN over OSPF, "
                               f"AS {demo.ibgp.bgp_asn}"],
               ["Switches", ", ".join(f"{n} {k}" for k, n in roles.items())],
               ["Tenants", ", ".join(f"{v.name} ({', '.join(n.name for n in demo.networks if n.vrf_name == v.name)})"
                                     for v in demo.vrfs)],
               ["Host ports", f"{len(demo.interfaces)} interfaces, incl. vPC port-channels; {shut} shut on purpose "
                              "(red on the port map)"],
               ["VRF-lite", "PROD handed off to external routers (AS 65500) on the external borders"],
               ["Checks", f"{len(check_project(demo))} issues; {len(render_all(demo))} YAML files generated"]],
              [1.5 * inch, 7.2 * inch]),
         Spacer(1, 10), Paragraph("The tour", H2),
         grid([["1", "Demo mode: load a simulated fabric", "8", "Review & export with nac-validate"],
               ["2", "The header and locked design-standard fields", "9", "Clone a fabric and switch between fabrics"],
               ["3", "Switches with hardware models and leaf roles", "10", "Fabric instances: list and delete"],
               ["4", "Topology diagram", "11", "Design standards editor (developers)"],
               ["5", "Networks (VLANs) in the data model", "12", "History of every change"],
               ["6", "Click a port to edit it", "13", "Dark mode"],
               ["7", "Day-2 preview: validation and YAML diff", "", ""]],
              [0.3 * inch, 3.9 * inch, 0.3 * inch, 3.9 * inch]),
         Spacer(1, 10),
         Paragraph(f"Run it: {code('cd ~/code/nac-vxlan-builder &amp;&amp; source .venv/bin/activate &amp;&amp; streamlit run app.py')}",
                   SMALL),
         PageBreak()]

page(story, 1, "Demo mode",
     "<b>Design standards → Demo mode</b> loads a simulated fabric full of sample values. It opens as its own "
     "fabric (your others stay in the fabric list), can be exported as a zip or to export/demo-dc1/, and deleted "
     "again with its History and export folder.",
     img("01-demo", max_h=FRAME_H * 0.55),
     notes=["No developer unlock needed; the sidebar and header show a Demo badge while it's open.",
            "Serials, IPs and ASNs are made up."])

story += [Paragraph("STEP 2", STEP), Paragraph("The header and locked fields", H1),
          Paragraph("Every page has a header that stays put when you scroll: the fabric you're editing, its standard, "
                    "counts and error count, the NaC version it targets, a fabric switcher and a light/dark button. "
                    "Settings the design standard fixes are shown grayed out.", BODY), Spacer(1, 6),
          img("02-header", max_h=FRAME_H * 0.12), Spacer(1, 8), img("03-fabric", max_h=FRAME_H * 0.56),
          Paragraph("The DC Fabric standard locks the fabric type, route reflectors, anycast gateway MAC, overlay mode, "
                    "BUM replication and link mask; developers choose what's locked on the Design standards page.",
                    SMALL), PageBreak()]

page(story, 3, "Switches",
     "Per-role counters check the fabric against its standard (4 spines, two compute and one storage leaf pair here, "
     "three border pairs). Every switch has a Nexus 9300 model, so port numbering and checks follow the hardware.",
     halves("04-switches"),
     caption="The Switches page, top half on the left and the switch table on the right.")

page(story, 4, "Topology",
     "Spines, leaf pairs grouped by leaf role, border pairs by border set, and the VRF-lite handoff to the external "
     "routers. Hover a switch for its details.",
     img("05-topology", max_h=FRAME_H * 0.76))

page(story, 5, "Networks",
     "The VLANs in the data model. Port settings can only use these, so a host port can never carry a VLAN that "
     "isn't a network.",
     img("06-networks", max_h=FRAME_H * 0.72))

page(story, 6, "Click a port to edit it",
     "<b>Day-2 tasks → Provision ports</b> shows each switch's front panel. Green ports are enabled in the YAML, red "
     "ones are disabled, gray ones aren't in the YAML. Clicking a port (orange outline) loads its settings in a "
     "panel you can change.",
     img("07-port-panel", max_h=FRAME_H * 0.72),
     notes=["A port-channel member edits its port-channel, on both peers for a vPC.",
            "vPC peer-link and routed ports are read-only here."])

page(story, 7, "Preview: nac-validate and the YAML diff",
     "Every Day-2 change is previewed before it's applied: what's added, removed or changed, new check issues, the "
     "port map after the change (blue outline), nac-validate on the result (macOS; skipped on Windows), and a "
     "line-by-line diff of each YAML file.",
     img("08-port-preview", max_h=FRAME_H * 0.74))

page(story, 8, "Review & export",
     "The app's own checks, then nac-validate with the bundled schema and, on macOS, Cisco's rule sets from the "
     f"installed {code(NAC_COLLECTION)} collection. Files can be downloaded as a zip or written to "
     "export/&lt;fabric&gt;/ or a NaC repo, with a diff first.",
     img("09-review", max_h=FRAME_H * 0.72))

story += [Paragraph("STEP 9", STEP), Paragraph("Clone a fabric, then switch between fabrics", H1),
          Paragraph("Clone copies the fabric under a new name and swaps the switch-name prefix everywhere it's used. "
                    "The clone is saved as a new fabric; the header's dropdown switches between every saved fabric.",
                    BODY), Spacer(1, 6),
          two_up(img("10-clone", max_w=FRAME_W / 2 - 12, max_h=FRAME_H * 0.62),
                 img("11-switcher", max_w=FRAME_W / 2 - 12, max_h=FRAME_H * 0.62)),
          Paragraph("Each fabric has a stable ID, so renaming keeps it the same fabric and two fabrics can share a "
                    "name. Every change is saved as you go.", SMALL), PageBreak()]

page(story, 10, "Fabric instances",
     "The bottom of the Fabric page lists every saved fabric. Tick the ones to delete and confirm by typing "
     f"{code('Yes')}: the fabric, its History and its export folder go.",
     img("12-instances", max_h=FRAME_H * 0.5),
     notes=["Clear fabric (above it) resets the open fabric to its standard's defaults after you type its name."])

page(story, 11, "Design standards editor",
     "Developers only (behind a warning and an unlock): change each standard's constraints and defaults, and choose "
     "which defaults engineers can't change. Changes go to nacbuilder/data/standards.yaml.",
     halves("13-standards", max_h=FRAME_H * 0.78),
     caption="Left: the developer-only warning, identity and constraints. Right: defaults and the locked-defaults list.")

page(story, 12, "History",
     "A snapshot of every change, per fabric. Compare any snapshot with the open fabric, restore it, or download it as "
     "a project file. Undo and Redo in the sidebar step through this session's changes.",
     img("14-history", max_h=FRAME_H * 0.7))

page(story, 13, "Dark mode",
     "The sun/moon button at the top right of the header switches between light and dark mode for every page, "
     "and the browser remembers it.",
     halves("15-dark", max_h=FRAME_H * 0.76))

story += [Paragraph("Where things are kept", H1),
          grid([["Fabrics", code("~/.nac-vxlan-builder/fabrics/&lt;id&gt;.json") + " (one file per fabric)"],
                ["History", code("~/.nac-vxlan-builder/history/&lt;id&gt;/") + " (the last 200 snapshots per fabric)"],
                ["Exports", code("export/&lt;fabric&gt;/") + " in the app folder (git-ignored)"],
                ["Design standards", code("nacbuilder/data/standards.yaml") + " (only once a developer saves one)"],
                ["Validation settings", code("~/.nac-vxlan-builder.json")]],
               [1.8 * inch, 6.9 * inch], size=9),
          Spacer(1, 10),
          Paragraph("Rebuild this document: "
                    + code("python docs/tour/capture.py &amp;&amp; python docs/tour/build_pdf.py")
                    + " (needs Playwright with Chrome, Pillow and reportlab).", SMALL)]

SimpleDocTemplate(str(OUT), pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                  bottomMargin=MARGIN, title="NaC VXLAN Builder: guided tour",
                  author="NaC VXLAN Builder").build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
