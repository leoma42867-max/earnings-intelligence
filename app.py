"""Earnings Intelligence Platform — Streamlit homepage."""

import hmac
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from config.secrets import get_setting
from src.dashboard.data import (
    build_anticipated_earnings_calendar,
    build_earnings_spillover,
    format_last_data_refresh,
    get_last_data_refresh_at,
    load_dashboard_data,
)
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
        html, body, [data-testid="stAppViewContainer"], .stApp {
            background-color: #0b1120 !important;
        }
        [data-testid="stHeader"] { background: transparent; }
        .stApp { background: #0b1120; }
        [data-testid="stMetric"] {
            background: #121c31; border: 1px solid #23304d; border-radius: 10px;
            padding: 14px;
        }
        [data-testid="stMetricLabel"] { color: #9fb0cc; }
        [data-testid="stMetricValue"] { color: #f3f7ff; }
        h1, h2, h3 { color: #f3f7ff; }
        .earnings-cal {
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 6px;
            margin: 0.4rem 0 0.2rem 0;
        }
        .earnings-cal-head {
            color: #9fb0cc;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            text-align: center;
            padding: 0.35rem 0;
        }
        .earnings-cal-day {
            min-height: 118px;
            background: #121c31;
            border: 1px solid #23304d;
            border-radius: 10px;
            padding: 6px 6px 8px 6px;
        }
        .earnings-cal-day.empty {
            background: transparent;
            border-color: transparent;
        }
        .earnings-cal-day.today {
            border-color: #4f8cff;
            box-shadow: inset 0 0 0 1px rgba(79, 140, 255, 0.35);
        }
        .earnings-cal-day.past {
            opacity: 0.88;
        }
        .earnings-cal-num {
            color: #9fb0cc;
            font-size: 0.7rem;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .earnings-cal-day.today .earnings-cal-num { color: #93c5fd; }
        .earnings-cal-ticker {
            display: block;
            color: #f3f7ff;
            font-size: 0.98rem;
            font-weight: 700;
            line-height: 1.25;
            letter-spacing: 0.01em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .earnings-cal-ticker.sent-bullish { color: #6ee7b7; }
        .earnings-cal-ticker.sent-mixed { color: #fbbf24; }
        .earnings-cal-ticker.sent-bearish { color: #f87171; }
        .earnings-cal-ticker.sent-unknown { color: #94a3b8; }
        .earnings-cal-ticker.heat-high {
            color: #e2e8f0;
            text-shadow: 0 0 10px rgba(110, 231, 183, 0.35);
            border-bottom: 2px solid rgba(110, 231, 183, 0.65);
        }
        .earnings-cal-ticker.heat-mid { color: #cbd5e1; }
        .earnings-cal-ticker.heat-low,
        .earnings-cal-ticker.heat-none { color: #94a3b8; font-weight: 600; }
        .earnings-cal-legend {
            color: #9fb0cc;
            font-size: 0.82rem;
            margin: 0.55rem 0 0.15rem 0;
            line-height: 1.45;
        }
        .spillover-card {
            background: #121c31;
            border: 1px solid #23304d;
            border-radius: 10px;
            padding: 12px 14px;
            margin-bottom: 8px;
        }
        .spillover-title {
            color: #f3f7ff;
            font-weight: 700;
            font-size: 0.95rem;
        }
        .spillover-meta { color: #9fb0cc; font-size: 0.82rem; margin-top: 2px; }
        .spillover-peers { color: #cbd5e1; font-size: 0.88rem; margin-top: 6px; }
        .spillover-status-bullish { color: #6ee7b7; }
        .spillover-status-bearish { color: #f87171; }
        .spillover-status-mixed { color: #fbbf24; }
        .spillover-status-upcoming { color: #93c5fd; }
        .spillover-status-unknown { color: #94a3b8; }
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


def _render_earnings_calendar(calendar_data: dict[str, object]) -> None:
    """Render a month grid of the highest-attention earnings dates."""
    today = calendar_data["today"]
    days = calendar_data["days"]
    first_weekday = int(calendar_data["first_weekday"])
    days_in_month = int(calendar_data["days_in_month"])

    cells: list[str] = []
    for label in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
        cells.append(f'<div class="earnings-cal-head">{label}</div>')

    for _ in range(first_weekday):
        cells.append('<div class="earnings-cal-day empty"></div>')

    for day in range(1, days_in_month + 1):
        day_date = date(int(calendar_data["year"]), int(calendar_data["month"]), day)
        classes = ["earnings-cal-day"]
        if day_date == today:
            classes.append("today")
        elif day_date < today:
            classes.append("past")

        tickers = days.get(day, [])
        ticker_parts: list[str] = []
        for item in tickers:
            label = str(item["ticker"])
            title = str(item.get("company_name") or label)
            css = "earnings-cal-ticker"
            if item.get("is_past"):
                sentiment = item.get("sentiment") or "unknown"
                css = f"{css} sent-{sentiment}"
                reaction = item.get("reaction_pct")
                if reaction is not None:
                    title = f"{title} · {reaction:+.1f}% after report"
            else:
                heat = item.get("heat") or "none"
                css = f"{css} heat-{heat}"
                momentum = item.get("momentum")
                if momentum:
                    label = f"{label} {momentum}"
                    title = f"{title} · pre-report momentum {momentum} (not earnings result)"
                score = item.get("attention_score")
                if score is not None:
                    title = f"{title} · attention {score:.0f}/100"
            ticker_parts.append(
                f'<span class="{css}" title="{title}">{label}</span>'
            )

        cells.append(
            f'<div class="{" ".join(classes)}">'
            f'<div class="earnings-cal-num">{day}</div>'
            f"{''.join(ticker_parts)}"
            f"</div>"
        )

    trailing = (7 - ((first_weekday + days_in_month) % 7)) % 7
    for _ in range(trailing):
        cells.append('<div class="earnings-cal-day empty"></div>')

    st.markdown(
        f'<div class="earnings-cal">{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="earnings-cal-legend">'
        "<b>Past days:</b> green = bullish price reaction (≥+3%), "
        "yellow = mixed (−3% to +3%), red = bearish (≤−3%). "
        "<b>Upcoming:</b> brighter tickers = higher attention heat; "
        "↑/↓ = pre-report price momentum (not the earnings outcome)."
        "</div>",
        unsafe_allow_html=True,
    )


def _render_earnings_spillover(spillover: list[dict[str, object]]) -> None:
    """Render mega-cap influencers and same-sector peers under the calendar."""
    if not spillover:
        st.caption("No mega-cap influencers on this month’s calendar yet.")
        return

    st.markdown("**Who can move the tape**")
    st.caption(
        "Large names on this month’s calendar and same-sector peers that may "
        "be lifted or dragged with them. Macro headlines coming later."
    )
    for item in spillover:
        status = str(item.get("status") or "unknown")
        status_label = status.replace("_", " ")
        reaction = item.get("reaction_pct")
        reaction_bit = (
            f" · {reaction:+.1f}% after report" if reaction is not None else ""
        )
        peers = item.get("peers") or []
        peer_text = (
            ", ".join(str(peer["ticker"]) for peer in peers)
            if peers
            else "No tracked same-sector peers yet"
        )
        st.markdown(
            f'<div class="spillover-card">'
            f'<div class="spillover-title">{item["ticker"]} '
            f'<span class="spillover-status-{status}">({status_label})</span>'
            f'{reaction_bit}</div>'
            f'<div class="spillover-meta">{item.get("company_name")} · '
            f'{item.get("sector")} · {item.get("watch_note")}</div>'
            f'<div class="spillover-peers"><b>Blast radius:</b> {peer_text}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

data = get_data()
attention = data["attention"]
earnings = data["earnings"]
social_growth = data["social_growth"]
most_mentioned = data["most_mentioned"]
most_trending_yahoo = data["most_trending_yahoo"]
yahoo_rank_growth = data["yahoo_rank_growth"]
yahoo_rank_drop = data["yahoo_rank_drop"]
social_drop = data["social_drop"]

with st.sidebar:
    st.markdown("## ◈ Earnings Intel")
    st.caption("Investor attention before earnings")
    st.divider()
    st.markdown("**Dashboard**")
    st.caption("Use the Company page in the sidebar for individual research.")
    st.divider()
    st.markdown("**Version 1 model**")
    st.caption(
        "40% StockTwits mentions · 25% Yahoo trend climb · "
        "20% relative volume · 15% price momentum"
    )
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
refresh_label = format_last_data_refresh(get_last_data_refresh_at())
if refresh_label:
    st.caption(refresh_label)

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
st.subheader("Trending ahead of earnings")

yahoo_col, stocktwits_col = st.columns(2)

with yahoo_col:
    st.markdown("**Most trending**")
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
    st.markdown("**Most mentioned**")
    if most_mentioned.empty:
        st.info("StockTwits mention data is unavailable. Run a refresh later.")
    else:
        _render_ranked_table(
            most_mentioned,
            "current_mentions",
            "Current Mentions",
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
        st.info("No Yahoo rank climbers in the last 7 days yet.")
    else:
        _render_ranked_table(
            yahoo_rank_growth,
            "yahoo_rank_change",
            "Ranks Climbed (7D)",
            "%+,.0f",
        )

with stocktwits_growth_col:
    st.markdown("**StockTwits**")
    st.caption("Ranked by StockTwits mention growth over the last 7 days.")
    if social_growth.empty:
        st.info("No StockTwits mention climbers in the last 7 days yet.")
    else:
        _render_ranked_table(
            social_growth,
            "social_change",
            "Mentions Gained (7D)",
            "%+,.0f",
        )

st.subheader("Biggest drop over the last 7 days")

yahoo_drop_col, stocktwits_drop_col = st.columns(2)

with yahoo_drop_col:
    st.markdown("**Yahoo Finance**")
    st.caption(
        "Ranked by how many trending positions fell over the last 7 days "
        "(includes tickers that left Yahoo's top 100)."
    )
    if yahoo_rank_drop.empty:
        st.info("No Yahoo rank declines in the last 7 days yet.")
    else:
        _render_ranked_table(
            yahoo_rank_drop,
            "yahoo_rank_change",
            "Ranks Fallen (7D)",
            "%+,.0f",
        )

with stocktwits_drop_col:
    st.markdown("**StockTwits**")
    st.caption("Ranked by StockTwits mention decline over the last 7 days.")
    if social_drop.empty:
        st.info("No StockTwits mention declines in the last 7 days yet.")
    else:
        _render_ranked_table(
            social_drop,
            "social_change",
            "Mentions Lost (7D)",
            "%+,.0f",
        )

st.divider()
st.subheader("Most anticipated earnings this month")
month_calendar = build_anticipated_earnings_calendar()
st.caption(
    f"{month_calendar['month_label']} · past days colored by post-report price reaction · "
    "upcoming days by attention heat · updates automatically each month"
)
if month_calendar["event_count"] == 0:
    st.info("No tracked earnings dates fall in this calendar month yet.")
else:
    _render_earnings_calendar(month_calendar)
    spillover = build_earnings_spillover(month_calendar, attention)
    st.subheader("Earnings spillover watch")
    _render_earnings_spillover(spillover)
