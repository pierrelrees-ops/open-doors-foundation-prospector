"""Open Doors Foundation Prospector — Single-file Streamlit Application.
All code combined into one file. Only requires foundations.json in the same folder.
"""

import streamlit as st
import pandas as pd
import json
import io
import sqlite3
from datetime import datetime
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================
APP_TITLE = "Open Doors — Foundation Prospector"
ACCENT_COLOR = "#0054A6"
ACCENT_LIGHT = "#E8F0FE"

ALIGNMENT_COLORS = {"High": "#16A34A", "Medium": "#EA580C", "Low": "#6B7280"}
STATUS_COLORS = {
    "Not contacted": "#6B7280", "Researching": "#2563EB", "In progress": "#EA580C",
    "Applied": "#7C3AED", "Successful": "#16A34A", "Declined": "#DC2626", "On hold": "#CA8A04",
}
PIPELINE_STATUSES = ["Not contacted", "Researching", "In progress", "Applied", "Successful", "Declined", "On hold"]
CONTACT_METHODS = ["", "Email", "Phone", "Meeting", "Other"]
AU_STATES = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]
CHARITY_SIZES = ["Small", "Medium", "Large"]

COLUMN_DISPLAY_NAMES = {
    "name": "Foundation Name", "abn": "ABN", "state": "State", "alignment_score": "Alignment",
    "dgr1_status": "DGR1 Status", "total_revenue": "Revenue", "total_expenses": "Expenses",
    "grants_outside_au": "Grants (Intl)", "grants_inside_au": "Grants (AU)", "net_assets": "Net Assets",
    "donations_bequests": "Donations/Bequests", "investment_revenue": "Investment Revenue",
    "charity_size": "Size", "pipeline_status": "Status", "website": "Website",
    "international_funding": "Intl Funding", "denomination": "Denomination",
}


def format_currency(value):
    if value is None or value == "" or value == 0:
        return "$0"
    try:
        v = float(value)
        if v >= 1_000_000:
            return f"${v/1_000_000:,.1f}M"
        elif v >= 1_000:
            return f"${v/1_000:,.0f}K"
        else:
            return f"${v:,.0f}"
    except (ValueError, TypeError):
        return str(value)


# ============================================================
# DATA LOADING
# ============================================================
DATA_FILE = Path(__file__).parent / "foundations.json"
TRACKING_DB = Path(__file__).parent / "tracking.db"


def init_tracking_db():
    conn = sqlite3.connect(str(TRACKING_DB))
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS tracking ("
        "abn TEXT PRIMARY KEY, existing_relationship TEXT DEFAULT '',"
        "last_contact_date TEXT DEFAULT '', last_contact_method TEXT DEFAULT '',"
        "last_contact_notes TEXT DEFAULT '', next_action TEXT DEFAULT '',"
        "next_action_date TEXT DEFAULT '',"
        "pipeline_status TEXT DEFAULT 'Not contacted', internal_notes TEXT DEFAULT ''"
        ")"
    )
    conn.commit()
    conn.close()


