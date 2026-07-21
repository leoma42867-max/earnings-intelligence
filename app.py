"""Earnings Intelligence Platform — Streamlit homepage."""

import hmac
from datetime import date

import pandas as pd
import streamlit as st

from config.secrets import get_setting
from src.dashboard.data import (
    attention_tier_label,
    build_anticipated_earnings_calendar,
    build_earnings_spillover,
    build_this_week_focus,
    build_weekly_postmortem,
    coverage_counts,
    format_last_data_refresh,
    get_last_data_refresh_at,
    load_dashboard_data,
)
from src.pipeline import run_refresh_pipeline


st.set_page_config(
    page_title="MarketsLite",
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
            text-decoration: none;
        }
        a.earnings-cal-ticker:hover { opacity: 0.85; }
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
        .mobile-cal-hint {
            display: none;
            color: #9fb0cc;
            font-size: 0.85rem;
            margin: 0.4rem 0 0.2rem 0;
        }
        .this-week-list { margin: 0.35rem 0 0.6rem 0; }
        .this-week-row {
            display: flex;
            gap: 10px;
            align-items: baseline;
            flex-wrap: wrap;
            padding: 8px 10px;
            border-bottom: 1px solid #23304d;
        }
        .this-week-date { color: #9fb0cc; font-size: 0.82rem; min-width: 4.5rem; }
        .this-week-ticker {
            color: #f3f7ff;
            font-weight: 700;
            font-size: 1rem;
            text-decoration: none;
        }
        .this-week-ticker:hover { color: #93c5fd; }
        .this-week-meta { color: #9fb0cc; font-size: 0.85rem; }
        .this-week-heat-high { color: #6ee7b7; }
        .this-week-heat-mid { color: #93c5fd; }
        .this-week-heat-low, .this-week-heat-none { color: #94a3b8; }
        .why-chip-inline {
            color: #9fb0cc;
            font-size: 0.82rem;
        }
        .postmortem-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin: 0.4rem 0 0.8rem 0;
        }
        .postmortem-col {
            background: #121c31;
            border: 1px solid #23304d;
            border-radius: 10px;
            padding: 12px 14px;
        }
        .postmortem-heading {
            color: #f3f7ff;
            font-weight: 700;
            margin-bottom: 8px;
        }
        .postmortem-row {
            display: flex;
            justify-content: space-between;
            gap: 8px;
            padding: 4px 0;
            font-size: 0.92rem;
        }
        .postmortem-row a {
            color: #f3f7ff;
            font-weight: 700;
            text-decoration: none;
        }
        .postmortem-row a:hover { color: #93c5fd; }
        .postmortem-beat { color: #6ee7b7; }
        .postmortem-miss { color: #f87171; }
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
        .spillover-title a {
            color: inherit;
            text-decoration: none;
        }
        .spillover-title a:hover { color: #93c5fd; }
        .spillover-meta { color: #9fb0cc; font-size: 0.82rem; margin-top: 2px; }
        .spillover-peers { color: #cbd5e1; font-size: 0.88rem; margin-top: 6px; }
        .spillover-peers a {
            color: #93c5fd;
            text-decoration: none;
            font-weight: 600;
        }
        .spillover-peers a:hover { text-decoration: underline; }
        .spillover-status-bullish { color: #6ee7b7; }
        .spillover-status-bearish { color: #f87171; }
        .spillover-status-mixed { color: #fbbf24; }
        .spillover-status-upcoming { color: #93c5fd; }
        .spillover-status-unknown { color: #94a3b8; }
        @media (max-width: 768px) {
            .earnings-cal,
            .earnings-cal-legend { display: none !important; }
            .mobile-cal-hint { display: block; }
            .postmortem-grid { grid-template-columns: 1fr; }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60)
def get_data() -> dict[str, pd.DataFrame]:
    """Cache database reads briefly to keep dashboard interactions fast."""
    return load_dashboard_data()


def _company_href(ticker: str) -> str:
    """Build an in-app Company page link for a ticker."""
    return f"/Company?ticker={str(ticker).upper()}"


def _render_ranked_table(
    data: pd.DataFrame,
    value_column: str,
    value_label: str,
    value_format: str,
    *,
    show_value: bool = True,
) -> None:
    """Render a numbered top-10 table shared by Yahoo and StockTwits sections."""
    display = data.head(10).copy()
    display.insert(0, "rank", range(1, len(display) + 1))
    display["ticker_link"] = display["ticker"].map(_company_href)
    columns = ["rank", "ticker_link", "company_name", "earnings_date"]
    column_config: dict[str, object] = {
        "ticker_link": st.column_config.LinkColumn(
            "Ticker",
            display_text=r"ticker=([A-Z0-9.\-]+)",
        ),
    }
    if show_value:
        columns.append(value_column)
        column_config[value_column] = st.column_config.NumberColumn(
            value_label, format=value_format
        )
    st.dataframe(
        display[columns],
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )


def _render_this_week(focus: list[dict[str, object]]) -> None:
    """Render the mobile-first This week’s prints list."""
    if not focus:
        st.info("No tracked prints in the next 7 days.")
        return
    rows: list[str] = []
    for item in focus:
        heat = str(item.get("heat") or "none")
        headline = item.get("attention_headline") or attention_tier_label(
            item.get("attention_tier")
        )
        chips = item.get("why_chips") or []
        chip_text = " · ".join(str(chip) for chip in chips[:2])
        event_date = item["earnings_date"]
        date_text = (
            event_date.strftime("%b %d")
            if hasattr(event_date, "strftime")
            else str(event_date)
        )
        rows.append(
            f'<div class="this-week-row">'
            f'<span class="this-week-date">{date_text}</span>'
            f'<a class="this-week-ticker" href="{_company_href(str(item["ticker"]))}">'
            f'{item["ticker"]}</a>'
            f'<span class="this-week-meta this-week-heat-{heat}">{headline}</span>'
            f'<span class="why-chip-inline">{chip_text}</span>'
            f"</div>"
        )
    st.markdown(
        f'<div class="this-week-list">{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


def _render_weekly_postmortem(postmortem: dict[str, list[dict[str, object]]]) -> None:
    """Render biggest post-report beats and misses from the last week."""
    beats = postmortem.get("beats") or []
    misses = postmortem.get("misses") or []
    if not beats and not misses:
        st.info("No post-report price reactions in the last 7 days yet.")
        return

    def _rows(items: list[dict[str, object]], kind: str) -> str:
        if not items:
            return '<div class="this-week-meta">None yet.</div>'
        parts: list[str] = []
        for item in items:
            reaction = float(item["reaction_pct"])
            parts.append(
                f'<div class="postmortem-row">'
                f'<a href="{_company_href(str(item["ticker"]))}">{item["ticker"]}</a>'
                f'<span class="postmortem-{kind}">{reaction:+.1f}%</span>'
                f"</div>"
            )
        return "".join(parts)

    st.markdown(
        f'<div class="postmortem-grid">'
        f'<div class="postmortem-col">'
        f'<div class="postmortem-heading">Biggest beats</div>'
        f"{_rows(beats, 'beat')}</div>"
        f'<div class="postmortem-col">'
        f'<div class="postmortem-heading">Biggest misses</div>'
        f"{_rows(misses, 'miss')}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Based on next-day price reaction after the report — not attention heat."
    )


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
                headline = item.get("attention_headline")
                if headline:
                    title = f"{title} · {headline}"
                elif score is not None:
                    title = f"{title} · attention index {score:.0f}"
            ticker_parts.append(
                f'<a class="{css}" href="{_company_href(str(item["ticker"]))}" '
                f'title="{title}">{label}</a>'
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
        "<b>Upcoming:</b> brighter tickers = higher relative attention "
        "(On the radar / Warming up); "
        "↑/↓ = pre-report price momentum (not the earnings outcome)."
        "</div>"
        '<div class="mobile-cal-hint">'
        "Month calendar is easiest on desktop — use This week’s prints above."
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
            ", ".join(
                f'<a href="{_company_href(str(peer["ticker"]))}">{peer["ticker"]}</a>'
                for peer in peers
            )
            if peers
            else "No tracked same-sector peers yet"
        )
        st.markdown(
            f'<div class="spillover-card">'
            f'<div class="spillover-title">'
            f'<a href="{_company_href(str(item["ticker"]))}">{item["ticker"]}</a> '
            f'<span class="spillover-status-{status}">({status_label})</span>'
            f"{reaction_bit}</div>"
            f'<div class="spillover-meta">{item.get("company_name")} · '
            f'{item.get("sector")} · {item.get("watch_note")}</div>'
            f'<div class="spillover-peers"><b>Blast radius:</b> {peer_text}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

data = get_data()
attention = data["attention"]
earnings = data["earnings"]
most_mentioned = data["most_mentioned"]
yahoo_rank_growth = data["yahoo_rank_growth"]

with st.sidebar:
    st.markdown("## ◈ MarketsLite")
    st.caption("Investor attention before earnings")
    st.divider()
    st.markdown("**Dashboard**")
    st.caption("Click any ticker to open Company research.")
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

coverage = coverage_counts(attention, data["metrics"])
st.caption(
    f"Tracking {coverage['tracked']} companies with upcoming earnings · "
    f"Yahoo ranks available for {coverage['yahoo']} · "
    f"StockTwits mentions for {coverage['stocktwits']}"
)

next_earnings = earnings["earnings_date"].min() if not earnings.empty else "—"

metric_columns = st.columns(2)
metric_columns[0].metric("Tracked companies", f"{len(attention):,}")
metric_columns[1].metric("Next earnings", next_earnings)

st.divider()
st.subheader("This week’s prints")
st.caption(
    "Highest-attention upcoming reports in the next 7 days. "
    "Rank is among all tracked upcoming earnings — not a grade out of 100."
)
_render_this_week(build_this_week_focus(attention))

month_calendar = build_anticipated_earnings_calendar()
st.subheader("Last 7 days: biggest beats & misses")
_render_weekly_postmortem(build_weekly_postmortem(month_calendar))

st.divider()
st.subheader("Trending ahead of earnings")

yahoo_col, stocktwits_col = st.columns(2)

with yahoo_col:
    st.markdown("**Most Searched**")
    if yahoo_rank_growth.empty:
        st.info("No Yahoo rank climbers in the last 7 days yet.")
    else:
        _render_ranked_table(
            yahoo_rank_growth,
            "yahoo_rank_change",
            "Ranks Climbed (7D)",
            "%+,.0f",
        )

with stocktwits_col:
    st.markdown("**Most mentioned**")
    if most_mentioned.empty:
        st.info(
            "StockTwits mentions missing in the latest refresh — "
            "coverage may be incomplete."
        )
    else:
        _render_ranked_table(
            most_mentioned,
            "current_mentions",
            "Current Mentions",
            "%,.0f",
            show_value=False,
        )

st.divider()
st.subheader("Most anticipated earnings this month")
st.caption(
    f"{month_calendar['month_label']} · past days colored by post-report price reaction · "
    "upcoming days by relative attention (On the radar / Warming up) · "
    "updates automatically each month"
)
if month_calendar["event_count"] == 0:
    st.info("No tracked earnings dates fall in this calendar month yet.")
else:
    _render_earnings_calendar(month_calendar)
    spillover = build_earnings_spillover(month_calendar, attention)
    st.subheader("Earnings spillover watch")
    _render_earnings_spillover(spillover)
