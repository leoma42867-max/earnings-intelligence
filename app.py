"""Earnings Intelligence Platform — Streamlit homepage."""

import hmac

import pandas as pd
import plotly.express as px
import streamlit as st

from config.secrets import get_setting
from src.dashboard.data import load_dashboard_data
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


def _render_ranked_table(
    data: pd.DataFrame,
    value_column: str,
    value_label: str,
    value_format: str,
) -> None:
    """Render a numbered top-10 table shared by Yahoo and StockTwits sections."""
    display = data.head(10).copy()
    display.insert(0, "rank", range(1, len(display) + 1))
    st.dataframe(
        display[
            ["rank", "ticker", "company_name", "earnings_date", value_column]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            value_column: st.column_config.NumberColumn(value_label, format=value_format),
        },
    )


def _render_mention_chart(data: pd.DataFrame, x_column: str, x_title: str) -> None:
    """Render a horizontal bar chart for absolute search-volume leaders."""
    chart_data = data.head(10).sort_values(x_column)
    max_value = chart_data[x_column].max()
    x_max = max(max_value * 1.15, 35)
    figure = px.bar(
        chart_data,
        x=x_column,
        y="ticker",
        orientation="h",
        color=x_column,
        color_continuous_scale=["#273a66", "#4f8cff", "#6ee7b7"],
    )
    figure.update_layout(
        height=420,
        margin=dict(l=0, r=0, t=10, b=0),
        coloraxis_showscale=False,
        paper_bgcolor="#121c31",
        plot_bgcolor="#121c31",
        font_color="#dbeafe",
        xaxis_title=x_title,
        yaxis_title="",
        xaxis=dict(range=[0, x_max]),
    )
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})


def _render_yahoo_chart(data: pd.DataFrame) -> None:
    """Render Yahoo trending ranks as bars (lower rank number = longer bar)."""
    chart_data = data.head(10).copy()
    chart_data["trend_strength"] = 101 - chart_data["current_yahoo_rank"]
    chart_data = chart_data.sort_values("trend_strength")
    figure = px.bar(
        chart_data,
        x="trend_strength",
        y="ticker",
        orientation="h",
        color="trend_strength",
        color_continuous_scale=["#273a66", "#4f8cff", "#6ee7b7"],
    )
    figure.update_layout(
        height=420,
        margin=dict(l=0, r=0, t=10, b=0),
        coloraxis_showscale=False,
        paper_bgcolor="#121c31",
        plot_bgcolor="#121c31",
        font_color="#dbeafe",
        xaxis_title="Trend strength (#1 = highest)",
        yaxis_title="",
    )
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})


data = get_data()
attention = data["attention"]
earnings = data["earnings"]
social_growth = data["social_growth"]
most_mentioned = data["most_mentioned"]
most_trending_yahoo = data["most_trending_yahoo"]
yahoo_rank_growth = data["yahoo_rank_growth"]

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
                    with st.spinner(
                        "Collecting earnings, prices, StockTwits mentions, "
                        "and Yahoo trending ranks..."
                    ):
                        result = run_refresh_pipeline()
                    for message in result.messages:
                        st.write(f"- {message}")
                    st.success("Refresh complete.")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Incorrect admin token.")

st.title("Most Watched Upcoming Earnings")
st.caption(
    "Companies ranked based on investor search activity ahead of earnings reports"
)

if attention.empty:
    st.warning(
        "No dashboard data is available yet.\n\n"
        "**Locally:** run `python scripts/refresh_data.py` from the project folder.\n\n"
        "**On a deployed app:** open **Admin: refresh data** in the sidebar and "
        "run a refresh with the admin token."
    )
    st.stop()

next_earnings = earnings["earnings_date"].min() if not earnings.empty else "—"
top_yahoo = (
    most_trending_yahoo.iloc[0]
    if not most_trending_yahoo.empty
    else None
)
top_mentions_value = (
    most_mentioned["current_mentions"].max() if not most_mentioned.empty else None
)

metric_columns = st.columns(5)
metric_columns[0].metric("Tracked companies", f"{len(attention):,}")
metric_columns[1].metric(
    "Top Yahoo trend",
    f"#{int(top_yahoo['current_yahoo_rank'])}" if top_yahoo is not None else "—",
)
metric_columns[2].metric(
    "Top StockTwits searches",
    f"{top_mentions_value:,.0f}" if top_mentions_value is not None else "—",
)
metric_columns[3].metric(
    "Average attention score", f"{attention['attention_score'].mean():.1f}/100"
)
metric_columns[4].metric("Next earnings", next_earnings)

st.divider()
st.subheader("Most searched companies")

yahoo_col, stocktwits_col = st.columns(2)

with yahoo_col:
    st.markdown("**Yahoo Finance**")
    if most_trending_yahoo.empty:
        st.info("Yahoo trending data is unavailable. Run a refresh later.")
    else:
        _render_ranked_table(
            most_trending_yahoo,
            "current_yahoo_rank",
            "Trend Rank",
            "%.0f",
        )

with stocktwits_col:
    st.markdown("**StockTwits**")
    if most_mentioned.empty:
        st.info("StockTwits mention data is unavailable. Run a refresh later.")
    else:
        _render_ranked_table(
            most_mentioned,
            "current_mentions",
            "Current Searches",
            "%,.0f",
        )

st.subheader("Search volume leaders")
yahoo_chart_col, stocktwits_chart_col = st.columns(2)

with yahoo_chart_col:
    st.markdown("**Yahoo Finance**")
    st.caption("Source: Yahoo Finance US trending symbols API, refreshed daily.")
    if most_trending_yahoo.empty:
        st.info("Yahoo trending data is unavailable. Run a refresh later.")
    else:
        _render_yahoo_chart(most_trending_yahoo)

with stocktwits_chart_col:
    st.markdown("**StockTwits**")
    st.caption("Source: StockTwits public mention stream, refreshed daily.")
    if most_mentioned.empty:
        st.info("StockTwits mention data is unavailable. Run a refresh later.")
    else:
        _render_mention_chart(most_mentioned, "current_mentions", "Searches")

st.divider()
st.subheader("Highest increase in searches")

yahoo_growth_col, stocktwits_growth_col = st.columns(2)

with yahoo_growth_col:
    st.markdown("**Yahoo Finance**")
    st.caption("Ranked by how many trending positions climbed over the last 7 days.")
    if yahoo_rank_growth.empty:
        st.info("Yahoo trending history is unavailable. Run a refresh later.")
    else:
        _render_ranked_table(
            yahoo_rank_growth,
            "yahoo_rank_change",
            "Ranks Climbed (7D)",
            "%+,.0f",
        )

with stocktwits_growth_col:
    st.markdown("**StockTwits**")
    st.caption("Ranked by StockTwits search growth over the last 7 days.")
    if social_growth.empty:
        st.info("StockTwits mention data is unavailable. Run a refresh later.")
    else:
        _render_ranked_table(
            social_growth,
            "social_change",
            "Searches Gained (7D)",
            "%+,.0f",
        )
