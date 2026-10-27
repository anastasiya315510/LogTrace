"""
NemoTrace — Streamlit Investigation Portal
Real-time incident monitoring, service topology visualisation, and PDF report export.
"""
from __future__ import annotations

import io
import time
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

import base64 as _b64
import os
import requests
import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph
from fpdf import FPDF

# ── Logo (loaded once, reused everywhere) ─────────────────────────────────────
_HERE = Path(__file__).parent
with open(_HERE / "icon.svg", "rb") as _f:
    _logo_b64 = _b64.b64encode(_f.read()).decode()

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="NemoTrace",
    page_icon=str(_HERE / "icon.svg"),
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Colour palette (matches React portal) ────────────────────────────────────

COLORS = {
    "root_cause":       "#C47D6D",
    "propagated_error": "#C9A05A",
    "symptom":          "#7F9DB5",
    "unknown":          "#879477",
    "success":          "#8FB5A0",
    "info":             "#7F9DB5",
    "warning":          "#C9A05A",
    "error":            "#C47D6D",
    "bg":               "#202427",
    "card":             "#292E32",
    "text":             "#E3E5E2",
}

ROLE_LABELS = {
    "root_cause":       "Root Cause",
    "propagated_error": "Propagated",
    "symptom":          "Symptom",
    "unknown":          "Unknown",
}

# ── Custom CSS ─────────────────────────────────────────────────────────────────

st.markdown("""
<style>
  /* ── Full dark background ── */
  html, body,
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"],
  [data-testid="block-container"],
  [data-testid="stVerticalBlock"],
  .main, .block-container,
  section[data-testid="stSidebar"] + div,
  div[class*="main"] { background: #202427 !important; }

  /* ── Global text ── */
  html, body, [data-testid="stMain"] *,
  p, span, div, label, li, td, th, h1, h2, h3 {
    color: #E3E5E2;
  }

  /* ── Sidebar ── */
  [data-testid="stSidebar"],
  [data-testid="stSidebar"] > div { background: #292E32 !important; }
  [data-testid="stSidebar"] * { color: #E3E5E2 !important; }

  /* ── Inputs ── */
  [data-testid="stTextInput"] input,
  [data-testid="stTextInput"] input:focus {
    background: #2F3438 !important;
    color: #E3E5E2 !important;
    border-color: rgba(227,229,226,0.12) !important;
  }

  /* ── Buttons ── */
  [data-testid="stBaseButton-primary"],
  [data-testid="stBaseButton-secondary"] {
    background: #2F3438 !important;
    border: 1px solid rgba(227,229,226,0.12) !important;
    color: #E3E5E2 !important;
  }
  [data-testid="stBaseButton-primary"] { background: #7F9DB5 !important; color: #202427 !important; }

  /* ── Dividers, captions ── */
  hr { border-color: rgba(227,229,226,0.08) !important; }
  [data-testid="stCaptionContainer"] p { color: rgba(227,229,226,0.4) !important; }

  /* ── Expander ── */
  [data-testid="stExpander"] {
    background: #292E32 !important;
    border: 1px solid rgba(227,229,226,0.08) !important;
    border-radius: 10px !important;
  }
  [data-testid="stExpander"] summary { color: #E3E5E2 !important; }

  /* ── Info / warning / error banners ── */
  [data-testid="stNotification"] { background: #2F3438 !important; border-radius: 10px !important; }
  .status-badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border-radius: 999px;
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  }
  .metric-card {
    background: #292E32; border: 1px solid rgba(227,229,226,0.08);
    border-radius: 12px; padding: 16px 20px;
  }
  .metric-label { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: rgba(227,229,226,0.35); margin-bottom: 4px; }
  .metric-value { font-size: 1.5rem; font-weight: 800; color: #E3E5E2; }
  .incident-card {
    background: #292E32; border: 1px solid rgba(227,229,226,0.08);
    border-radius: 14px; padding: 16px 20px; margin-bottom: 10px;
    cursor: pointer; transition: border-color 0.2s;
  }
  .incident-card:hover { border-color: rgba(127,157,181,0.4); }
  .section-title {
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: rgba(227,229,226,0.45);
    margin-bottom: 12px; margin-top: 24px;
  }
  .cascade-step {
    display: flex; align-items: flex-start; gap: 12px; margin-bottom: 14px;
  }
  .cascade-num {
    width: 28px; height: 28px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.75rem; font-weight: 700; flex-shrink: 0;
  }
</style>
""", unsafe_allow_html=True)

