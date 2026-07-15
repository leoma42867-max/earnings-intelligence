"""Company research page for the Earnings Intelligence dashboard."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.data import format_market_cap, get_company_data, load_dashboard_data


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


st.set_page_config(page_title="Company Research | Earnings Intelligence", page_icon="◈", layout="wide")

st.markdown(
    """
    <style>
        .stApp { background: #0b1120; }
        [data-testid="stMetric"] {
            background: #121c31; border: 1px solid #23304d; border-radius: 10px;
            padding: 14px;
        }
        h1, h2, h3 { color: #f3f7ff; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60)
def get_company_list() -> list[str]:
    """Return researchable tickers from the current database snapshot."""
    data = load_dashboard_data()
    attention = data["attention"]
    if not attention.empty and "ticker" in attention.columns:
        return attention["ticker"].tolist()
    most_mentioned = data["most_mentioned"]
    if most_mentioned.empty or "ticker" not in most_mentioned.columns:
        return []
    return most_mentioned["ticker"].tolist()


@st.cache_data(ttl=60)
def load_company(ticker: str) -> dict[str, object]:
    """Cache individual company queries during a browsing session."""
    return get_company_data(ticker)


tickers = get_company_list()
if not tickers:
    st.warning("No company data is available. Run `python scripts/refresh_data.py` first.")
    st.stop()

with st.sidebar:
    st.markdown("## ◈ Earnings Intel")
    st.caption("Company research")
    st.divider()
    if st.button("Reload database", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

selected_ticker = st.selectbox("Search a ticker", tickers)
company = load_company(selected_ticker)
metrics = company["metrics"].copy()
earnings = company["earnings"]
score = company["score"]

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

summary, score_col, earnings_col, volume_col = st.columns(4)
summary.metric("Last close", f"${latest['close']:,.2f}" if pd.notna(latest["close"]) else "—")
score_col.metric("Attention score", f"{score.get('attention_score', 0):.1f}/100")
earnings_col.metric("Earnings date", earnings.get("earnings_date", "—"))
volume_col.metric(
    "Latest volume",
    f"{int(latest['volume']):,}" if pd.notna(latest["volume"]) else "—",
)

st.divider()
chart_col, gauge_col = st.columns([1.6, 1])

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

with gauge_col:
    st.subheader("Attention score")
    gauge = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score.get("attention_score", 0),
            number={"suffix": " / 100", "font": {"color": "#f3f7ff"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#9fb0cc"},
                "bar": {"color": "#60a5fa"},
                "bgcolor": "#121c31",
                "bordercolor": "#23304d",
                "steps": [
                    {"range": [0, 35], "color": "#1e293b"},
                    {"range": [35, 70], "color": "#263752"},
                    {"range": [70, 100], "color": "#1f4c50"},
                ],
            },
        )
    )
    gauge.update_layout(
        height=300, margin=dict(l=20, r=20, t=30, b=10), paper_bgcolor="#121c31"
    )
    st.plotly_chart(gauge, use_container_width=True, config={"displayModeBar": False})

    st.caption("50% StockTwits mentions gained · 30% volume gained · 20% price momentum")
    st.metric("Est. EPS", _format_value(earnings.get("estimated_eps"), "$%.2f"))
    st.metric("Est. revenue", format_market_cap(earnings.get("estimated_revenue")))

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
