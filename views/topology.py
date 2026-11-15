import re

import streamlit as st
import streamlit.components.v1 as components

from nacbuilder.diagram import render_svg
from nacbuilder.ui import project

p = project()

st.title("Topology")
st.caption("Spines, leafs and border pairs as they're defined now. Dashed boxes are vPC pairs and border sets; "
           "a red outline means the switch has check errors. Hover a switch for details.")

if not p.switches:
    st.info("Add switches first.", icon=":material/info:")
else:
    svg = render_svg(p)
    width, height = (int(x) for x in re.search(r'width="(\d+)" height="(\d+)"', svg).groups())
    # Scale to the page width; the iframe keeps the SVG intact (st.html strips SVG) and the hover tooltips.
    fitted = svg.replace(f'width="{width}" height="{height}"', 'width="100%"', 1)
    view_w = 1000  # typical content width; the frame is sized for it so wide diagrams aren't clipped
    components.html(f'<body style="margin:0">{fitted}</body>', height=int(height * min(1, view_w / width)) + 16)
    c1, c2 = st.columns([1, 3])
    c1.download_button("Download SVG", svg, file_name=f"{p.fabric.name}-topology.svg", mime="image/svg+xml",
                       icon=":material/download:")
    c2.caption("Legend: indigo = super spines, purple = spines (RR = route reflector), blue = leafs, teal / amber / red = client / internal / "
               "external borders, thick black line = vPC peer link, red dashes = VRF-lite handoff.")
