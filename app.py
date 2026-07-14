"""Earnings Intelligence Platform — Streamlit homepage."""

import hmac

import pandas as pd
import plotly.express as px
import streamlit as st

from config.secrets import get_setting
from src.dashboard.data import format_market_cap, load_dashboard_data
from src.pipeline import run_refresh_pipeline


st.set_page_config(
    page_title="Earnings Intelligence",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .stApp { background: #0b1120; }
        [data-testid="stMetric"] {
            background: #121c31; border: 1px solid #23304d; border-radius: 10px;
            padding: 14px;
        }
        [data-testid="stMetricLabel"] { color: #9fb0cc; }
        [data-testid="stMetricValue"] { color: #f3f7ff; }
        h1, h2, h3 { color: #f3f7ff; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60)
def get_data() -> dict[str, pd.DataFrame]:
    """Cache database reads briefly to keep dashboard interactions fast."""
    return load_dashboard_data()


data = get_data()
attention = data["attention"]
earnings = data["earnings"]
social_growth = data["social_growth"]
most_mentioned = data["most_mentioned"]

with st.sidebar:
    st.markdown("## ◈ Earnings Intel")
    st.caption("Investor attention before earnings")
    st.divider()
    st.markdown("**Dashboard**")
    st.caption("Use the Company page in the sidebar for individual research.")
    st.divider()
    st.markdown("**Version 1 model**")
    st.caption("50% StockTwits mentions gained · 30% volume gained · 20% price momentum")
    if st.button("Reload database", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    with st.expander("Admin: refresh data"):
        configured_token = get_setting("ADMIN_REFRESH_TOKEN")
        if not configured_token:
            st.caption(
                "Set ADMIN_REFRESH_TOKEN in `.streamlit/secrets.toml` "
                "(or app Secrets on Streamlit Cloud) to enable this."
            )
        else:
            entered_token = st.text_input("Admin token", type="password")
            if st.button("Run full refresh now", use_container_width=True):
                if entered_token and hmac.compare_digest(
                    str(entered_token), str(configured_token)
                ):
                    with st.spinner("Collecting earnings, prices, and StockTwits mentions..."):
                        result = run_refresh_pipeline()
                    for message in result.messages:
                        st.write(f"- {message}")
                    st.success("Refresh complete.")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Incorrect admin token.")

st.title("Earnings Intelligence")
st.caption("Detecting unusual investor attention ahead of upcoming earnings.")

if attention.empty:
    st.warning(
        "No dashboard data is available yet.\n\n"
        "**Locally:** run `python scripts/refresh_data.py` from the project folder.\n\n"
        "**On a deployed app:** open **Admin: refresh data** in the sidebar and "
        "run a refresh with the admin token."
    )
    st.stop()

next_earnings = earnings["earnings_date"].min() if not earnings.empty else "—"
top_mentions_value = (
    most_mentioned["current_mentions"].max() if not most_mentioned.empty else None
)
metric_columns = st.columns(4)
metric_columns[0].metric("Tracked companies", f"{len(attention):,}")
metric_columns[1].metric(
    "Most searched today",
    f"{top_mentions_value:,.0f}" if top_mentions_value is not None else "—",
)
metric_columns[2].metric(
    "Average attention score", f"{attention['attention_score'].mean():.1f}/100"
)
metric_columns[3].metric("Next earnings", next_earnings)

st.divider()
left, right = st.columns([1.35, 1])

# Category 1: who is being searched/talked about the most *right now*
# (absolute level). Separate from the growth category below, which tracks
# who gained the most searches over the last 7 days.
with left:
    st.subheader("Most searched companies")
    st.caption("Ranked by current StockTwits search volume.")
    if most_mentioned.empty:
        st.info("StockTwits mention data is currently unavailable. Run a refresh later.")
    else:
        top_attention = most_mentioned.head(10).copy()
        top_attention.insert(0, "rank", range(1, len(top_attention) + 1))
        st.dataframe(
            top_attention[
                [
                    "rank",
                    "ticker",
                    "company_name",
                    "earnings_date",
                    "current_mentions",
                    "attention_score",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "current_mentions": st.column_config.NumberColumn(
                    "Current Searches", format="%,.0f"
                ),
                "attention_score": st.column_config.ProgressColumn(
                    "Attention Score", min_value=0, max_value=100, format="%.1f"
                ),
            },
        )

with right:
    st.subheader("Search volume leaders")
    if most_mentioned.empty:
        st.info("StockTwits mention data is currently unavailable. Run a refresh later.")
    else:
        chart_data = most_mentioned.head(10).sort_values("current_mentions")
        figure = px.bar(
            chart_data,
            x="current_mentions",
            y="ticker",
            orientation="h",
            color="current_mentions",
            color_continuous_scale=["#273a66", "#4f8cff", "#6ee7b7"],
        )
        figure.update_layout(
            height=355,
            margin=dict(l=0, r=0, t=10, b=0),
            coloraxis_showscale=False,
            paper_bgcolor="#121c31",
            plot_bgcolor="#121c31",
            font_color="#dbeafe",
            xaxis_title="Searches",
            yaxis_title="",
        )
        st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})

st.divider()
upcoming_col, growth_col = st.columns(2)

with upcoming_col:
    st.subheader("Upcoming earnings")
    if earnings.empty:
        st.info("No earnings events are available in the next 30 days.")
    else:
        display_earnings = earnings.head(10).copy()
        display_earnings["estimated_revenue"] = display_earnings[
            "estimated_revenue"
        ].apply(format_market_cap)
        st.dataframe(
            display_earnings,
            use_container_width=True,
            hide_index=True,
            column_config={
                "estimated_eps": st.column_config.NumberColumn("Est. EPS", format="%.2f"),
                "estimated_revenue": st.column_config.TextColumn("Est. Revenue"),
            },
        )

# Category 2: who gained the most searches recently — separate from the
# absolute-level "most searched" list above. A company can be climbing
# quickly off a small base without yet cracking the top-search list.
with growth_col:
    st.subheader("Highest increase in searches")
    st.caption("Ranked by StockTwits search growth over the last 7 days.")
    if social_growth.empty:
        st.info("StockTwits mention data is currently unavailable. Run a refresh later.")
    else:
        display_growth = social_growth[
            ["ticker", "company_name", "earnings_date", "social_change"]
        ].head(10)
        st.dataframe(
            display_growth,
            use_container_width=True,
            hide_index=True,
            column_config={
                "social_change": st.column_config.NumberColumn(
                    "Searches Gained (7D)", format="%+,.0f"
                )
            },
        )
