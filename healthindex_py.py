import streamlit as st
import pandas as pd
import plotly.express as px
import io
 
st.set_page_config(page_title="Transformer Health", layout="wide")
st.title("⚡ Transformer Health Index")
 
# ---------------------------
# Upload principal (existing)
# ---------------------------
uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])
 
if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
 
    # ---------------------------
    # Transformar estructura
    # ---------------------------
    df_melt = df.melt(id_vars=["Transformador"],
                      var_name="Month",
                      value_name="Value")
 
    df_melt[["Indicator", "Type"]] = df_melt["Transformador"].str.extract(r"(.*)\((.*)\)")
 
    df_pivot = df_melt.pivot_table(
        index=["Month", "Indicator"],
        columns="Type",
        values="Value"
    ).reset_index()
 
    # ---------------------------
    # Calcular Health Index
    # ---------------------------
    df_pivot["Weighted Score"] = df_pivot["Score"] * df_pivot["Weight"]
    hi_monthly = df_pivot.groupby("Month")["Weighted Score"].sum().reset_index()
    hi_monthly.rename(columns={"Weighted Score": "Health Index"}, inplace=True)
 
    # ---------------------------
    # TABS  ← new structure
    # ---------------------------
    tab1, tab2 = st.tabs(["📊 Health Index Dashboard", "⚡ Events & HI Recalculation"])
 
    # ════════════════════════════════════════════════════════
    # TAB 1 — original content (unchanged)
    # ════════════════════════════════════════════════════════
    with tab1:
        st.subheader("📂 Raw Data")
        st.dataframe(df)
 
        st.subheader("🔄 Data Transformada")
        st.dataframe(df_pivot)
 
        st.subheader("📊 Health Index Mensual")
        st.dataframe(hi_monthly)
 
        fig = px.line(
            hi_monthly,
            x="Month",
            y="Health Index",
            markers=True,
            title="Health Index Trend"
        )
        st.plotly_chart(fig, use_container_width=True)
 
        st.subheader("🔍 Indicadores")
        indicadores = df_pivot["Indicator"].unique()
        selected = st.selectbox("Selecciona indicador", indicadores)
        df_ind = df_pivot[df_pivot["Indicator"] == selected]
        fig2 = px.line(
            df_ind,
            x="Month",
            y="Score",
            markers=True,
            title=f"{selected} Score"
        )
        st.plotly_chart(fig2, use_container_width=True)
 
        col1, col2, col3 = st.columns(3)
        col1.metric("HI Promedio", f"{hi_monthly['Health Index'].mean():.2f}")
        col2.metric("HI Mínimo",   f"{hi_monthly['Health Index'].min():.2f}")
        col3.metric("HI Máximo",   f"{hi_monthly['Health Index'].max():.2f}")
 
    # ════════════════════════════════════════════════════════
    # TAB 2 — Events & HI Recalculation (new)
    # ════════════════════════════════════════════════════════
    with tab2:
        st.markdown("## 📂 Upload Events & Recalculate Health Index")
        st.markdown(
            "Upload an Events `.xlsx` file. For each asset the app takes the worst event "
            "(max deduction) and computes:  \n"
            "**`NewHealthIndex = HealthIndex − (Condition × Weight)`**"
        )
 
        # Build asset_df from the already-loaded main file
        # We need: Activo, Componente, HealthIndex, Weight, Asset_Condition(Actual)
        # ── derive it from df_pivot + hi_monthly ──────────────────────────────
        # Use last month's HI as the baseline HealthIndex
        last_month = hi_monthly["Month"].iloc[-1]
        baseline_hi = hi_monthly[hi_monthly["Month"] == last_month]["Health Index"].values[0]
 
        # Asset_Condition(Actual) column: look for an indicator whose name contains
        # "Asset_Condition" and Type == "Actual"
        asset_cond_row = df_pivot[
            df_pivot["Indicator"].str.contains("Asset_Condition", case=False, na=False) &
            (df_pivot["Month"] == last_month)
        ]
 
        if asset_cond_row.empty:
            st.warning(
                "Could not find an **Asset_Condition(Actual)** indicator in your main file. "
                "Make sure it exists as a row named like `Asset_Condition(Actual)` in your Excel."
            )
            asset_condition_actual = None
        else:
            asset_condition_actual = asset_cond_row["Actual"].values[0]
 
        # Build a simple asset_df with one row per indicator (Componente = Indicator)
        asset_df = df_pivot[df_pivot["Month"] == last_month][["Indicator", "Actual", "Weight"]].copy()
        asset_df = asset_df.rename(columns={
            "Indicator": "Componente",
            "Actual":    "Asset_Condition(Actual)",
        })
        asset_df["Activo"]      = "Transformador"
        asset_df["HealthIndex"] = baseline_hi
 
        # ── events file uploader ──────────────────────────────────────────────
        events_file = st.file_uploader(
            "Drop your Events file here",
            type=["xlsx"],
            key="events_uploader",
            help="Expected columns: Fecha, Activo, Componente, Modo de Falla, Severidad, Condition, DiasFalla, FechaFalla",
        )
 
        if events_file is None:
            st.info("Waiting for an Events file…")
        else:
            # ── read & validate ───────────────────────────────────────────────
            try:
                events_raw = pd.read_excel(events_file)
            except Exception as e:
                st.error(f"Could not read file: {e}")
                st.stop()
 
            required_cols = {"Activo", "Componente", "Condition"}
            missing = required_cols - set(events_raw.columns)
            if missing:
                st.error(f"Events file is missing columns: **{', '.join(missing)}**")
                st.stop()
 
            with st.expander("📋 Uploaded Events", expanded=True):
                st.dataframe(events_raw, use_container_width=True)
 
            st.markdown("---")
 
            # ── join Weight from asset_df into events ─────────────────────────
            weight_lookup = asset_df[["Activo", "Componente", "Weight"]].drop_duplicates()
            events_enriched = events_raw.merge(weight_lookup, on=["Activo", "Componente"], how="left")
 
            unmatched = events_enriched["Weight"].isna().sum()
            if unmatched > 0:
                st.warning(
                    f"⚠️ {unmatched} event(s) could not be matched to an asset row "
                    "(no matching Activo + Componente). They will be ignored."
                )
                events_enriched = events_enriched.dropna(subset=["Weight"])
 
            if events_enriched.empty:
                st.error("No events matched your asset data. Check that Activo and Componente values align.")
                st.stop()
 
            # ── compute deductions ────────────────────────────────────────────
            events_enriched["Deduction"] = events_enriched["Condition"] * events_enriched["Weight"]
 
            worst = (
                events_enriched
                .groupby(["Activo", "Componente"], as_index=False)["Deduction"]
                .max()
                .rename(columns={"Deduction": "MaxDeduction"})
            )
 
            result_df = asset_df.merge(worst, on=["Activo", "Componente"], how="left")
            result_df["MaxDeduction"]   = result_df["MaxDeduction"].fillna(0)
            result_df["NewHealthIndex"] = (result_df["HealthIndex"] - result_df["MaxDeduction"]).clip(0, 100)
            result_df["Delta"]          = result_df["NewHealthIndex"] - result_df["HealthIndex"]
 
            # ── KPI row ───────────────────────────────────────────────────────
            affected  = (result_df["Delta"] < 0).sum()
            worst_row = result_df.loc[result_df["Delta"].idxmin()]
            avg_drop  = result_df.loc[result_df["Delta"] < 0, "Delta"].mean()
 
            k1, k2, k3 = st.columns(3)
            k1.metric("Components Affected", affected)
            k2.metric("Avg HI Drop", f"{avg_drop:.2f}" if affected else "—")
            k3.metric(
                "Worst Component",
                worst_row["Componente"] if affected else "—",
                delta=f"{worst_row['Delta']:.2f}" if affected else None,
                delta_color="inverse",
            )
 
            st.markdown("---")
 
            # ── results table ─────────────────────────────────────────────────
            st.subheader("📊 Adjusted Health Index per Component")
 
            display_cols = ["Activo", "Componente", "Asset_Condition(Actual)",
                            "Weight", "HealthIndex", "MaxDeduction", "NewHealthIndex", "Delta"]
            display = result_df[display_cols].copy()
 
            def color_delta(val):
                return "color: #e74c3c; font-weight:600" if val < 0 else "color: #27ae60; font-weight:600"
 
            styled = (
                display.style
                .format({
                    "Asset_Condition(Actual)": "{:.3f}",
                    "Weight":                  "{:.3f}",
                    "HealthIndex":             "{:.2f}",
                    "MaxDeduction":            "{:.4f}",
                    "NewHealthIndex":          "{:.2f}",
                    "Delta":                   "{:.2f}",
                })
                .applymap(color_delta, subset=["Delta"])
                .background_gradient(subset=["NewHealthIndex"], cmap="RdYlGn", vmin=0, vmax=100)
            )
            st.dataframe(styled, use_container_width=True)
 
            # ── before / after HI chart ───────────────────────────────────────
            st.subheader("📉 Before vs After Health Index")
            chart_df = pd.DataFrame({
                "Componente":      result_df["Componente"],
                "Before":          result_df["HealthIndex"],
                "After":           result_df["NewHealthIndex"],
            }).melt(id_vars="Componente", var_name="State", value_name="Health Index")
 
            fig3 = px.bar(
                chart_df,
                x="Componente",
                y="Health Index",
                color="State",
                barmode="group",
                color_discrete_map={"Before": "#3498db", "After": "#e74c3c"},
                title="Health Index — Before vs After Events",
            )
            st.plotly_chart(fig3, use_container_width=True)
 
            # ── download ──────────────────────────────────────────────────────
            st.markdown("---")
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                result_df[display_cols].to_excel(writer, index=False, sheet_name="Adjusted_HI")
                events_raw.to_excel(writer, index=False, sheet_name="Events")
            buffer.seek(0)
 
            st.download_button(
                label="📥 Download Adjusted Health Index (.xlsx)",
                data=buffer,
                file_name="adjusted_health_index.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
 
else:
    st.info("Sube el archivo Excel del transformador")
