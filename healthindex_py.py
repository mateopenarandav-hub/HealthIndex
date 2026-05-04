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
                "Could not find an **Asset_Condition** indicator in your main file."
            )
            st.stop()
 
        # Asset_Condition weight and current actual value (from last month)
        asset_condition_weight  = asset_cond_row["Weight"].values[0]
        asset_condition_actual  = asset_cond_row["Actual"].values[0]
 
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
 
            required_cols = {"Activo", "Condition"}
            missing = required_cols - set(events_raw.columns)
            if missing:
                st.error(f"Events file is missing columns: **{', '.join(missing)}**")
                st.stop()
 
            # Only keep events for this transformer
            events_matched = events_raw[
                events_raw["Activo"].str.strip().str.lower() == "transformador"
            ].copy()
 
            if events_matched.empty:
                st.error("No events found for **Transformador** in the uploaded file.")
                st.stop()
 
            with st.expander("📋 Uploaded Events", expanded=True):
                st.dataframe(events_raw, use_container_width=True)
 
            st.markdown("---")
 
            # ── compute deductions ────────────────────────────────────────────
            # Each event deduction = Condition × Asset_Condition Weight
            events_matched["Deduction"] = events_matched["Condition"] * asset_condition_weight
 
            worst = (
                events_enriched
                .groupby(["Activo", "Componente"], as_index=False)["Deduction"]
                .max()
                .rename(columns={"Deduction": "MaxDeduction"})
            )
 
            result_df = asset_df.merge(worst, on=["Activo", "Componente"], how="left")
            result_df["MaxDeduction"]   = result_df["MaxDeduction"].fillna(0)
            # Worst event = max deduction across all components
            max_deduction   = events_matched["Deduction"].max()
            worst_event     = events_matched.loc[events_matched["Deduction"].idxmax()]
            new_hi          = max(0, baseline_hi - max_deduction)
            delta           = new_hi - baseline_hi
 
            # ── KPI row ───────────────────────────────────────────────────────
            k1, k2, k3 = st.columns(3)
            k1.metric("Health Index (Before)", f"{baseline_hi:.4f}")
            k2.metric("Max Deduction",         f"{max_deduction:.4f}")
            k3.metric("Health Index (After)",  f"{new_hi:.4f}",
                      delta=f"{delta:.4f}", delta_color="inverse")
 
            st.markdown("---")
 
            # ── worst event detail ────────────────────────────────────────────
            st.subheader("⚠️ Worst Event (drives the deduction)")
            st.dataframe(
                events_matched.loc[[worst_event.name]],
                use_container_width=True
            )
 
            # ── all events with their deductions ─────────────────────────────
            st.subheader("📊 All Events & Deductions")
 
            def color_deduction(val):
                return "color: #e74c3c; font-weight:600"
 
            events_display = events_matched.copy()
            events_display["Weight (Asset_Condition)"] = asset_condition_weight
            events_display["Deduction"] = events_display["Deduction"].round(6)
 
            styled = (
                events_display.style
                .applymap(color_deduction, subset=["Deduction"])
            )
            st.dataframe(styled, use_container_width=True)
 
            # ── before / after chart ──────────────────────────────────────────
            st.subheader("📉 Before vs After Health Index")
            chart_df = pd.DataFrame({
                "State":        ["Before Events", "After Events"],
                "Health Index": [baseline_hi, new_hi],
            })
            fig3 = px.bar(
                chart_df,
                x="State",
                y="Health Index",
                color="State",
                text="Health Index",
                color_discrete_map={"Before Events": "#3498db", "After Events": "#e74c3c"},
                title="Health Index — Before vs After Events",
            )
            fig3.update_traces(texttemplate="%{text:.4f}", textposition="outside")
            fig3.update_layout(showlegend=False, yaxis_range=[0, max(baseline_hi * 1.1, 1)])
            st.plotly_chart(fig3, use_container_width=True)
 
            # ── download ──────────────────────────────────────────────────────
            st.markdown("---")
            summary_df = pd.DataFrame([{
                "Activo":                    "Transformador",
                "Asset_Condition(Actual)":   asset_condition_actual,
                "Asset_Condition(Weight)":   asset_condition_weight,
                "HealthIndex (Before)":      baseline_hi,
                "Max Deduction":             max_deduction,
                "HealthIndex (After)":       new_hi,
                "Delta":                     delta,
                "Worst Component":           worst_event.get("Componente", "—"),
                "Worst Condition":           worst_event["Condition"],
            }])
 
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                summary_df.to_excel(writer, index=False, sheet_name="Adjusted_HI")
                events_matched.to_excel(writer, index=False, sheet_name="Events")
            buffer.seek(0)
 
            st.download_button(
                label="📥 Download Adjusted Health Index (.xlsx)",
                data=buffer,
                file_name="adjusted_health_index.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
 
else:
    st.info("Sube el archivo Excel del transformador")