# ── API helpers ───────────────────────────────────────────────────────────────

def api(method: str, path: str, **kwargs) -> dict | None:
    """Make an authenticated API call; return parsed JSON or None on error."""
    base   = st.session_state.get("base_url", os.environ.get("API_BASE_URL", "http://localhost:8000")).rstrip("/")
    api_key = st.session_state.get("api_key", "")
    try:
        resp = requests.request(
            method, f"{base}{path}",
            headers={"X-API-Key": api_key},
            timeout=10,
            **kwargs,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        st.error(f"API error {e.response.status_code}: {e.response.text[:200]}")
    except requests.RequestException as e:
        st.error(f"Connection error: {e}")
    return None


def fmt_confidence(score: float | None) -> str:
    if score is None:
        return "—"
    pct = round(score * 100) if score <= 1.0 else round(score)
    return f"{pct}%"


def confidence_pct(score: float | None) -> int:
    if score is None:
        return 0
    return round(score * 100) if score <= 1.0 else round(score)


def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return iso


STATUS_COLOR = {
    "pending":     ("#879477", "rgba(135,148,119,0.15)"),
    "classifying": ("#7F9DB5", "rgba(127,157,181,0.15)"),
    "analyzing":   ("#A89BC0", "rgba(168,155,192,0.15)"),
    "complete":    ("#8FB5A0", "rgba(143,181,160,0.15)"),
    "failed":      ("#C47D6D", "rgba(196,125,109,0.15)"),
}


def status_badge_html(status: str) -> str:
    color, bg = STATUS_COLOR.get(status, ("#879477", "rgba(135,148,119,0.15)"))
    dot = "●" if status in ("classifying", "analyzing") else "●"
    return (
        f'<span class="status-badge" style="color:{color};background:{bg};'
        f'border:1px solid {color}40">{dot} {status}</span>'
    )

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(f"""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:2px">
  <div style="width:32px;height:32px;border-radius:9px;flex-shrink:0;
              background:rgba(127,157,181,0.1);border:1px solid rgba(127,157,181,0.2);
              display:flex;align-items:center;justify-content:center">
    <img src="data:image/svg+xml;base64,{_logo_b64}" style="width:18px;height:18px" />
  </div>
  <span style="font-size:1.05rem;font-weight:800;letter-spacing:-0.01em;color:#E3E5E2">NemoTrace</span>
</div>
""", unsafe_allow_html=True)
    st.caption("AI Log Intelligence — Investigation Portal")
    st.divider()

    st.session_state["api_key"] = st.text_input(
        "API Key",
        value=st.session_state.get("api_key", "dev-demo-key"),
        type="password",
        placeholder="Enter API key…",
    )
    st.session_state["base_url"] = st.text_input(
        "API Base URL",
        value=st.session_state.get("base_url", os.environ.get("API_BASE_URL", "http://localhost:8000")),
    )
    st.divider()

    st.markdown("**Browse Submission**")
    submission_id_input = st.text_input(
        "Submission ID",
        value=st.session_state.get("submission_id", ""),
        placeholder="UUID…",
        label_visibility="collapsed",
    )
    if st.button("Load Submission", use_container_width=True, type="primary"):
        st.session_state["submission_id"] = submission_id_input.strip()
        st.session_state.pop("selected_incident", None)
        st.rerun()

    st.divider()

    # Demo controls
    st.markdown("**Live Demo**")
    demo_data = api("GET", "/demo/status")
    phase = demo_data.get("phase", "idle") if demo_data else "idle"

    st.markdown(
        f'<div style="text-align:center;margin-bottom:6px">{status_badge_html(phase)}</div>',
        unsafe_allow_html=True,
    )
    if demo_data:
        events_raw = demo_data.get("events_pushed", 0)
        events = sum(events_raw.values()) if isinstance(events_raw, dict) else (events_raw or 0)
        if events:
            st.caption(f"{events:,} events pushed")

    scenario = st.selectbox(
        "Scenario",
        options=["pool_exhaustion", "memory_leak", "slow_query"],
        format_func=lambda x: {
            "pool_exhaustion": "DB Pool Exhaustion",
            "memory_leak":     "Memory Leak / OOM",
            "slow_query":      "Deadlock / Slow Query",
        }.get(x, x),
        label_visibility="collapsed",
    )

    col_start, col_inject = st.columns(2)
    with col_start:
        if st.button("▶ Start", disabled=(phase != "idle"), use_container_width=True):
            api("POST", "/demo/start")
            st.rerun()
    with col_inject:
        if st.button("⚡ Inject", disabled=(phase != "normal"), use_container_width=True):
            api("POST", "/demo/cascade", json={"scenario": scenario})
            st.rerun()
    if st.button("↺ Reset", use_container_width=True):
        api("POST", "/demo/reset")
        st.rerun()

    if demo_data:
        demo_sid = demo_data.get("submission_id")
        if demo_sid and st.button("Use demo submission", use_container_width=True):
            st.session_state["submission_id"] = str(demo_sid)
            st.session_state.pop("selected_incident", None)
            st.rerun()

    st.divider()
    st.caption("Powered by Nemotron Nano 8B + Ultra 253B via Nebius Token Factory")

# ── PDF generation (fpdf2) ────────────────────────────────────────────────────

_STEP_COLORS_PDF = ["#C47D6D", "#C9A05A", "#879477", "#7F9DB5"]


def _safe(text: str, max_len: int = 0) -> str:
    """Strip non-latin chars that fpdf2 core fonts can't encode."""
    result = text.encode("latin-1", errors="replace").decode("latin-1")
    return result[:max_len] if max_len else result


def _wrap(text: str, max_token: int = 70) -> str:
    """Break any token longer than max_token so fpdf2 multi_cell can wrap it."""
    parts = []
    for token in text.split(" "):
        while len(token) > max_token:
            parts.append(token[:max_token])
            token = token[max_token:]
        parts.append(token)
    return " ".join(parts)


def render_pdf(incident: dict, incident_id: str) -> bytes:
    """Generate a PDF report using fpdf2 (no external renderer needed)."""
    conf_pct   = confidence_pct(incident.get("confidence_score"))
    now        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cascade    = incident.get("cascade_chain") or []
    fixes      = incident.get("fix_suggestions") or []
    alts       = incident.get("alternative_hypotheses") or []
    rca        = incident.get("cascade_explanation") or ""
    root_cause = incident.get("root_cause_service") or "—"
    services   = ", ".join(incident.get("services_involved") or [])

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(20, 18, 20)

    # ── Cover ──
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 10, "NemoTrace Incident Report", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(107, 114, 128)
    pdf.cell(0, 6, _safe(f"Generated: {now}"), ln=True)
    pdf.cell(0, 6, _safe(f"Incident ID: {incident_id}"), ln=True)
    pdf.cell(0, 6, _safe(f"Services: {services}"), ln=True)
    pdf.ln(4)
    pdf.set_draw_color(229, 231, 235)
    pdf.set_line_width(0.5)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(6)

    def section_title(title: str) -> None:
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(156, 163, 175)
        pdf.cell(0, 5, title.upper(), ln=True)
        pdf.set_draw_color(243, 244, 246)
        pdf.line(20, pdf.get_y(), 190, pdf.get_y())
        pdf.ln(4)

    # ── Root cause + confidence ──
    section_title("Root Cause")
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(180, 83, 9)
    pdf.cell(0, 8, _safe(f"  {root_cause}"), ln=True)
    if conf_pct:
        r, g, b = (5, 150, 105) if conf_pct >= 80 else (217, 119, 6) if conf_pct >= 60 else (220, 38, 38)
        pdf.set_font("Helvetica", "B", 28)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 14, f"{conf_pct}% confidence", ln=True)
    pdf.ln(4)

    # ── Cascade chain ──
    if cascade:
        section_title("Cascade Timeline")
        for i, step in enumerate(cascade):
            svc = _safe(step.get("service") or step.get("name") or "?", 60)
            err = _safe(step.get("error", ""), 100)
            ts  = _safe(step.get("timestamp", ""), 40)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(17, 24, 39)
            pdf.cell(8, 6, f"{i+1}.", ln=False)
            pdf.cell(0, 6, svc, ln=True)
            if err:
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(220, 38, 38)
                pdf.cell(8, 5, "", ln=False)
                pdf.cell(0, 5, err, ln=True)
            if ts:
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(156, 163, 175)
                pdf.cell(8, 5, "", ln=False)
                pdf.cell(0, 5, ts, ln=True)
        pdf.ln(4)

    # ── RCA text ──
    section_title("Root Cause Analysis  (Nemotron Ultra 253B)")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(55, 65, 81)
    # Strip markdown symbols and write line by line
    for raw_line in rca.splitlines():
        line = raw_line.strip()
        if not line:
            pdf.ln(2)
            continue
        # Headings
        if line.startswith("### "):
            pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(17, 24, 39)
            pdf.multi_cell(0, 5, _wrap(_safe(line[4:])), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9); pdf.set_text_color(55, 65, 81)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(17, 24, 39)
            pdf.multi_cell(0, 6, _wrap(_safe(line[3:])), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9); pdf.set_text_color(55, 65, 81)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 13); pdf.set_text_color(17, 24, 39)
            pdf.multi_cell(0, 7, _wrap(_safe(line[2:])), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9); pdf.set_text_color(55, 65, 81)
        elif line.startswith("|"):
            # Skip markdown tables (complex to render)
            continue
        elif line.startswith("```") or line == "---":
            continue
        else:
            pdf.multi_cell(0, 5, _wrap(_safe(line)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── Fix suggestions ──
    if fixes:
        section_title("Fix Suggestions  (Tavily)")
        for fix in fixes:
            title   = _safe(fix.get("source_title") or fix.get("source_url", ""), 80)
            url     = _safe(fix.get("source_url", ""), 80)  # truncate long URLs
            excerpt = _safe((fix.get("excerpt") or "")[:200])
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(37, 99, 235)
            pdf.multi_cell(0, 5, title, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(107, 114, 128)
            pdf.cell(0, 4, url, ln=True)
            if excerpt:
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(75, 85, 99)
                pdf.multi_cell(0, 4, _wrap(excerpt), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

    # ── Alternative hypotheses ──
    if alts:
        section_title("Alternative Hypotheses")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(55, 65, 81)
        for i, h in enumerate(alts, 1):
            hyp_text = h if isinstance(h, str) else (h.get("hypothesis") if isinstance(h, dict) else str(h))
            raw_c = h.get("confidence") if isinstance(h, dict) else None
            conf_str = f" ({round(raw_c * 100 if raw_c and raw_c <= 1 else raw_c)}% likely)" if raw_c else ""
            pdf.multi_cell(0, 5, _safe(f"{i}. {hyp_text}{conf_str}"), new_x="LMARGIN", new_y="NEXT")
            if isinstance(h, dict) and h.get("reason"):
                pdf.set_font("Helvetica", "", 8); pdf.set_text_color(107, 114, 128)
                pdf.multi_cell(0, 4, _wrap(_safe(f"   {h['reason']}")), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9); pdf.set_text_color(55, 65, 81)
            pdf.ln(1)

    # ── Footer ──
    pdf.set_y(-18)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(156, 163, 175)
    pdf.cell(0, 5, "Generated by NemoTrace  -  AI Log Intelligence  -  NVIDIA x Nebius Hackathon", align="C")

    return bytes(pdf.output())

# ── Topology graph ────────────────────────────────────────────────────────────

def render_topology(topology: dict | None) -> None:
    if not topology or not topology.get("node_roles"):
        st.info("No topology data available yet.")
        return

    node_roles  = topology.get("node_roles", {})
    adjacency   = topology.get("adjacency", {})
    error_counts = topology.get("error_counts", {})

    nodes, edges = [], []

    for service, role in node_roles.items():
        color     = COLORS.get(role, COLORS["unknown"])
        count     = error_counts.get(service)
        label     = f"{service}\n({count} err)" if count else service
        is_root   = role == "root_cause"
        nodes.append(Node(
            id=service,
            label=label,
            color=color,
            size=25 if is_root else 18,
            font={"color": "#E3E5E2", "size": 11},
            borderWidth=3 if is_root else 1,
            borderWidthSelected=4,
            shadow=is_root,
        ))

    for src, targets in adjacency.items():
        for tgt in (targets or []):
            edges.append(Edge(
                source=src,
                target=tgt,
                color={"color": "rgba(227,229,226,0.25)", "highlight": "#7F9DB5"},
                width=1.5,
                arrows="to",
            ))

    cfg = Config(
        width="100%",
        height=300,
        directed=True,
        physics=True,
        hierarchical=False,
        nodeHighlightBehavior=True,
        highlightColor="#7F9DB5",
        collapsible=False,
        node={"labelProperty": "label"},
        link={"labelProperty": "label", "renderLabel": False},
    )
    agraph(nodes=nodes, edges=edges, config=cfg)

    # Legend
    with st.expander("Legend", expanded=False):
        cols = st.columns(4)
        for i, (role, label) in enumerate(ROLE_LABELS.items()):
            color = COLORS.get(role, COLORS["unknown"])
            cols[i].markdown(
                f'<span style="color:{color}">⬤</span> <span style="font-size:0.8rem">{label}</span>',
                unsafe_allow_html=True,
            )

# ── Incident detail view ──────────────────────────────────────────────────────

def render_incident(incident_id: str) -> None:
    incident = api("GET", f"/api/v1/incidents/{incident_id}")
    if not incident:
        return

    status     = incident.get("status", "unknown")
    is_live    = status not in ("complete", "failed")
    root_cause = incident.get("root_cause_service")
    conf_pct   = confidence_pct(incident.get("confidence_score"))
    conf_color = COLORS["success"] if conf_pct >= 80 else COLORS["warning"] if conf_pct >= 60 else COLORS["error"]

    # ── Header ──
    col_back, col_badge = st.columns([1, 5])
    with col_back:
        if st.button("← Back", key="back_btn"):
            st.session_state.pop("selected_incident", None)
            st.rerun()
    with col_badge:
        st.markdown(status_badge_html(status), unsafe_allow_html=True)

    st.markdown(f'<h2 style="color:#E3E5E2;font-size:1.6rem;font-weight:800;margin:12px 0 4px">'
                f'{incident_id[:8]}…{incident_id[-4:]}</h2>', unsafe_allow_html=True)
    st.caption(f"Full ID: `{incident_id}`")

    # ── Metrics row ──
    m1, m2, m3 = st.columns(3)
    with m1:
        if root_cause:
            rc_html = f'<div class="metric-value" style="color:{COLORS["warning"]};font-size:1.1rem">{root_cause}</div>'
        elif is_live:
            rc_html = '<div class="metric-value" style="color:rgba(227,229,226,0.3);font-size:0.85rem;font-style:italic">analyzing…</div>'
        else:
            rc_html = '<div class="metric-value">—</div>'
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Root Cause Service</div>{rc_html}</div>',
            unsafe_allow_html=True,
        )
    with m2:
        if conf_pct:
            conf_html = f'<div class="metric-value" style="color:{conf_color}">{conf_pct}%</div>'
        elif is_live:
            conf_html = '<div class="metric-value" style="color:rgba(227,229,226,0.3);font-size:0.85rem;font-style:italic">analyzing…</div>'
        else:
            conf_html = '<div class="metric-value">—</div>'
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Confidence</div>{conf_html}</div>',
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            f'<div class="metric-card">'
            f'<div class="metric-label">Status</div>'
            f'<div class="metric-value" style="font-size:1rem">'
            f'{status_badge_html(status)}</div></div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ── RCA / sections ──
    rca_text = incident.get("cascade_explanation") or ""

    st.markdown('<div class="section-title">Root Cause Analysis</div>', unsafe_allow_html=True)

    if rca_text:
        with st.container():
            st.markdown(
                f'<div style="background:#292E32;border:1px solid rgba(227,229,226,0.08);'
                f'border-radius:12px;padding:20px 24px;line-height:1.8;color:rgba(227,229,226,0.85)">'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown(rca_text)
    else:
        st.warning("Analysis not yet available.")

    # ── Three-column panel ──
    left_col, mid_col, right_col = st.columns(3)

    # Cascade chain
    with left_col:
        st.markdown('<div class="section-title">Cascade Chain</div>', unsafe_allow_html=True)
        cascade = incident.get("cascade_chain") or []
        if cascade:
            for i, step in enumerate(cascade):
                svc = step.get("service") or step.get("name") or "?"
                err = step.get("error", "")
                ts  = step.get("timestamp", "")
                color = _STEP_COLORS_PDF[i % len(_STEP_COLORS_PDF)]
                st.markdown(
                    f'<div class="cascade-step">'
                    f'<div class="cascade-num" style="background:{color};color:#202427;'
                    f'width:28px;height:28px;border-radius:50%;display:flex;align-items:center;'
                    f'justify-content:center;font-size:.75rem;font-weight:700;flex-shrink:0">'
                    f'{i+1}</div>'
                    f'<div><div style="font-family:monospace;font-size:.85rem;font-weight:600;'
                    f'color:{color}">{svc}</div>'
                    f'{"<div style=\"font-size:.8rem;color:#C47D6D;opacity:.85\">" + err + "</div>" if err else ""}'
                    f'{"<div style=\"font-size:.75rem;color:rgba(227,229,226,.3);font-family:monospace\">" + ts + "</div>" if ts else ""}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption(
                "No cascade chain produced by model"
                if status == "complete"
                else "No cascade data yet"
            )

    # Service topology
    with mid_col:
        st.markdown('<div class="section-title">Service Topology</div>', unsafe_allow_html=True)
        render_topology(incident.get("service_topology"))

    # Fix suggestions
    with right_col:
        st.markdown('<div class="section-title">Fix Suggestions</div>', unsafe_allow_html=True)
        fixes = incident.get("fix_suggestions") or []
        if fixes:
            for fix in fixes:
                title   = fix.get("source_title") or fix.get("source_url", "")
                url     = fix.get("source_url", "#")
                excerpt = fix.get("excerpt") or ""
                qtype   = (fix.get("query_type") or "other").capitalize()
                score   = fix.get("tavily_score") or 0
                with st.expander(f"**{title[:55]}…**" if len(title) > 55 else f"**{title}**"):
                    st.caption(f"{qtype} · relevance {round(score * 100)}%")
                    st.markdown(f"[{url}]({url})")
                    if excerpt:
                        st.markdown(f"> {excerpt[:300]}")
        else:
            st.caption("No suggestions yet")

    # Alternative hypotheses
    alts = incident.get("alternative_hypotheses") or []
    if alts:
        st.markdown('<div class="section-title">Alternative Hypotheses</div>', unsafe_allow_html=True)
        for i, h in enumerate(alts, 1):
            if isinstance(h, str):
                text, conf, reason = h, None, None
            else:
                text   = h.get("hypothesis") or str(h)
                raw_c  = h.get("confidence")
                conf   = round(raw_c * 100 if raw_c and raw_c <= 1 else (raw_c or 0)) if raw_c else None
                reason = h.get("reason")
            badge = f" &nbsp;<span style='font-size:.75rem;color:#879477'>{conf}% likely</span>" if conf else ""
            st.markdown(f"**{i}.** {text}{badge}", unsafe_allow_html=True)
            if reason:
                st.caption(f"  ↳ {reason}")

    # ── PDF download (only when complete) ──
    if status == "complete":
        st.divider()
        try:
            pdf_bytes = render_pdf(incident, incident_id)
            st.download_button(
                label="⬇ Download PDF Report",
                data=io.BytesIO(pdf_bytes),
                file_name=f"nemotrace-incident-{incident_id[:8]}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        except Exception as e:
            st.warning(f"PDF generation failed: {e}")
            # Fallback: build markdown locally from the already-loaded incident dict
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            lines = [
                "# NemoTrace Incident Report",
                f"\n**Generated:** {now}  ",
                f"**Incident ID:** `{incident_id}`  ",
                f"**Status:** {incident.get('status', '—')}  ",
                f"**Root Cause:** {incident.get('root_cause_service', '—')}  ",
            ]
            if confidence_pct(incident.get("confidence_score")):
                lines.append(f"**Confidence:** {confidence_pct(incident.get('confidence_score'))}%")
            rca_text = incident.get("cascade_explanation", "")
            if rca_text:
                lines += ["\n---\n\n## Root Cause Analysis\n", rca_text]
            md_str = "\n".join(lines)
            st.download_button(
                label="⬇ Download Markdown Report",
                data=md_str,
                file_name=f"nemotrace-incident-{incident_id[:8]}.md",
                mime="text/markdown",
                use_container_width=True,
            )

    # ── Auto-refresh (must be last) ──
    # Keep a per-incident refresh window: always refresh for 60 s after first open,
    # then stop. This covers both in-flight polling and post-complete trailing data.
    _expiry_key = f"_refresh_until_{incident_id}"
    if _expiry_key not in st.session_state:
        st.session_state[_expiry_key] = time.time() + 60

    if is_live:
        st.info("⏳ Analysis in progress — refreshing every 3 seconds…")
        time.sleep(3)
        st.rerun()
    elif time.time() < st.session_state[_expiry_key]:
        time.sleep(3)
        st.rerun()

# ── Submission view ───────────────────────────────────────────────────────────

def render_submission(submission_id: str) -> None:
    sub = api("GET", f"/api/v1/submissions/{submission_id}")
    if not sub:
        return

    status = sub.get("status", "unknown")
    count  = sub.get("incident_count", 0)

    st.markdown(
        f'<h2 style="color:#E3E5E2;font-size:1.5rem;font-weight:800;margin-bottom:4px">'
        f'Submission</h2>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.markdown(
        f'<div class="metric-card"><div class="metric-label">Status</div>'
        f'<div class="metric-value" style="font-size:1rem">{status_badge_html(status)}</div></div>',
        unsafe_allow_html=True,
    )
    c2.markdown(
        f'<div class="metric-card"><div class="metric-label">Incidents</div>'
        f'<div class="metric-value" style="color:#7F9DB5">{count}</div></div>',
        unsafe_allow_html=True,
    )
    c3.markdown(
        f'<div class="metric-card"><div class="metric-label">Created</div>'
        f'<div class="metric-value" style="font-size:.9rem">'
        f'{fmt_dt(sub.get("created_at"))}</div></div>',
        unsafe_allow_html=True,
    )

    # Auto-refresh while still processing
    if status not in ("complete", "failed"):
        st.info("⏳ Analysis in progress — refreshing every 3 seconds…")
        time.sleep(3)
        st.rerun()

    # Incident list
    st.markdown('<div class="section-title" style="margin-top:28px">Incidents</div>',
                unsafe_allow_html=True)
    inc_data = api("GET", f"/api/v1/submissions/{submission_id}/incidents")
    incidents = inc_data.get("incidents", []) if inc_data else []

    if not incidents:
        st.info("No incidents detected yet — analysis may still be running.")
        return

    for inc in incidents:
        iid   = str(inc.get("incident_id", ""))
        istatus = inc.get("status", "?")
        root  = inc.get("root_cause_service")
        conf  = confidence_pct(inc.get("confidence_score"))
        conf_c = COLORS["success"] if conf >= 80 else COLORS["warning"] if conf >= 60 else COLORS["error"]

        col_info, col_btn = st.columns([5, 1])
        with col_info:
            st.markdown(
                f'<div class="incident-card">'
                f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">'
                f'<code style="font-size:.8rem;color:rgba(227,229,226,.55)">{iid[:8]}…</code>'
                f'{status_badge_html(istatus)}</div>'
                f'<div style="display:flex;gap:20px;align-items:center">'
                f'{"<span style=\"font-size:.8rem;font-weight:700;padding:2px 10px;border-radius:999px;background:rgba(201,160,90,.15);color:#C9A05A\">⬤ " + root + "</span>" if root else ""}'
                f'{"<span style=\"font-size:.8rem;font-weight:700;color:" + conf_c + "\">" + str(conf) + "% confidence</span>" if conf else ""}'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        with col_btn:
            if st.button("View →", key=f"view_{iid}"):
                st.session_state["selected_incident"] = iid
                st.rerun()

# ── Main ──────────────────────────────────────────────────────────────────────

st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;margin-bottom:20px;padding:20px 0 12px">
  <div style="width:52px;height:52px;border-radius:14px;flex-shrink:0;
              background:rgba(127,157,181,0.1);border:1px solid rgba(127,157,181,0.2);
              display:flex;align-items:center;justify-content:center;
              box-shadow:0 0 24px rgba(127,157,181,0.15)">
    <img src="data:image/svg+xml;base64,{_logo_b64}"
         style="width:30px;height:30px" />
  </div>
  <div>
    <div style="font-size:1.85rem;font-weight:800;letter-spacing:-0.03em;
                color:#E3E5E2;line-height:1.1">NemoTrace</div>
    <div style="font-size:0.78rem;font-weight:500;color:rgba(227,229,226,0.4);
                letter-spacing:0.06em;text-transform:uppercase;margin-top:4px">
      AI Log Intelligence
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

api_key_set  = bool(st.session_state.get("api_key"))
submission_id = st.session_state.get("submission_id", "")
selected_inc  = st.session_state.get("selected_incident")

if not api_key_set:
    st.warning("Enter your API key in the sidebar to get started.")
elif selected_inc:
    render_incident(selected_inc)
elif submission_id:
    render_submission(submission_id)
else:
    # Landing state
    st.markdown("""
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
min-height:55vh;text-align:center;gap:20px">
  <div style="font-size:4rem;opacity:.25">🔍</div>
  <div>
    <h3 style="color:#E3E5E2;font-weight:700;margin-bottom:8px">No submission selected</h3>
    <p style="color:rgba(227,229,226,.55);font-size:.9rem;max-width:400px">
      Enter a Submission ID in the sidebar, or use the <b>Live Demo Status</b>
      panel to load the current demo submission.
    </p>
  </div>
</div>
""", unsafe_allow_html=True)