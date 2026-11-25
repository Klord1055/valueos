"""Shared look and feel: high contrast text, larger type, readable charts."""
import plotly.io as pio
import streamlit as st

INK = "#111111"
NAVY = "#1F3A93"
GREEN = "#1E7B45"
RED = "#B42318"
GOLD = "#B7791F"
GREY = "#5B6472"

CSS = """
<style>
html, body, [class*="css"] { color: #111111; }
[data-testid="stCaptionContainer"], .stCaption, [data-testid="stCaptionContainer"] p {
    color: #2B2F36 !important; font-size: 0.95rem !important; }
[data-testid="stMetricLabel"] p { color: #2B2F36 !important; font-size: 0.95rem !important; font-weight: 600;
    white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * { overflow: visible !important; white-space: normal !important; text-overflow: clip !important; max-width: none !important; }
[data-testid="stMetricValue"] { color: #111111 !important; font-size: 1.85rem !important; }
[data-testid="stMetricValue"] div { white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
button[role="tab"] p { font-size: 1.05rem !important; font-weight: 600; }
button[role="tab"][aria-selected="true"] p { color: #1F3A93 !important; }
[data-testid="stSidebar"] label p { color: #111111 !important; font-weight: 500; }
[data-testid="stSidebar"] h2 { font-size: 1.2rem; margin-top: 0.6rem; }
.intro { color:#2B2F36; font-size:1.02rem; line-height:1.5; margin:-6px 0 14px 0; }
.note { color:#2B2F36; font-size:0.92rem; margin-top:-10px; }
[data-testid="stMetric"] div { overflow: visible !important; }
[data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * { white-space: normal !important; overflow: visible !important; max-width: none !important; }
@media (max-width: 640px) { .note { margin-bottom: 14px; } [data-testid="stMetric"] { margin-bottom: 4px; } }
.takeaway { background:#EEF2FB; border-left:5px solid #1F3A93; padding:10px 14px; border-radius:6px;
            color:#111111; font-size:1.0rem; margin:4px 0 14px 0; }
</style>
"""

pio.templates["clear"] = pio.templates["plotly_white"]
pio.templates["clear"].layout.update(
    font=dict(size=14, color=INK, family="Arial, Helvetica, sans-serif"),
    title=dict(font=dict(size=17, color=INK)),
    xaxis=dict(tickfont=dict(size=13, color=INK), title=dict(font=dict(size=14, color=INK)), gridcolor="#E3E6EB"),
    yaxis=dict(tickfont=dict(size=13, color=INK), title=dict(font=dict(size=14, color=INK)), gridcolor="#E3E6EB"),
    legend=dict(font=dict(size=13, color=INK)),
    hoverlabel=dict(font=dict(size=14)),
    margin=dict(l=10, r=24),
)
pio.templates.default = "clear"


def wrap(label, width=20):
    """Break a long axis label over several lines so phone charts keep room for the bars."""
    import textwrap
    return "<br>".join(textwrap.wrap(str(label), width=width, break_long_words=False)) or str(label)


def setup():
    st.markdown(CSS, unsafe_allow_html=True)


def takeaway(text: str):
    """One plain English line that says what the result above means."""
    st.markdown(f"<div class='takeaway'>{text}</div>", unsafe_allow_html=True)


def intro(text: str):
    """Dark, readable subtitle under the page title (st.caption renders too light)."""
    st.markdown(f"<div class='intro'>{text}</div>", unsafe_allow_html=True)


def note(col, text: str):
    """Small dark line under a metric, used instead of a delta arrow when an arrow would mislead."""
    col.markdown(f"<div class='note'>{text}</div>", unsafe_allow_html=True)
