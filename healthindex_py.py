import streamlit as st
import pandas as pd
import plotly.express as px
import io
 
st.set_page_config(page_title="Asset Health Index", layout="wide")
st.title("⚡ Asset Health Index")
 
# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
MAX_ASSETS = 5   # ← change this to allow more or fewer asset files
 
 
# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
 
def fmt_pct(val):
    """Format a 0–1 decimal as a percentage string with 1 decimal."""
    return f"{val * 100:.1f}%"
 
 
def color_hi(val):
    """Background color for a Health Index % value (0–100 scale)."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return ""
    if v >= 85:
        return "background-color: #27ae60; color: white; font-weight:600"   # Green
    elif v >= 70:
        return "background-color: #82e0aa; color: black; font-weight:600"   # Light green
    elif v >= 50:
        return "background-color: #f4d03f; color: black; font-weight:600"   # Yellow
    elif v >= 30:
        return "background-color: #e67e22; color: white; font-weight:600"   # Orange
    else:
        return "background-color: #e74c3c; color: white; font-weight:600"   # Red
 
 
def parse_asset_file(file, asset_name):
    df = pd.read_excel(file)
    id_col = df.columns[0]
    df_melt = df.melt(id_vars=[id_col], var_name="Month", value_name="Value")
    df_melt[["Indicator", "Type"]] = df_melt[id_col].str.extract(r"(.*)\((.*)\)")
    df_melt = df_melt.dropna(subset=["Indicator", "Type"])
 
    df_pivot = df_melt.pivot_table(
        index=["Month", "Indicator"],
        columns="Type",
        values="Value"
    ).reset_index()
 
    for col in ["Score", "Weight"]:
        if col not in df_pivot.columns:
            raise ValueError(f"Column '{col}' not found after pivoting '{asset_name}'. "
                             "Make sure the file has rows with (Score) and (Weight).")
 
    df_pivot["Weighted Score"] = df_pivot["Score"] * df_pivot["Weight"]
    hi_monthly = df_pivot.groupby("Month")["Weighted Score"].sum().reset_index()
    hi_monthly.rename(columns={"Weighted Score": "Health Index"}, inplace=True)
    hi_monthly["Asset"] = asset_name
 
    # Convert to percentage
    hi_monthly["Health Index %"] = hi_monthly["Health Index"] * 100
    df_pivot["Score %"] = df_pivot["Score"] * 100
 
    last_month = hi_monthly["Month"].iloc[-1]
    baseline_hi = hi_monthly[hi_monthly["Month"] == last_month]["Health Index"].values[0]
 
    asset_cond_row = df_pivot[
        df_pivot["Indicator"].str.contains("Asset_Condition", case=False, na=False) &
        (df_pivot["Month"] == last_month)
    ]
    if asset_cond_row.empty:
        raise ValueError(f"No 'Asset_Condition' indicator found in '{asset_name}'.")
 
    asset_condition_weight = asset_cond_row["Weight"].values[0]
    asset_condition_actual = asset_cond_row["Actual"].values[0]
 
    return df_pivot, hi_monthly, baseline_hi, asset_condition_weight, asset_condition_actual
 
 
def compute_adjusted_hi(asset_name, baseline_hi, asset_condition_weight,
                         asset_condition_actual, events_df):
    asset_events = events_df[
        events_df["Activo"].str.strip().str.lower() == asset_name.lower()
    ].copy()
 
    if asset_events.empty:
        return None, asset_events
 
    asset_events["Deduction"] = asset_events["Condition"] * asset_condition_weight
    max_deduction = asset_events["Deduction"].max()
    new_hi = max(0.0, baseline_hi - max_deduction)
    worst = asset_events.loc[asset_events["Deduction"].idxmax()]
 
    # Safely extract optional columns from the worst event
    failure_mode       = worst.get("Modo de Falla", "—")
    days_to_failure    = worst.get("DiasFalla", "—")
    expected_fail_date = worst.get("FechaFalla", "—")
 
    summary = {
        "Asset":                     asset_name,
        "Asset_Condition(Actual)":   asset_condition_actual,
        "Asset_Condition(Weight)":   asset_condition_weight,
        "HI Before %":               round(baseline_hi * 100, 1),
        "Max Deduction %":           round(max_deduction * 100, 1),
        "HI After %":                round(new_hi * 100, 1),
        "Delta %":                   round((new_hi - baseline_hi) * 100, 1),
        "Worst Component":           worst.get("Componente", "—"),
        "Failure Mode":              failure_mode,
        "Days to Failure":           days_to_failure,
        "Expected Failure Date":     expected_fail_date,
        "Worst Condition":           worst["Condition"],
    }
    return summary, asset_events
 
 
# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📁 Upload Files")
    st.markdown(f"Upload up to **{MAX_ASSETS}** asset files. "
                "The filename (without .xlsx) will be used as the asset name.")
 
    asset_files = st.file_uploader(
        "Asset files (.xlsx)",
        type=["xlsx"],
        accept_multiple_files=True,
        key="asset_files",
    )
 
    if asset_files and len(asset_files) > MAX_ASSETS:
        st.warning(f"Only the first {MAX_ASSETS} files will be used.")
        asset_files = asset_files[:MAX_ASSETS]
 
    st.markdown("---")
    events_file = st.file_uploader(
        "Events file (.xlsx)",
        type=["xlsx"],
        key="events_file",
        help="Must have columns: Activo, Condition.",
    )
 
    # Criticality per asset (only shown once files are uploaded)
    criticality_map = {}
    if asset_files:
        st.markdown("---")
        st.markdown("**🔺 Asset Criticality**")
        st.caption("1 = Low · 2 = Medium · 3 = High")
        for f in asset_files[:MAX_ASSETS]:
            aname = f.name.replace(".xlsx", "").replace(".XLSX", "")
            criticality_map[aname] = st.select_slider(
                aname,
                options=[1, 2, 3],
                value=1,
                key=f"crit_{aname}",
            )
 
# ─────────────────────────────────────────────────────────────────────────────
# GUARD
# ─────────────────────────────────────────────────────────────────────────────
if not asset_files:
    st.info("👈 Upload at least one asset file in the sidebar to get started.")
    st.stop()
 
# ─────────────────────────────────────────────────────────────────────────────
# PARSE ALL ASSET FILES
# ─────────────────────────────────────────────────────────────────────────────
assets = {}
 
for f in asset_files:
    asset_name = f.name.replace(".xlsx", "").replace(".XLSX", "")
    try:
        df_pivot, hi_monthly, baseline_hi, ac_weight, ac_actual = parse_asset_file(f, asset_name)
        assets[asset_name] = {
            "df_pivot":    df_pivot,
            "hi_monthly":  hi_monthly,
            "baseline_hi": baseline_hi,
            "ac_weight":   ac_weight,
            "ac_actual":   ac_actual,
            "criticality": criticality_map.get(asset_name, 1),
        }
    except ValueError as e:
        st.error(f"**{asset_name}:** {e}")
 
if not assets:
    st.stop()
 
# ─────────────────────────────────────────────────────────────────────────────
# PARSE EVENTS FILE
# ─────────────────────────────────────────────────────────────────────────────
events_raw = None
if events_file:
    try:
        events_raw = pd.read_excel(events_file)
        for col in events_raw.select_dtypes(include=["datetime64"]).columns:
            events_raw[col] = events_raw[col].dt.date
        missing_ev = {"Activo", "Condition"} - set(events_raw.columns)
        if missing_ev:
            st.error(f"Events file is missing columns: **{', '.join(missing_ev)}**")
            events_raw = None
    except Exception as e:
        st.error(f"Could not read Events file: {e}")
 
# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "📊 Health Index Dashboard",
    "🔍 Asset Detail",
    "⚡ Events & HI Recalculation",
])
 
# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — Overview
# ═════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("📊 Health Index — All Assets")
 
    all_hi = pd.concat([a["hi_monthly"] for a in assets.values()], ignore_index=True)
 
    fig = px.line(all_hi, x="Month", y="Health Index %", color="Asset",
                  markers=True, title="Health Index Trend — All Assets",
                  labels={"Health Index %": "Health Index (%)"})
    fig.update_yaxes(ticksuffix="%", range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)
 
    st.markdown("### Last Month Summary")
    cols = st.columns(len(assets))
    crit_labels = {1: "🟢 Low", 2: "🟡 Medium", 3: "🔴 High"}
    for col, (name, a) in zip(cols, assets.items()):
        col.metric(name, f"{a['baseline_hi'] * 100:.1f}%",
                   help=f"Criticality: {crit_labels[a['criticality']]}")
 
    # Asset overview table with criticality
    overview = pd.DataFrame([{
        "Asset":        name,
        "Criticality":  crit_labels[a["criticality"]],
        "HI (Last Month) %": round(a["baseline_hi"] * 100, 1),
    } for name, a in assets.items()])
    st.dataframe(
        overview.style
        .format({"HI (Last Month) %": "{:.1f}%"})
        .map(color_hi, subset=["HI (Last Month) %"]),
        use_container_width=True,
        hide_index=True,
    )
 
    st.markdown("### Monthly Health Index Table")
    hi_table = all_hi.pivot_table(index="Month", columns="Asset", values="Health Index %")
    st.dataframe(
        hi_table.style
        .format("{:.1f}%")
        .map(color_hi),
        use_container_width=True,
    )
 
# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — Asset Detail
# ═════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("🔍 Asset Detail")
 
    selected_asset = st.selectbox("Select asset", list(assets.keys()))
    a = assets[selected_asset]
 
    fig_hi = px.line(a["hi_monthly"], x="Month", y="Health Index %", markers=True,
                     title=f"{selected_asset} — Health Index",
                     labels={"Health Index %": "Health Index (%)"})
    fig_hi.update_yaxes(ticksuffix="%", range=[0, 100])
    st.plotly_chart(fig_hi, use_container_width=True)
 
    col1, col2, col3 = st.columns(3)
    col1.metric("HI Promedio", f"{a['hi_monthly']['Health Index %'].mean():.1f}%")
    col2.metric("HI Mínimo",   f"{a['hi_monthly']['Health Index %'].min():.1f}%")
    col3.metric("HI Máximo",   f"{a['hi_monthly']['Health Index %'].max():.1f}%")
 
    st.markdown("#### Indicator Scores")
    indicadores = a["df_pivot"]["Indicator"].unique()
    selected_ind = st.selectbox("Select indicator", indicadores, key="ind_select")
    df_ind = a["df_pivot"][a["df_pivot"]["Indicator"] == selected_ind]
    fig_ind = px.line(df_ind, x="Month", y="Score %", markers=True,
                      title=f"{selected_asset} — {selected_ind} Score",
                      labels={"Score %": "Score (%)"})
    fig_ind.update_yaxes(ticksuffix="%", range=[0, 100])
    st.plotly_chart(fig_ind, use_container_width=True)
 
    with st.expander("📂 Raw Pivot Data"):
        st.dataframe(a["df_pivot"], use_container_width=True)
 
# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — Events & HI Recalculation
# ═════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("## ⚡ Events & HI Recalculation")
    st.markdown(
        "Upload an Events file in the sidebar. For each asset the app takes the "
        "worst event (max deduction) and computes:  \n"
        "**`NewHealthIndex = HealthIndex − (Condition × Asset_Condition_Weight)`**"
    )
 
    if events_raw is None:
        st.info("👈 Upload an Events file in the sidebar to recalculate.")
        st.stop()
 
    with st.expander("📋 Uploaded Events", expanded=False):
        st.dataframe(events_raw, use_container_width=True)
 
    st.markdown("---")
 
    summaries  = []
    all_events = []
 
    crit_labels = {1: "🟢 Low", 2: "🟡 Medium", 3: "🔴 High"}
    for name, a in assets.items():
        summary, asset_events = compute_adjusted_hi(
            name, a["baseline_hi"], a["ac_weight"], a["ac_actual"], events_raw
        )
        if summary:
            summary["Criticality"] = crit_labels[a["criticality"]]
            summaries.append(summary)
            all_events.append(asset_events)
 
    unmatched = [n for n in assets if n not in {s["Asset"] for s in summaries}]
    if unmatched:
        st.warning(f"No events found for: **{', '.join(unmatched)}**. "
                   "Check that 'Activo' values in the Events file match the filenames exactly.")
 
    if not summaries:
        st.error("No events could be matched to any asset.")
        st.stop()
 
    summary_df = pd.DataFrame(summaries)
 
    # ── Format Expected Failure Date if it's a numeric Excel serial ──
    def maybe_excel_date(val):
        try:
            if isinstance(val, (int, float)):
                return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(val))
            return val
        except Exception:
            return val
 
    if "Expected Failure Date" in summary_df.columns:
        summary_df["Expected Failure Date"] = summary_df["Expected Failure Date"].apply(maybe_excel_date)
 
    # KPI cards
    st.subheader("📊 Adjusted Health Index — All Assets")
    cols = st.columns(len(summaries))
    for col, row in zip(cols, summaries):
        col.metric(row["Asset"],
                   f"{row['HI After %']:.1f}%",
                   delta=f"{row['Delta %']:.1f}%",
                   delta_color="inverse")
 
    st.markdown("---")
 
    # Summary table — requested columns only
    def color_delta(val):
        return "color: #e74c3c; font-weight:600" if val < 0 else "color: #27ae60; font-weight:600"
 
    col_order = [
        "Asset",
        "Criticality",
        "HI Before %",
        "HI After %",
        "Delta %",
        "Worst Component",
        "Failure Mode",
        "Days to Failure",
        "Expected Failure Date",
    ]
    col_order = [c for c in col_order if c in summary_df.columns]
 
    fmt = {
        "HI Before %":  "{:.1f}%",
        "HI After %":   "{:.1f}%",
        "Delta %":      "{:.1f}%",
    }
 
    st.dataframe(
        summary_df[col_order].style
        .format(fmt)
        .map(color_delta, subset=["Delta %"])
        .map(color_hi, subset=["HI Before %", "HI After %"]),
        use_container_width=True,
        hide_index=True,
    )
 
    # Before / after chart
    st.subheader("📉 Before vs After — All Assets")
    chart_df = summary_df[["Asset", "HI Before %", "HI After %"]].melt(
        id_vars="Asset", var_name="State", value_name="Health Index %"
    )
    fig_ba = px.bar(
        chart_df, x="Asset", y="Health Index %", color="State", barmode="group",
        text="Health Index %",
        color_discrete_map={"HI Before %": "#3498db", "HI After %": "#e74c3c"},
        title="Health Index — Before vs After Events",
        labels={"Health Index %": "Health Index (%)"},
    )
    fig_ba.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig_ba.update_yaxes(ticksuffix="%", range=[0, 100])
    st.plotly_chart(fig_ba, use_container_width=True)
 
    # Per-asset event detail
    st.subheader("🔍 Event Detail per Asset")
    selected_ev_asset = st.selectbox("Select asset", [s["Asset"] for s in summaries], key="ev_asset")
    sel_summary = next(s for s in summaries if s["Asset"] == selected_ev_asset)
    sel_events  = next(e for e in all_events
                       if e["Activo"].iloc[0].strip().lower() == selected_ev_asset.lower())
 
    k1, k2, k3 = st.columns(3)
    k1.metric("HI Before",     f"{sel_summary['HI Before %']:.1f}%")
    k2.metric("Max Deduction", f"{sel_summary['Max Deduction %']:.1f}%")
    k3.metric("HI After",      f"{sel_summary['HI After %']:.1f}%",
              delta=f"{sel_summary['Delta %']:.1f}%", delta_color="inverse")
 
    def color_ded(val):
        return "color: #e74c3c; font-weight:600"
 
    ev_display = sel_events.copy()
    ev_display["Deduction %"] = (ev_display["Deduction"] * 100).round(1)
    ev_display = ev_display.drop(columns=["Condition", "Deduction"], errors="ignore")
    st.dataframe(
        ev_display.style
        .map(color_ded, subset=["Deduction %"])
        .format({"Deduction %": "{:.1f}%"}),
        use_container_width=True,
    )
 
    # Download
    st.markdown("---")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="Adjusted_HI")
        pd.concat(all_events, ignore_index=True).to_excel(writer, index=False, sheet_name="Events")
    buffer.seek(0)
 
    st.download_button(
        label="📥 Download Results (.xlsx)",
        data=buffer,
        file_name="adjusted_health_index.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