def load_foundations():
    with open(DATA_FILE, "r") as f:
        foundations = json.load(f)
    df = pd.DataFrame(foundations)
    df["state"] = df["state"].str.upper().str.strip()
    numeric_cols = ["total_revenue", "total_expenses", "grants_outside_au", "grants_inside_au", "net_assets", "donations_bequests", "investment_revenue"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    init_tracking_db()
    conn = sqlite3.connect(str(TRACKING_DB))
    try:
        tracking_df = pd.read_sql("SELECT * FROM tracking", conn)
        if not tracking_df.empty:
            tracking_cols = ["existing_relationship", "last_contact_date", "last_contact_method", "last_contact_notes", "next_action", "next_action_date", "pipeline_status", "internal_notes"]
            for col in tracking_cols:
                if col in tracking_df.columns:
                    mapping = tracking_df.set_index("abn")[col].to_dict()
                    for abn, val in mapping.items():
                        if val:
                            mask = df["abn"] == abn
                            df.loc[mask, col] = val
    except Exception:
        pass
    finally:
        conn.close()
    return df


def save_tracking(abn, tracking_data):
    init_tracking_db()
    conn = sqlite3.connect(str(TRACKING_DB))
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tracking (abn, existing_relationship, last_contact_date, last_contact_method, last_contact_notes, next_action, next_action_date, pipeline_status, internal_notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(abn) DO UPDATE SET "
        "existing_relationship = excluded.existing_relationship, last_contact_date = excluded.last_contact_date, "
        "last_contact_method = excluded.last_contact_method, last_contact_notes = excluded.last_contact_notes, "
        "next_action = excluded.next_action, next_action_date = excluded.next_action_date, "
        "pipeline_status = excluded.pipeline_status, internal_notes = excluded.internal_notes",
        (abn, tracking_data.get("existing_relationship", ""), tracking_data.get("last_contact_date", ""),
         tracking_data.get("last_contact_method", ""), tracking_data.get("last_contact_notes", ""),
         tracking_data.get("next_action", ""), tracking_data.get("next_action_date", ""),
         tracking_data.get("pipeline_status", "Not contacted"), tracking_data.get("internal_notes", "")))
    conn.commit()
    conn.close()


# ============================================================
# FILTERS
# ============================================================
def apply_filters(df, filters):
    filtered = df.copy()
    if filters.get("search"):
        search = filters["search"].lower()
        text_cols = ["name", "also_known_as", "all_directors", "organisations_funded", "giving_themes", "internal_notes", "mission_summary", "main_director_name", "admin_contact_name", "notable_recipients"]
        mask = pd.Series(False, index=filtered.index)
        for col in text_cols:
            if col in filtered.columns:
                mask = mask | filtered[col].astype(str).str.lower().str.contains(search, na=False)
        filtered = filtered[mask]
    multi_select_filters = {"states": "state", "alignment_scores": "alignment_score", "dgr1_statuses": "dgr1_status", "intl_funding": "international_funding", "applications": "accepts_applications", "charity_sizes": "charity_size", "pipeline_statuses": "pipeline_status"}
    for key, col in multi_select_filters.items():
        if filters.get(key) and col in filtered.columns:
            filtered = filtered[filtered[col].isin(filters[key])]
    if filters.get("giving_themes"):
        mask = pd.Series(False, index=filtered.index)
        for theme in filters["giving_themes"]:
            mask = mask | filtered["giving_themes"].astype(str).str.lower().str.contains(theme.lower(), na=False)
        filtered = filtered[mask]
    if filters.get("denominations"):
        mask = pd.Series(False, index=filtered.index)
        for denom in filters["denominations"]:
            mask = mask | filtered["denomination"].astype(str).str.lower().str.contains(denom.lower(), na=False)
        filtered = filtered[mask]
    return filtered


def count_active_filters(filters):
    count = 0
    for key, value in filters.items():
        if value:
            if isinstance(value, (list, tuple)):
                if len(value) > 0:
                    count += 1
            elif isinstance(value, str) and value.strip():
                count += 1
    return count


# ============================================================
# EXPORT
# ============================================================
def create_excel_export(df, include_summary=False):
    output = io.BytesIO()
    display_df = df.copy().rename(columns={k: v for k, v in COLUMN_DISPLAY_NAMES.items() if k in df.columns})
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        display_df.to_excel(writer, sheet_name="Foundations", index=False)
        workbook = writer.book
        worksheet = writer.sheets["Foundations"]
        header_format = workbook.add_format({"bold": True, "bg_color": "#0054A6", "font_color": "#FFFFFF", "border": 1})
        for col_num, value in enumerate(display_df.columns):
            worksheet.write(0, col_num, value, header_format)
        for i, col in enumerate(display_df.columns):
            max_len = max(display_df[col].astype(str).map(len).max() if len(display_df) > 0 else 0, len(col))
            worksheet.set_column(i, i, min(max_len + 2, 50))
        if include_summary:
            summary_data = {
                "Metric": ["Total Foundations", "High Alignment", "Medium Alignment", "Low Alignment", "Total Revenue", "Total Intl Grants", "Total AU Grants"],
                "Value": [len(df), len(df[df["alignment_score"] == "High"]), len(df[df["alignment_score"] == "Medium"]), len(df[df["alignment_score"] == "Low"]),
                    f"${df['total_revenue'].sum():,.0f}", f"${df['grants_outside_au'].sum():,.0f}", f"${df['grants_inside_au'].sum():,.0f}"]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)
    output.seek(0)
    return output


def create_csv_export(df):
    display_df = df.copy().rename(columns={k: v for k, v in COLUMN_DISPLAY_NAMES.items() if k in df.columns})
    return display_df.to_csv(index=False).encode("utf-8")


# ============================================================
# PAGE SETUP
# ============================================================
st.set_page_config(page_title=APP_TITLE, page_icon="🔍", layout="wide", initial_sidebar_state="expanded")

st.markdown(f"""
<style>
    .stApp {{ background-color: #FFFFFF; color: #1F2937; }}
    .conf-banner {{ background-color: {ACCENT_LIGHT}; border: 1px solid #BFDBFE; border-radius: 8px; padding: 12px 20px; margin-bottom: 20px; font-size: 0.85rem; color: #1E40AF; line-height: 1.5; }}
    .conf-banner strong {{ color: #1E3A8A; }}
    .metric-card {{ background-color: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 10px; padding: 16px 20px; text-align: center; }}
    .metric-card .metric-value {{ font-size: 1.8rem; font-weight: 700; color: #111827; margin: 4px 0; }}
    .metric-card .metric-label {{ font-size: 0.8rem; color: #6B7280; text-transform: uppercase; letter-spacing: 0.05em; }}
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }}
    .badge-high {{ background-color: #DCFCE7; color: #166534; }}
    .badge-medium {{ background-color: #FFF7ED; color: #9A3412; }}
    .badge-low {{ background-color: #F3F4F6; color: #4B5563; }}
    .status-not-contacted {{ background-color: #F3F4F6; color: #4B5563; }}
    .status-researching {{ background-color: #DBEAFE; color: #1E40AF; }}
    .status-in-progress {{ background-color: #FFF7ED; color: #9A3412; }}
    .status-applied {{ background-color: #EDE9FE; color: #5B21B6; }}
    .status-successful {{ background-color: #DCFCE7; color: #166534; }}
    .status-declined {{ background-color: #FEE2E2; color: #991B1B; }}
    .status-on-hold {{ background-color: #FEF9C3; color: #854D0E; }}
    .section-header {{ color: {ACCENT_COLOR}; border-bottom: 2px solid {ACCENT_COLOR}; padding-bottom: 6px; margin-top: 24px; }}
    .criteria-card {{ background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 10px; padding: 20px; margin-bottom: 16px; }}
    .criteria-card h4 {{ color: #166534; margin-top: 0; }}
    .exclude-card {{ background-color: #FEF2F2; border: 1px solid #FECACA; border-radius: 10px; padding: 20px; margin-bottom: 16px; }}
    .exclude-card h4 {{ color: #991B1B; margin-top: 0; }}
    .note-card {{ background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 20px; margin-bottom: 16px; }}
    .section-divider {{ border-top: 2px solid {ACCENT_COLOR}; margin: 32px 0 24px 0; }}
    #MainMenu {{ visibility: hidden; }}
    footer {{ visibility: hidden; }}
    [data-testid="stSidebar"] {{ background-color: #F8FAFC; }}
    .stButton > button {{ border-radius: 6px; }}
</style>
""", unsafe_allow_html=True)


# ============================================================
# NAVIGATION
# ============================================================
page = st.sidebar.radio("Navigate", ["Foundation Database", "About This Database"], label_visibility="collapsed")


# ============================================================
# PAGE: FOUNDATION DATABASE
# ============================================================
if page == "Foundation Database":

    @st.cache_data(ttl=60)
    def get_data():
        return load_foundations()

    df = get_data()

    st.markdown("""
    <div class="conf-banner">
        <strong>This tool is purpose-built for Open Doors Australia. Please do not share this link.</strong><br>
        All information contained in this database is sourced from publicly available records
        (ACNC, ABR, organisation websites, and public reports). No Open Doors internal data has been used.
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<h1 style='color: {ACCENT_COLOR}; margin-bottom: 0;'>🔍 {APP_TITLE}</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='color: #6B7280; margin-top: 4px;'>Last data refresh: 27 March 2026 &nbsp;|&nbsp; Source: ACNC Charity Register & 2023 AIS Data</p>", unsafe_allow_html=True)

    # --- Sidebar Filters ---
    with st.sidebar:
        st.markdown(f"<h2 style='color: {ACCENT_COLOR};'>Filters</h2>", unsafe_allow_html=True)
        filters = {}
        filters["search"] = st.text_input("🔍 Search", placeholder="Foundation name, director, keywords...")
        st.markdown("---")
        filters["alignment_scores"] = st.multiselect("Alignment Score", options=["High", "Medium", "Low"], default=[])
        filters["pipeline_statuses"] = st.multiselect("Pipeline Status", options=PIPELINE_STATUSES, default=[])
        dgr1_options = sorted(df["dgr1_status"].unique().tolist())
        filters["dgr1_statuses"] = st.multiselect("DGR1 Status", options=dgr1_options, default=[])
        intl_options = sorted(df["international_funding"].unique().tolist())
        filters["intl_funding"] = st.multiselect("International Funding", options=intl_options, default=[])
        st.markdown("---")
        filters["states"] = st.multiselect("State", options=AU_STATES, default=[])
        filters["charity_sizes"] = st.multiselect("Charity Size", options=CHARITY_SIZES, default=[])
        st.markdown("---")
        if df["total_revenue"].max() > 0:
            max_rev = int(df["total_revenue"].max())
            rev_range = st.slider("Revenue Range (AUD)", min_value=0, max_value=max_rev, value=(0, max_rev), format="$%d")
            if rev_range != (0, max_rev):
                filters["revenue_range"] = rev_range
        filters["applications"] = st.multiselect("Accepts Applications", options=["Yes", "No", "Unknown"], default=[])
        if st.button("🗑️ Clear All Filters", use_container_width=True):
            st.rerun()

    # --- Apply Filters ---
    filtered_df = apply_filters(df, filters)
    if filters.get("revenue_range"):
        min_r, max_r = filters["revenue_range"]
        filtered_df = filtered_df[(filtered_df["total_revenue"] >= min_r) & (filtered_df["total_revenue"] <= max_r)]
    active_filter_count = count_active_filters(filters)

    # --- Dashboard ---
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Total Foundations</div><div class="metric-value">{len(filtered_df):,}</div><div style="font-size: 0.75rem; color: #9CA3AF;">of {len(df):,} total</div></div>', unsafe_allow_html=True)
    with col2:
        hc = len(filtered_df[filtered_df["alignment_score"] == "High"])
        mc = len(filtered_df[filtered_df["alignment_score"] == "Medium"])
        lc = len(filtered_df[filtered_df["alignment_score"] == "Low"])
        st.markdown(f'<div class="metric-card"><div class="metric-label">Alignment</div><div style="margin: 8px 0;"><span class="badge badge-high">{hc} High</span> <span class="badge badge-medium">{mc} Med</span> <span class="badge badge-low">{lc} Low</span></div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Combined Revenue</div><div class="metric-value">{format_currency(filtered_df["total_revenue"].sum())}</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Total Intl Grants</div><div class="metric-value">{format_currency(filtered_df["grants_outside_au"].sum())}</div></div>', unsafe_allow_html=True)
    with col5:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Active Filters</div><div class="metric-value">{active_filter_count}</div></div>', unsafe_allow_html=True)

    # Pipeline status breakdown
    st.markdown("<br>", unsafe_allow_html=True)
    status_cols = st.columns(len(PIPELINE_STATUSES))
    for i, status in enumerate(PIPELINE_STATUSES):
        count = len(filtered_df[filtered_df["pipeline_status"] == status])
        css_class = f"status-{status.lower().replace(' ', '-')}"
        with status_cols[i]:
            st.markdown(f'<div style="text-align: center; padding: 6px;"><span class="badge {css_class}">{count}</span><div style="font-size: 0.65rem; color: #9CA3AF; margin-top: 4px;">{status}</div></div>', unsafe_allow_html=True)

    st.markdown("---")

    # --- Export ---
    ec1, ec2, ec3 = st.columns(3)
    with ec1:
        st.download_button("📥 Export Filtered (.xlsx)", data=create_excel_export(filtered_df, True), file_name=f"od_foundations_filtered_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with ec2:
        st.download_button("📥 Export All (.xlsx)", data=create_excel_export(df, True), file_name=f"od_foundations_all_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with ec3:
        st.download_button("📥 Export CSV", data=create_csv_export(filtered_df), file_name=f"od_foundations_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # --- Sort ---
    sort_col = st.selectbox("Sort by", options=["Grants (Intl) — Highest", "Revenue — Highest", "Foundation Name — A-Z", "Alignment — High first", "Net Assets — Highest"], index=0)
    sort_map = {"Grants (Intl) — Highest": ("grants_outside_au", False), "Revenue — Highest": ("total_revenue", False), "Foundation Name — A-Z": ("name", True), "Alignment — High first": ("alignment_score", True), "Net Assets — Highest": ("net_assets", False)}
    sort_field, sort_asc = sort_map[sort_col]
    if sort_field == "alignment_score":
        order = {"High": 0, "Medium": 1, "Low": 2}
        filtered_df = filtered_df.copy()
        filtered_df["_sort"] = filtered_df["alignment_score"].map(order)
        filtered_df = filtered_df.sort_values("_sort").drop(columns=["_sort"])
    else:
        filtered_df = filtered_df.sort_values(sort_field, ascending=sort_asc)

    # --- Table ---
    display_cols = ["name", "state", "alignment_score", "dgr1_status", "total_revenue", "grants_outside_au", "grants_inside_au", "net_assets", "charity_size", "pipeline_status", "website"]
    table_df = filtered_df[display_cols].copy()
    table_df = table_df.rename(columns={k: v for k, v in COLUMN_DISPLAY_NAMES.items() if k in table_df.columns})
    table_df["Revenue"] = filtered_df["total_revenue"].apply(format_currency)
    table_df["Grants (Intl)"] = filtered_df["grants_outside_au"].apply(format_currency)
    table_df["Grants (AU)"] = filtered_df["grants_inside_au"].apply(format_currency)
    table_df["Net Assets"] = filtered_df["net_assets"].apply(format_currency)

    st.dataframe(table_df.reset_index(drop=True), use_container_width=True, height=500, column_config={"Website": st.column_config.LinkColumn("Website", display_text="🔗 Visit")})
    st.markdown(f"<p style='color: #9CA3AF; font-size: 0.8rem;'>Showing {len(filtered_df):,} of {len(df):,} foundations</p>", unsafe_allow_html=True)

    # --- Detail View ---
    st.markdown("---")
    st.markdown(f"<h2 class='section-header'>Foundation Detail View</h2>", unsafe_allow_html=True)
    foundation_names = filtered_df["name"].tolist()
    if foundation_names:
        selected_name = st.selectbox("Select a foundation to view details", options=[""] + foundation_names, format_func=lambda x: "Choose a foundation..." if x == "" else x)
        if selected_name:
            row = filtered_df[filtered_df["name"] == selected_name].iloc[0]
            st.markdown(f"<h3 style='color: {ACCENT_COLOR};'>{row['name']}</h3>", unsafe_allow_html=True)
            if row.get("also_known_as"):
                st.markdown(f"Also known as: {row['also_known_as']}")

            qs1, qs2, qs3, qs4 = st.columns(4)
            with qs1:
                badge_class = f"badge-{row['alignment_score'].lower()}"
                st.markdown(f"**Alignment:** <span class='badge {badge_class}'>{row['alignment_score']}</span>", unsafe_allow_html=True)
            with qs2:
                st.markdown(f"**DGR1:** {row['dgr1_status']}")
            with qs3:
                st.markdown(f"**Size:** {row['charity_size']}")
            with qs4:
                st.markdown(f"**Intl Funding:** {row['international_funding']}")

            tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📋 Overview", "💰 Financials", "👥 People", "🎯 Grants & Focus", "📝 Application", "🤝 Relationship"])

            with tab1:
                ca, cb = st.columns(2)
                with ca:
                    st.markdown("**Identity & Registration**")
                    st.markdown(f"- **ABN:** {row['abn']}")
                    st.markdown(f"- **Year Established:** {row.get('year_established', 'Not found')}")
                    st.markdown(f"- **Registration Date:** {row.get('registration_date', 'Not found')}")
                    st.markdown(f"- **Governance:** {row.get('governance_type', 'Not found')}")
                    st.markdown(f"- **Denomination:** {row.get('denomination', 'Not found')}")
                    if row.get('related_entities'):
                        st.markdown(f"- **Related Entities:** {row['related_entities']}")
                    if row.get('mission_summary'):
                        st.markdown(f"- **Mission:** {row['mission_summary']}")
                with cb:
                    st.markdown("**Contact Details**")
                    st.markdown(f"- **Address:** {row.get('address', '')} {row.get('suburb', '')} {row['state']} {row['postcode']}")
                    if row.get('phone'):
                        st.markdown(f"- **Phone:** {row['phone']}")
                    if row.get('email'):
                        st.markdown(f"- **Email:** {row['email']}")
                    if row.get('website'):
                        st.markdown(f"- **Website:** [{row['website']}]({row['website']})")
                    st.markdown(f"- **[ACNC Profile]({row['acnc_url']})**")
                    st.markdown(f"- **[ABR Lookup]({row['abr_url']})**")
                if row.get('alignment_notes'):
                    st.markdown(f"**Alignment Notes:** {row['alignment_notes']}")
                if row.get('christian_evidence'):
                    st.markdown(f"**Christian Evidence:** {row['christian_evidence']}")

            with tab2:
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    st.metric("Total Revenue", format_currency(row["total_revenue"]))
                    st.metric("Total Expenses", format_currency(row["total_expenses"]))
                with fc2:
                    st.metric("Grants (Intl)", format_currency(row["grants_outside_au"]))
                    st.metric("Grants (AU)", format_currency(row["grants_inside_au"]))
                with fc3:
                    st.metric("Net Assets", format_currency(row["net_assets"]))
                    st.metric("Donations/Bequests", format_currency(row.get("donations_bequests", 0)))
                st.markdown(f"**Financial Year:** {row.get('financial_year', 'Not found')}")

            with tab3:
                cp1, cp2 = st.columns(2)
                with cp1:
                    st.markdown("**Main Director / Chair**")
                    st.markdown(f"- Name: {row.get('main_director_name', 'Not found')}")
                    st.markdown(f"- Title: {row.get('main_director_title', 'Not found')}")
                    if row.get('main_director_email'):
                        st.markdown(f"- Email: {row['main_director_email']}")
                    if row.get('main_director_phone'):
                        st.markdown(f"- Phone: {row['main_director_phone']}")
                with cp2:
                    st.markdown("**Admin Contact**")
                    st.markdown(f"- Name: {row.get('admin_contact_name', 'Not found')}")
                    if row.get('admin_contact_email'):
                        st.markdown(f"- Email: {row['admin_contact_email']}")
                    if row.get('admin_contact_phone'):
                        st.markdown(f"- Phone: {row['admin_contact_phone']}")
                if row.get('all_directors'):
                    st.markdown(f"**All Directors:** {row['all_directors']}")

            with tab4:
                if row.get('giving_themes'):
                    st.markdown(f"**Giving Themes:** {row['giving_themes']}")
                if row.get('geographic_focus'):
                    st.markdown(f"**Geographic Focus:** {row['geographic_focus']}")
                if row.get('organisations_funded'):
                    st.markdown(f"**Organisations Funded:** {row['organisations_funded']}")
                if row.get('notable_recipients'):
                    st.markdown(f"**Notable Recipients:** {row['notable_recipients']}")
                if row.get('grant_size_range'):
                    st.markdown(f"**Grant Size Range:** {row['grant_size_range']}")

            with tab5:
                st.markdown(f"**Accepts Applications:** {row.get('accepts_applications', 'Unknown')}")
                if row.get('application_method'):
                    st.markdown(f"**Application Method:** {row['application_method']}")
                if row.get('funding_deadlines'):
                    st.markdown(f"**Funding Deadlines:** {row['funding_deadlines']}")
                if row.get('eligibility_requirements'):
                    st.markdown(f"**Eligibility Requirements:** {row['eligibility_requirements']}")

            with tab6:
                st.markdown("**Relationship Tracking**")
                with st.form(key=f"tracking_{row['abn']}"):
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        pipeline = st.selectbox("Pipeline Status", options=PIPELINE_STATUSES, index=PIPELINE_STATUSES.index(row.get("pipeline_status", "Not contacted")) if row.get("pipeline_status", "Not contacted") in PIPELINE_STATUSES else 0)
                        relationship = st.text_area("Existing Relationship", value=row.get("existing_relationship", ""), placeholder="e.g. Board member knows our CEO")
                        last_date = st.text_input("Last Contact Date", value=row.get("last_contact_date", ""), placeholder="DD/MM/YYYY")
                        last_method = st.selectbox("Last Contact Method", options=CONTACT_METHODS, index=CONTACT_METHODS.index(row.get("last_contact_method", "")) if row.get("last_contact_method", "") in CONTACT_METHODS else 0)
                    with cc2:
                        last_notes = st.text_area("Last Contact Notes", value=row.get("last_contact_notes", ""), placeholder="What was discussed...")
                        next_action = st.text_input("Next Action", value=row.get("next_action", ""), placeholder="e.g. Follow up after April board meeting")
                        next_date = st.text_input("Next Action Date", value=row.get("next_action_date", ""), placeholder="DD/MM/YYYY")
                        notes = st.text_area("Internal Notes", value=row.get("internal_notes", ""), placeholder="Any additional notes...")
                    submitted = st.form_submit_button("💾 Save Changes", use_container_width=True)
                    if submitted:
                        save_tracking(row["abn"], {"existing_relationship": relationship, "last_contact_date": last_date, "last_contact_method": last_method, "last_contact_notes": last_notes, "next_action": next_action, "next_action_date": next_date, "pipeline_status": pipeline, "internal_notes": notes})
                        st.success("Changes saved successfully.")
                        st.cache_data.clear()
    else:
        st.info("No foundations match your current filters. Try broadening your search.")

    st.markdown("---")
    st.markdown(f'<div style="text-align: center; color: #9CA3AF; font-size: 0.75rem; padding: 20px 0;">Open Doors Foundation Prospector &nbsp;|&nbsp; Data sourced from ACNC and ABR public records &nbsp;|&nbsp; <a href="https://www.perplexity.ai/computer" target="_blank" style="color: #9CA3AF;">Created with Perplexity Computer</a></div>', unsafe_allow_html=True)


# ============================================================
# PAGE: ABOUT THIS DATABASE
# ============================================================
elif page == "About This Database":

    st.markdown("""
    <div class="conf-banner">
        <strong>This tool is purpose-built for Open Doors Australia. Please do not share this link.</strong><br>
        All information contained in this database is sourced from publicly available records
        (ACNC, ABR, organisation websites, and public reports). No Open Doors internal data has been used.
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<h1 style='color: {ACCENT_COLOR};'>📖 About This Database</h1>", unsafe_allow_html=True)
    st.markdown("This page explains what is and isn't included in the Foundation Prospector, so anyone using the tool understands exactly what they're looking at.")

    st.markdown(f"<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color: {ACCENT_COLOR};'>Purpose</h2>", unsafe_allow_html=True)
    st.markdown("This database exists to help Open Doors Australia identify **trusts and foundations that give grants to organisations like ours**.\n\nThese are funders — they receive donations or investment income and **redistribute that money to other Christian charities and mission organisations**. Open Doors could approach them for grant funding.\n\nThis is **not** a list of every Christian charity in Australia. It is specifically filtered to organisations that could realistically be a funding source for Open Doors.")

    st.markdown(f"<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color: {ACCENT_COLOR};'>What IS Included</h2>", unsafe_allow_html=True)
    st.markdown('<div class="criteria-card"><h4>✅ Trusts, foundations, and funds that give grants to other organisations</h4><p>The database includes organisations that meet <strong>all</strong> of the following:</p><ol><li><strong>Registered Australian charity</strong> — listed on the ACNC Charity Register</li><li><strong>Trust, foundation, or fund structure</strong> — the organisation exists primarily to distribute money, not to run its own programs</li><li><strong>Christian values or affiliation</strong> — Protestant, Evangelical, Pentecostal, Anglican, Uniting, Baptist, Presbyterian, Lutheran, Adventist, Brethren, or non-denominational Christian</li><li><strong>Grant-making activity</strong> — they give grants to other Australian charities (who may then use those funds for international work)</li></ol></div>', unsafe_allow_html=True)

    st.markdown("**Types of organisations you'll find in this list:**")
    tc1, tc2 = st.columns(2)
    with tc1:
        st.markdown("- Christian charitable trusts\n- Family foundations with Christian values\n- Denominational grant-making bodies\n- Church endowment funds that distribute to charities\n- Mission funding trusts\n- Christian community foundations")
    with tc2:
        st.markdown("- Gospel/ministry grant funds\n- Christian benevolent trusts\n- Denominational mission boards (that fund other orgs)\n- Anglican, Uniting, Baptist, and other denominational foundations\n- Private Christian philanthropic trusts")

    st.markdown(f"<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color: {ACCENT_COLOR};'>What is NOT Included</h2>", unsafe_allow_html=True)

    st.markdown('<div class="exclude-card"><h4>❌ Operational charities that raise and spend their own funds</h4><p>These organisations raise their own money and send it overseas themselves — they are <strong>not funders</strong> that Open Doors would approach for grants. Examples:</p><ul><li>World Vision Australia, Compassion, Samaritan\'s Purse</li><li>Bible League International, Barnabas Fund, Pioneers</li><li>Wycliffe Bible Translators, YWAM, Operation Mobilisation</li><li>Tearfund, Bible Society</li><li>Open Doors Australia (that\'s us)</li></ul></div>', unsafe_allow_html=True)

    st.markdown('<div class="exclude-card"><h4>❌ Catholic organisations</h4><p>All Catholic charities, trusts, diocesan bodies, religious orders, and Catholic-affiliated foundations have been excluded. This includes:</p><ul><li>Catholic Mission, Caritas, CatholicCare, Centacare</li><li>Diocesan and archdiocesan trusts</li><li>Religious orders (Jesuits, Franciscans, Marists, Sisters of Mercy, etc.)</li><li>Maronite, Orthodox, and other Catholic-adjacent traditions</li></ul></div>', unsafe_allow_html=True)

    st.markdown('<div class="exclude-card"><h4>❌ Non-Christian organisations</h4><p>The ACNC "Advancing Religion" category covers all religions. The following have been filtered out:</p><ul><li>Buddhist, Hindu, Islamic, Sikh, Jewish, Baha\'i, and other non-Christian faiths</li><li>Interfaith organisations without a specifically Christian mission</li></ul></div>', unsafe_allow_html=True)

    st.markdown('<div class="exclude-card"><h4>❌ Local churches</h4><p>Individual congregations and local churches have been removed — unless they operate a significant grant-making program (over $100K in international grants or more than 80% of their expenses going to grants).</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="exclude-card"><h4>❌ Property trusts, school foundations, and service providers</h4><ul><li><strong>Property trusts</strong> — hold buildings and land for denominations, not grant-makers</li><li><strong>School foundations</strong> — fund their own school\'s operations, not external charities</li><li><strong>Aged care, hospital, and welfare providers</strong> — run their own services (Anglicare, BaptistCare, UnitingCare, etc.)</li><li><strong>Investment and lending funds</strong> — provide loans to churches, not grants to charities</li><li><strong>Building funds</strong> — raise money for construction, not for grant distribution</li></ul></div>', unsafe_allow_html=True)

    # Alignment Scoring
    st.markdown(f"<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color: {ACCENT_COLOR};'>Alignment Scoring</h2>", unsafe_allow_html=True)
    st.markdown("Each foundation is rated **High**, **Medium**, or **Low** alignment based on how likely they are to be a good fit for Open Doors funding:")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.markdown('<div style="background-color: #DCFCE7; border-radius: 10px; padding: 16px; border: 1px solid #BBF7D0;"><h4 style="color: #166534; margin-top: 0;">🟢 High</h4><ul style="color: #166534; font-size: 0.9rem;"><li>Gives $50K+ in grants to AU charities</li><li>Foundation/trust structure with significant assets</li><li>High grant-to-expense ratio</li><li>Clear Christian mission alignment</li></ul></div>', unsafe_allow_html=True)
    with sc2:
        st.markdown('<div style="background-color: #FFF7ED; border-radius: 10px; padding: 16px; border: 1px solid #FED7AA;"><h4 style="color: #9A3412; margin-top: 0;">🟡 Medium</h4><ul style="color: #9A3412; font-size: 0.9rem;"><li>Gives $10K+ in grants</li><li>Foundation structure with moderate assets</li><li>Some grant activity but less proven</li><li>Christian affiliation confirmed</li></ul></div>', unsafe_allow_html=True)
    with sc3:
        st.markdown('<div style="background-color: #F3F4F6; border-radius: 10px; padding: 16px; border: 1px solid #D1D5DB;"><h4 style="color: #4B5563; margin-top: 0;">⚪ Low</h4><ul style="color: #4B5563; font-size: 0.9rem;"><li>Small or unclear grant activity</li><li>Foundation structure but limited data</li><li>May need further research to confirm fit</li><li>Worth keeping on the radar</li></ul></div>', unsafe_allow_html=True)

    # Data Sources
    st.markdown(f"<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color: {ACCENT_COLOR};'>Data Sources</h2>", unsafe_allow_html=True)
    st.markdown('<div class="note-card"><p>All data is sourced from <strong>publicly available records</strong>. No Open Doors internal data has been used.</p><table style="width: 100%; border-collapse: collapse; font-size: 0.9rem;"><tr style="border-bottom: 1px solid #E5E7EB;"><td style="padding: 8px; font-weight: 600;">ACNC Charity Register</td><td style="padding: 8px;">Names, ABNs, addresses, charity subtypes, beneficiary categories</td><td style="padding: 8px; color: #6B7280;">data.gov.au</td></tr><tr style="border-bottom: 1px solid #E5E7EB;"><td style="padding: 8px; font-weight: 600;">ACNC 2023 Annual Information Statements</td><td style="padding: 8px;">Revenue, expenses, grants, net assets, international activities</td><td style="padding: 8px; color: #6B7280;">data.gov.au</td></tr><tr style="border-bottom: 1px solid #E5E7EB;"><td style="padding: 8px; font-weight: 600;">ABN Lookup</td><td style="padding: 8px;">DGR1 (Deductible Gift Recipient) status</td><td style="padding: 8px; color: #6B7280;">abr.business.gov.au</td></tr><tr><td style="padding: 8px; font-weight: 600;">Organisation websites</td><td style="padding: 8px;">Directors, contact details, mission statements, grant guidelines</td><td style="padding: 8px; color: #6B7280;">Individual research</td></tr></table></div>', unsafe_allow_html=True)

    # How to Use
    st.markdown(f"<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color: {ACCENT_COLOR};'>How to Use This Tool</h2>", unsafe_allow_html=True)
    st.markdown("1. **Start with High alignment foundations** — these are the most likely grant-making fits for Open Doors\n2. **Use the filters** in the sidebar to narrow by state, grant size, or other criteria\n3. **Click on a foundation** in the detail view to see full information including financials, directors, and documents\n4. **Track your outreach** using the Relationship tab — update pipeline status, contact notes, and next actions\n5. **Export to Excel** at any time for sharing with colleagues or offline review")

    # Limitations
    st.markdown(f"<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color: {ACCENT_COLOR};'>Limitations & Notes</h2>", unsafe_allow_html=True)
    st.markdown('<div class="note-card"><ul><li><strong>Not every foundation will be relevant</strong> — some may only fund specific causes that don\'t align with Open Doors\' mission.</li><li><strong>Financial data is from 2023</strong> — the most recent AIS data available.</li><li><strong>DGR1 status still being verified</strong> — requires checking each foundation individually on the ABR.</li><li><strong>Contact details are a work in progress</strong> — director names, emails, and phone numbers require individual research.</li><li><strong>Some foundations may be missing</strong> — some private trusts may not be registered with the ACNC.</li></ul></div>', unsafe_allow_html=True)

    st.markdown(f"<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown(f'<div style="text-align: center; color: #9CA3AF; font-size: 0.85rem; padding: 20px 0;">Database last refreshed: <strong>27 March 2026</strong><br>Built from ACNC Register (65,228 charities) and 2023 AIS data (53,285 records)<br><br><a href="https://www.perplexity.ai/computer" target="_blank" style="color: #9CA3AF;">Created with Perplexity Computer</a></div>', unsafe_allow_html=True)
