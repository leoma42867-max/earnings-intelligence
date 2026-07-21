"""Company research page for the Earnings Intelligence dashboard."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.data import (
    format_market_cap,
    format_share_volume,
    get_company_data,
    get_researchable_tickers,
)


def _chart_layout(y_title: str) -> dict:
    """Provide consistent dark financial-chart styling."""
    return {
        "height": 320,
        "margin": dict(l=10, r=10, t=25, b=10),
        "paper_bgcolor": "#121c31",
        "plot_bgcolor": "#121c31",
        "font": {"color": "#dbeafe"},
        # A fixed date tickformat (rather than Plotly's auto-detected format)
        # avoids nonsensical sub-second tick labels when a ticker only has a
        # single day of history so far (e.g. right after adding a new signal).
        "xaxis": {"showgrid": False, "title": "", "type": "date", "tickformat": "%b %d"},
        "yaxis": {"gridcolor": "#23304d", "title": y_title},
        "showlegend": False,
    }


def _format_value(value: object, pattern: str) -> str:
    """Format an optional numeric earnings estimate for display."""
    return pattern % value if value is not None and pd.notna(value) else "—"


st.set_page_config(
    page_title="Company Research | MarketsLite", page_icon="◈", layout="wide"
)

st.markdown(
    """
    <style>
        html, body, [data-testid="stAppViewContainer"], .stApp {
            background-color: #0b1120 !important;
        }
        [data-testid="stHeader"] { background: transparent; }
        .stApp { background: #0b1120; }
        [data-testid="stMetric"] {
            background: #121c31; border: 1px solid #23304d; border-radius: 10px;
            padding: 14px;
            min-height: 108px;
        }
        [data-testid="stMetricValue"] {
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: unset !important;
            line-height: 1.25 !important;
            font-size: 1.15rem !important;
            word-break: break-word;
        }
        [data-testid="stMetricLabel"] { color: #9fb0cc; }
        h1, h2, h3 { color: #f3f7ff; }
        .peer-link { color: #93c5fd; text-decoration: none; font-weight: 600; }
        .peer-link:hover { text-decoration: underline; }
        .why-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0.4rem 0 0.8rem; }
        .why-chip {
            background: #121c31;
            border: 1px solid #23304d;
            color: #cbd5e1;
            border-radius: 999px;
            padding: 6px 12px;
            font-size: 0.88rem;
            font-weight: 600;
        }
        .why-chip.active { border-color: #4f8cff; color: #f3f7ff; }
        .attention-card {
            background: #121c31;
            border: 1px solid #23304d;
            border-radius: 10px;
            padding: 14px;
            min-height: 108px;
        }
        .attention-card-label {
            color: #9fb0cc;
            font-size: 0.85rem;
            margin-bottom: 6px;
        }
        .attention-card-value {
            color: #f3f7ff;
            font-size: 1.15rem;
            font-weight: 700;
            line-height: 1.3;
            word-break: break-word;
        }
    </style>
    <script>
      document.addEventListener(
        "click",
        function (event) {
          const anchor = event.target && event.target.closest
            ? event.target.closest('a[href*="Company"]')
            : null;
          if (!anchor) return;
          anchor.setAttribute("target", "_self");
          anchor.removeAttribute("rel");
        },
        true
      );
    </script>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60)
def get_company_list() -> list[str]:
    """Return researchable tickers from the current database snapshot."""
    return get_researchable_tickers()


@st.cache_data(ttl=60)
def load_company(ticker: str) -> dict[str, object]:
    """Cache individual company queries during a browsing session."""
    return get_company_data(ticker)


tickers = get_company_list()
if not tickers:
    st.warning("No company data is available. Run `python scripts/refresh_data.py` first.")
    st.stop()

with st.sidebar:
    st.markdown("## ◈ MarketsLite")
    st.caption("Company research")
    st.divider()
    if st.button("Reload database", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

query_ticker = str(st.query_params.get("ticker", "")).upper().strip()
default_index = tickers.index(query_ticker) if query_ticker in tickers else 0
selected_ticker = st.selectbox("Search a ticker", tickers, index=default_index)
if st.query_params.get("ticker") != selected_ticker:
    st.query_params["ticker"] = selected_ticker

company = load_company(selected_ticker)
metrics = company["metrics"].copy()
earnings = company["earnings"]
score = company["score"]
peers = company.get("peers") or []
why_chips = company.get("why_chips") or ["Quiet this week"]
headline = company.get("attention_headline") or "Background"

if metrics.empty:
    st.warning(f"No historical metrics are available for {selected_ticker}.")
    st.stop()

metrics["date"] = pd.to_datetime(metrics["date"])
metrics = metrics.sort_values("date")
latest = metrics.iloc[-1]

st.title(f"{selected_ticker} Research")
st.caption(
    f"{earnings.get('company_name', selected_ticker)}"
    + (f" · {earnings['sector']}" if earnings.get("sector") else "")
)

summary, attention_col, earnings_col, volume_col = st.columns(4)
summary.metric(
    "Last close", f"${latest['close']:,.2f}" if pd.notna(latest["close"]) else "—"
)
attention_col.markdown(
    f'<div class="attention-card">'
    f'<div class="attention-card-label">Attention</div>'
    f'<div class="attention-card-value">{headline}</div>'
    f"</div>",
    unsafe_allow_html=True,
)
earnings_col.metric("Earnings date", earnings.get("earnings_date", "—"))
volume_col.metric(
    "Latest volume",
    format_share_volume(latest["volume"]) if pd.notna(latest["volume"]) else "—",
)

st.markdown("**Why it’s getting attention**")
st.caption("What moved over the last 7 days — not the earnings outcome.")
chip_html = "".join(
    f'<span class="why-chip{" active" if chip != "Quiet this week" else ""}">{chip}</span>'
    for chip in why_chips
)
st.markdown(f'<div class="why-chips">{chip_html}</div>', unsafe_allow_html=True)
index_value = score.get("attention_score")
if index_value is not None and pd.notna(index_value):
    st.caption(f"Attention index {float(index_value):.0f} (internal ranking signal)")

st.divider()
chart_col, detail_col = st.columns([1.6, 1])

with chart_col:
    st.subheader("Price history")
    price = go.Figure(
        go.Scatter(
            x=metrics["date"],
            y=metrics["close"],
            mode="lines",
            line=dict(color="#60a5fa", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(96, 165, 250, 0.08)",
            hovertemplate="$%{y:,.2f}<extra></extra>",
        )
    )
    price.update_layout(**_chart_layout("Close price (USD)"))
    st.plotly_chart(price, use_container_width=True, config={"displayModeBar": False})

with detail_col:
    st.subheader("Report snapshot")
    st.metric("Est. EPS", _format_value(earnings.get("estimated_eps"), "$%.2f"))
    st.metric("Est. revenue", format_market_cap(earnings.get("estimated_revenue")))
    st.caption(
        "Attention ranks names by StockTwits mentions, Yahoo trend climbs, "
        "unusual volume, and price momentum ahead of earnings."
    )

st.subheader("Same-sector peers")
if not peers:
    st.caption("No tracked same-sector peers with attention scores right now.")
else:
    peer_bits = " · ".join(
        f'<a class="peer-link" href="/Company?ticker={peer["ticker"]}" '
        f'target="_self">{peer["ticker"]}</a>'
        for peer in peers
    )
    st.markdown(peer_bits, unsafe_allow_html=True)

st.subheader("StockTwits mention history")
mention_history = metrics.dropna(subset=["social_mentions"])
if mention_history.empty:
    st.info("StockTwits mention history is unavailable for this ticker.")
else:
    mentions = go.Figure(
        go.Scatter(
            x=mention_history["date"],
            y=mention_history["social_mentions"],
            mode="lines",
            line=dict(color="#6ee7b7", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(110, 231, 183, 0.08)",
            hovertemplate="StockTwits mentions: %{y}<extra></extra>",
        )
    )
    mentions.update_layout(**_chart_layout("StockTwits mentions per day"))
    st.plotly_chart(mentions, use_container_width=True, config={"displayModeBar": False})
