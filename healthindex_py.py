import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(page_title="Asset Health Index", layout="wide")
st.title("⚡ Asset Health Index")

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
MAX_ASSETS = 5


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def hi_color(value):
    if value >= 85:
        return "background-color: #006400; color: white;"
    elif value >= 70:
        return "background-color: #7CFC00; color: black;"
    elif value >= 50:
        return "background-color: #FFD700; color: black;"
    elif value >= 30:
        return "background-color: #FFA500; color: black;"
    else:
        return "background-color: #FF4C4C; color: white;"


def color_by_hi(v):
    if v >= 85:
        return "darkgreen"
    elif v >= 70:
        return "lightgreen"
    elif v >= 50:
        return "yellow"
    elif v >= 30:
        return "orange"
    else:
        return "red"


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

    df_pivot["Weighted Score"] = df_pivot["Score"] * df_pivot["Weight"]

    hi_monthly = df_pivot.groupby("Month")["Weighted Score"].sum().reset_index()
    hi_monthly.rename(columns={"Weighted Score": "Health Index"}, inplace=True)
    hi_monthly["Asset"] = asset_name

    hi_monthly["Health Index %"] = hi_monthly["Health Index"] * 100

    last_month = hi_monthly["Month"].iloc[-1]
    baseline_hi = hi_monthly[hi_monthly["Month"] == last_month]["Health Index"].values[0]

    asset_cond_row = df_pivot[
        df_pivot["Indicator"].str.contains("Asset_Condition", case=False, na=False) &
        (df_pivot["Month"] == last_month)
    ]

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

    return {
        "Asset": asset_name,
        "Asset_Condition(Actual)": asset_condition_actual,
        "Asset_Condition(Weight)": asset_condition_weight,
        "HI Before %": round(baseline_hi * 100, 1),
        "Max Deduction %": round(max_deduction * 100, 1),
        "HI After %": round(new_hi * 100, 1),
        "Delta %": round((new_hi - baseline_hi) * 100, 1),
        "Worst Component": worst.get("Componente", "—"),
        "Worst Condition": worst["Condition"],
    }, asset_events


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("📁 Upload Files")

    asset_files = st.file_uploader(
        "Asset files (.xlsx)",
        type=["xlsx"],
        accept_multiple_files=True
    )

    if asset_files and len(asset_files) > MAX_ASSETS:
        asset_files = asset_files[:MAX_ASSETS]

    events_file = st.file_uploader(
        "Events file (.xlsx)",
        type=["xlsx"]
    )

    criticality_map = {}
    if asset_files:
        st.markdown("**Asset Criticality**")
        for f in asset_files:
            name = f.name.replace(".xlsx", "")
            criticality_map[name] = st.select_slider(name, [1, 2, 3], value=1)


# ─────────────────────────────────────────────
# LOAD ASSETS (WITH SAFETY FIX)
# ─────────────────────────────────────────────
assets = {}

if asset_files:
    for f in asset_files:
        try:
            name = f.name.replace(".xlsx", "")
            df_pivot, hi_monthly, baseline_hi, ac_w, ac_a = parse_asset_file(f, name)

            assets[name] = {
                "df_pivot": df_pivot,
                "hi_monthly": hi_monthly,
                "baseline_hi": baseline_hi,
                "ac_weight": ac_w,
                "ac_actual": ac_a,
                "criticality": criticality_map.get(name, 1),
            }

        except Exception as e:
            st.error(f"❌ Error loading {f.name}: {e}")


# ─────────────────────────────────────────────
# SAFETY CHECK (FIX ERROR)
# ─────────────────────────────────────────────
if not assets:
    st.warning("No valid assets were loaded. Please check your Excel files.")
    st.stop()


# ─────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────
events_raw = pd.read_excel(events_file) if events_file else None


# ─────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["Overview", "Asset Detail", "Events"])


# ═════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ═════════════════════════════════════════════
with tab1:

    st.subheader("Health Index Trend")

    all_hi = pd.concat(
        [a["hi_monthly"] for a in assets.values()],
        ignore_index=True
    )

    all_hi["Color"] = all_hi["Health Index %"].apply(color_by_hi)

    fig = px.scatter(
        all_hi,
        x="Month",
        y="Health Index %",
        color="Color",
        symbol="Asset"
    )

    fig.update_traces(mode="lines+markers")
    fig.update_yaxes(range=[0, 100], ticksuffix="%")

    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Last Month Summary")

    overview = pd.DataFrame([
        {
            "Asset": name,
            "HI (Last Month) %": a["baseline_hi"] * 100
        }
        for name, a in assets.items()
    ])

    st.dataframe(
        overview.style.map(
            lambda v: hi_color(v) if isinstance(v, (int, float)) else "",
            subset=["HI (Last Month) %"]
        ),
        use_container_width=True
    )


# ═════════════════════════════════════════════
# TAB 2 — ASSET DETAIL
# ═════════════════════════════════════════════
with tab2:

    asset = st.selectbox("Select asset", list(assets.keys()))
    a = assets[asset]

    fig = px.line(a["hi_monthly"], x="Month", y="Health Index %", markers=True)
    fig.update_yaxes(range=[0, 100], ticksuffix="%")

    st.plotly_chart(fig, use_container_width=True)


# ═════════════════════════════════════════════
# TAB 3 — EVENTS
# ═════════════════════════════════════════════
with tab3:

    st.subheader("Events Data")

    if events_raw is not None:
        st.dataframe(events_raw, use_container_width=True)
    else:
        st.info("Upload events file to view data.")
