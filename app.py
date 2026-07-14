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


data = get_data()
attention = data["attention"]
earnings = data["earnings"]
search_growth = data["search_growth"]

with st.sidebar:
    st.markdown("## ◈ Earnings Intel")
    st.caption("Investor attention before earnings")
    st.divider()
    st.markdown("**Dashboard**")
    st.caption("Use the Company page in the sidebar for individual research.")
    st.divider()
    st.markdown("**Version 1 model**")
    st.caption("50% search growth · 30% volume · 20% price momentum")
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
                    with st.spinner("Collecting earnings, prices, and trends..."):
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
metric_columns = st.columns(4)
metric_columns[0].metric("Tracked companies", f"{len(attention):,}")
metric_columns[1].metric("Top attention score", f"{attention['attention_score'].max():.1f}/100")
metric_columns[2].metric(
    "Average attention", f"{attention['attention_score'].mean():.1f}/100"
)
metric_columns[3].metric("Next earnings", next_earnings)

st.divider()
left, right = st.columns([1.35, 1])

with left:
    st.subheader("Top attention-ranked companies")
    top_attention = attention.head(10).copy()
    top_attention.insert(0, "rank", range(1, len(top_attention) + 1))
    st.dataframe(
        top_attention[
            [
                "rank",
                "ticker",
                "company_name",
                "earnings_date",
                "attention_score",
                "trends_growth_pct",
                "volume_growth_pct",
                "price_growth_pct",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "attention_score": st.column_config.ProgressColumn(
                "Attention Score", min_value=0, max_value=100, format="%.1f"
            ),
            "trends_growth_pct": st.column_config.NumberColumn(
                "Search Growth (7D)", format="%.1f%%"
            ),
            "volume_growth_pct": st.column_config.NumberColumn(
                "Volume Growth (7D)", format="%.1f%%"
            ),
            "price_growth_pct": st.column_config.NumberColumn(
                "Price Momentum (7D)", format="%.1f%%"
            ),
        },
    )

with right:
    st.subheader("Attention leaders")
    chart_data = top_attention.sort_values("attention_score")
    figure = px.bar(
        chart_data,
        x="attention_score",
        y="ticker",
        orientation="h",
        color="attention_score",
        color_continuous_scale=["#273a66", "#4f8cff", "#6ee7b7"],
        range_color=[0, 100],
    )
    figure.update_layout(
        height=355,
        margin=dict(l=0, r=0, t=10, b=0),
        coloraxis_showscale=False,
        paper_bgcolor="#121c31",
        plot_bgcolor="#121c31",
        font_color="#dbeafe",
        xaxis_title="Score",
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
        st.dataframe(
            earnings.head(10),
            use_container_width=True,
            hide_index=True,
            column_config={
                "estimated_eps": st.column_config.NumberColumn("Est. EPS", format="%.2f"),
                "estimated_revenue": st.column_config.NumberColumn(
                    "Est. Revenue", format="$%.2f"
                ),
            },
        )

with growth_col:
    st.subheader("Search growth rankings")
    if search_growth.empty:
        st.info("Google Trends data is currently unavailable. Run a refresh later.")
    else:
        display_growth = search_growth[
            ["ticker", "company_name", "trends_growth_pct"]
        ].head(10)
        st.dataframe(
            display_growth,
            use_container_width=True,
            hide_index=True,
            column_config={
                "trends_growth_pct": st.column_config.NumberColumn(
                    "Search Growth (7D)", format="%.1f%%"
                )
            },
        )
