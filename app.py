import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from datetime import date

# Page setup
st.set_page_config(page_title="SeaFreight360", layout="wide")
st.title("SeaFreight360 — Freight Ops Dashboard")
st.caption("Track sea-freight shipments, costs, invoices, warehouse flows, and client deliveries. Optimized for a Logistics workflow.")

# Nice number formatting in tables
pd.options.display.float_format = "{:,.2f}".format

# Tighter vertical spacing
st.markdown(
    "<style>.block-container{padding-top:1rem;padding-bottom:1rem;}</style>",
    unsafe_allow_html=True
)

# ---------- DATA ----------
@st.cache_data
def load_data_from_uploads(up_ship, up_inv, up_wh, up_cli):
    # fall back to /data/*.csv if no upload provided
    shipments = pd.read_csv(up_ship, parse_dates=["ETA"]) if up_ship else \
                pd.read_csv("data/shipments.csv", parse_dates=["ETA"])
    invoices  = pd.read_csv(up_inv,  parse_dates=["Due_Date","Payment_Date"]) if up_inv else \
                pd.read_csv("data/invoices.csv",  parse_dates=["Due_Date","Payment_Date"])
    warehouse = pd.read_csv(up_wh,   parse_dates=["Inbound_Date","Outbound_Date"]) if up_wh else \
                pd.read_csv("data/warehouse.csv", parse_dates=["Inbound_Date","Outbound_Date"])
    clients   = pd.read_csv(up_cli,  parse_dates=["Pickup_Date"]) if up_cli else \
                pd.read_csv("data/clients.csv",   parse_dates=["Pickup_Date"])

    # ----- SLA: Delivered_Date & On-Time (simulated) -----
    if {"Status","ETA"}.issubset(shipments.columns):
        delivered_mask = shipments["Status"].astype(str).str.lower().eq("delivered")
        rng = np.random.default_rng(42)
        on_time_flag = rng.random(delivered_mask.sum()) < 0.75
        delays = rng.integers(1, 6, size=delivered_mask.sum())

        delivered_dates, idx = [], 0
        for is_delivered in delivered_mask:
            if is_delivered:
                base_eta = shipments.iloc[idx]["ETA"]
                delivered_dates.append(base_eta if on_time_flag[idx] else base_eta + pd.Timedelta(days=int(delays[idx])))
                idx += 1
            else:
                delivered_dates.append(pd.NaT)

        shipments["Delivered_Date"] = pd.to_datetime(delivered_dates)
        shipments["On_Time"] = np.where(delivered_mask, shipments["Delivered_Date"] <= shipments["ETA"], np.nan)
    else:
        shipments["Delivered_Date"] = pd.NaT
        shipments["On_Time"] = np.nan

    # ----- Enrichments -----
    if {"Cost_Planned","Cost_Actual"}.issubset(shipments.columns):
        shipments["Cost_Variance"] = shipments["Cost_Actual"] - shipments["Cost_Planned"]
        shipments["Variance_%"] = (shipments["Cost_Variance"] / shipments["Cost_Planned"]) * 100
        shipments["Variance_%"] = shipments["Variance_%"].replace([np.inf, -np.inf], np.nan).round(1)

    if {"Origin_Port","Destination_Port"}.issubset(shipments.columns):
        shipments["Route"] = shipments["Origin_Port"].astype(str) + " → " + shipments["Destination_Port"].astype(str)

    today = pd.Timestamp(date.today())
    if "Paid_Status" in invoices.columns:
        invoices["Is_Outstanding"] = invoices["Paid_Status"].isin(["Unpaid","Overdue"])
    if "Due_Date" in invoices.columns:
        invoices["Overdue_Flag"] = invoices.get("Is_Outstanding", False) & (invoices["Due_Date"] < today)

    return shipments, invoices, warehouse, clients

# actually load the data
shipments, invoices, warehouse, clients = load_data_from_uploads(up_ship, up_inv, up_wh, up_cli)

# ---------- DATA UPLOAD ----------
with st.sidebar:
    st.subheader("Upload your own CSVs (optional)")
    up_ship = st.file_uploader("Shipments CSV", type="csv", key="u_ship")
    up_inv  = st.file_uploader("Invoices CSV",  type="csv", key="u_inv")
    up_wh   = st.file_uploader("Warehouse CSV", type="csv", key="u_wh")
    up_cli  = st.file_uploader("Clients CSV",   type="csv", key="u_cli")

# ---------- SIDEBAR (filters + role view) ----------
with st.sidebar:
    st.header("Filters")

    # role-based view (just used for guidance text later)
    role = st.selectbox("View as", ["All", "Logistics", "Finance", "Service"])

    # ---- safe helpers ----
    def col_safe(df, name):
        return name in df.columns

    # ---- PORT FILTERS ----
    if col_safe(shipments, "Origin_Port") and col_safe(shipments, "Destination_Port"):
        ports = sorted(
            set(shipments["Origin_Port"].astype(str).dropna())
            | set(shipments["Destination_Port"].astype(str).dropna())
        )
    else:
        ports = []

    default_port_pick = ports[: min(3, len(ports))] if ports else []

    sel_origin = st.multiselect("Origin Ports", options=ports, default=default_port_pick, key="origin_ports")
    sel_dest   = st.multiselect("Destination Ports", options=ports, default=default_port_pick, key="dest_ports")

    # ---- STATUS FILTER ----
    if col_safe(shipments, "Status"):
        statuses = sorted(shipments["Status"].astype(str).dropna().unique().tolist())
    else:
        statuses = []
    sel_status = st.multiselect("Shipment Status", options=statuses, default=statuses, key="status_filter")

    # ---- ETA WINDOW FILTER ----
    if col_safe(shipments, "ETA") and pd.api.types.is_datetime64_any_dtype(shipments["ETA"]):
        if shipments["ETA"].notna().any():
            min_eta = pd.to_datetime(shipments["ETA"].min())
            max_eta = pd.to_datetime(shipments["ETA"].max())
        else:
            min_eta = max_eta = pd.Timestamp.today()
    else:
        min_eta = max_eta = pd.Timestamp.today()

    eta_range = st.date_input(
        "ETA window",
        value=(min_eta.date(), max_eta.date()),
        key="eta_window"
    )

    # ---- APPLY FILTERS ----
    f = shipments.copy()

    # Only filter if columns exist
    if len(sel_origin) and col_safe(f, "Origin_Port"):
        f = f[f["Origin_Port"].astype(str).isin(sel_origin)]

    if len(sel_dest) and col_safe(f, "Destination_Port"):
        f = f[f["Destination_Port"].astype(str).isin(sel_dest)]

    if len(sel_status) and col_safe(f, "Status"):
        f = f[f["Status"].astype(str).isin(sel_status)]

    # date tuple guard
    if isinstance(eta_range, (list, tuple)) and len(eta_range) == 2 and col_safe(f, "ETA"):
        start = pd.Timestamp(eta_range[0])
        end   = pd.Timestamp(eta_range[1]) + pd.Timedelta(days=1)  # inclusive end
        f = f[(f["ETA"] >= start) & (f["ETA"] < end)]

    # ---- ACTIONS ----
    st.divider()
    st.download_button(
        "Download filtered shipments (CSV)",
        data=f.to_csv(index=False),
        file_name="filtered_shipments.csv",
        mime="text/csv"
    )

    if st.button("Reset filters"):
        st.session_state.pop("origin_ports", None)
        st.session_state.pop("dest_ports", None)
        st.session_state.pop("status_filter", None)
        st.session_state.pop("eta_window", None)
        st.rerun()

# ---------- KPI STRIP ----------
def kpi_row(df_s, df_i, df_w):
    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

    # --- shipments ---
    total_ship = len(df_s)
    delayed = 0
    if "Status" in df_s:
        delayed = int(df_s["Status"].astype(str).str.lower().isin(["delayed","pending customs"]).sum())
    delayed_pct = (delayed / total_ship * 100) if total_ship else 0

    # --- costs ---
    total_planned = float(df_s.get("Cost_Planned", pd.Series(dtype=float)).sum())
    total_actual  = float(df_s.get("Cost_Actual", pd.Series(dtype=float)).sum())
    variance = total_actual - total_planned
    variance_pct = (variance / total_planned * 100) if total_planned else 0

    # --- invoices ---
    outstanding_amt = 0
    if not df_i.empty and "Amount" in df_i and "Is_Outstanding" in df_i:
        outstanding_amt = float(df_i.loc[df_i["Is_Outstanding"], "Amount"].sum())

    paid_rate = 0
    if "Paid_Status" in df_i and len(df_i) > 0:
        paid_rate = (df_i["Paid_Status"].eq("Paid").mean()) * 100

    # --- warehouse ---
    on_hand = 0
    if "Outbound_Date" in df_w and "Quantity" in df_w:
        today = pd.Timestamp(date.today())
        on_hand = int(df_w.loc[df_w["Outbound_Date"] >= today, "Quantity"].sum())

    # --- SLA ---
    sla = 0
    if "Status" in df_s and "On_Time" in df_s:
        delivered_only = df_s[df_s["Status"].astype(str).str.lower() == "delivered"]
        if not delivered_only.empty:
            sla = (delivered_only["On_Time"].mean() * 100)

    # --- display ---
    col1.metric("Total Shipments", f"{total_ship}")
    col2.metric("Delayed %", f"{delayed_pct:.1f}%")
    col3.metric("Planned Cost", f"${total_planned:,.0f}")
    col4.metric("Actual Cost", f"${total_actual:,.0f}", delta=f"${variance:,.0f} ({variance_pct:.1f}%)")
    col5.metric("Invoices Paid", f"{paid_rate:.1f}%")
    col6.metric("Outstanding $", f"${outstanding_amt:,.0f}")
    col7.metric("On-time SLA", f"{sla:.1f}%")

# render KPIs
kpi_row(f, invoices, warehouse)
st.divider()

# ---------- TABS ----------
tabs = st.tabs(["Shipments", "Finance / Invoices", "Warehouse", "Clients"])

# ========== TAB 1: SHIPMENTS ==========
with tabs[0]:
    st.subheader("Shipment Tracker (filtered)")
    st.dataframe(f, use_container_width=True)

    left, right = st.columns([1, 1])

    with left:
        st.markdown("**Status Breakdown**")
        if "Status" in f.columns and not f.empty:
            st.bar_chart(f["Status"].value_counts())
        else:
            st.info("No status data available for current filter.")

    with right:
        if {"Cost_Planned", "Cost_Actual", "Container_ID"}.issubset(f.columns) and not f.empty:
            st.markdown("**Planned vs Actual (by Container)**")
            fig_cost = px.line(
                f.sort_values("Container_ID"),
                x="Container_ID",
                y=["Cost_Planned", "Cost_Actual"],
                markers=True
            )
            st.plotly_chart(fig_cost, use_container_width=True)
        else:
            st.info("Cost data not available for current filter.")

    # Route variance chart
    if {"Route", "Variance_%", "Cost_Variance"}.issubset(f.columns) and not f.empty:
        st.markdown("**Top Cost Variance by Route**")
        route_var = (
            f.groupby("Route", as_index=False)[["Cost_Variance", "Variance_%"]]
             .mean()
             .sort_values("Cost_Variance", ascending=False)
             .head(10)
        )
        if not route_var.empty:
            fig_route = px.bar(
                route_var, x="Route", y="Cost_Variance", text="Variance_%",
                title="Avg variance by route"
            )
            fig_route.update_xaxes(tickangle=30)
            st.plotly_chart(fig_route, use_container_width=True)
        else:
            st.info("No variance data to display.")

    # ---------- Alerts ----------
    st.markdown("### Alerts")
    alerts_left, alerts_right = st.columns([1, 1])

    # Top 5 cost overruns
    with alerts_left:
        if "Cost_Variance" in f.columns and not f.empty:
            overruns = f.sort_values("Cost_Variance", ascending=False).head(5)
            st.write("**Top Cost Overruns (by container)**")
            cols_to_show = [c for c in ["Container_ID", "Route", "Cost_Planned", "Cost_Actual", "Cost_Variance"] if c in f.columns]
            st.dataframe(overruns[cols_to_show], use_container_width=True)
        else:
            st.info("No overrun data for current filter.")

    # Shipments approaching ETA but not cleared/delivered
    with alerts_right:
        if {"ETA", "Status"}.issubset(f.columns) and not f.empty:
            upcoming = f[
                (f["ETA"] <= pd.Timestamp.today() + pd.Timedelta(days=3)) &
                (~f["Status"].astype(str).str.lower().isin(["delivered", "cleared"]))
            ].sort_values("ETA").head(5)
            st.write("**ETA ≤ 3 days & not cleared/delivered**")
            cols_to_show = [c for c in ["Container_ID", "Route", "ETA", "Status"] if c in f.columns]
            st.dataframe(upcoming[cols_to_show], use_container_width=True)
        else:
            st.info("No ETA risk items for current filter.")

# ========== FINANCE / INVOICES ==========
with tabs[1]:
    st.subheader("Invoice Overview")
    st.dataframe(invoices, use_container_width=True)

    c1, c2 = st.columns(2)

    # --- Payment status mix ---
    with c1:
        st.markdown("**Payment Status**")
        if "Paid_Status" in invoices.columns and not invoices.empty:
            st.bar_chart(invoices["Paid_Status"].value_counts())
        else:
            st.info("No payment status data available.")

    # --- Outstanding by due date ---
    with c2:
        st.markdown("**Outstanding by Due Date**")
        if {"Is_Outstanding", "Due_Date"}.issubset(invoices.columns) and not invoices.empty:
            outstanding = invoices[invoices["Is_Outstanding"]].sort_values("Due_Date")
            cols = [c for c in ["Invoice_ID","Container_ID","Amount","Paid_Status","Due_Date"] if c in outstanding.columns]
            st.dataframe(outstanding[cols].head(15), use_container_width=True)
        else:
            outstanding = pd.DataFrame()
            st.info("No outstanding invoices or missing columns.")

    # --- Overdue impact metric ---
    st.markdown("### Overdue Impact (Value at risk)")
    if "Overdue_Flag" in invoices.columns and "Amount" in invoices.columns and not invoices.empty:
        overdue_total = float(invoices.loc[invoices["Overdue_Flag"], "Amount"].sum())
        st.metric("Overdue Amount", f"${overdue_total:,.0f}")
    else:
        st.info("Overdue flags or amounts not available.")

    # --- Download outstanding ---
    if not outstanding.empty:
        st.download_button(
            "Download outstanding invoices (CSV)",
            outstanding.to_csv(index=False),
            "outstanding_invoices.csv",
            "text/csv"
        )

# ========== WAREHOUSE ==========
with tabs[2]:
    st.subheader("Inbound / Outbound Register")
    st.dataframe(warehouse, use_container_width=True)

    # Safety flags
    has_inbound = {"Inbound_Date", "Quantity"}.issubset(warehouse.columns)
    has_location = {"Location", "Quantity"}.issubset(warehouse.columns)
    has_outbound = "Outbound_Date" in warehouse.columns

    # Inbound trend
    if has_inbound and not warehouse.empty:
        st.markdown("**Inbound Quantity Over Time**")
        wh_in = warehouse.dropna(subset=["Inbound_Date"]).sort_values("Inbound_Date")
        if not wh_in.empty:
            fig_in = px.line(wh_in, x="Inbound_Date", y="Quantity")
            st.plotly_chart(fig_in, use_container_width=True)
        else:
            st.info("No inbound dates available.")
    else:
        st.info("Inbound_Date or Quantity missing.")

    # Quantity by location
    if has_location and not warehouse.empty:
        st.markdown("**Quantity by Location**")
        loc = (
            warehouse.groupby("Location", as_index=False)["Quantity"]
            .sum().sort_values("Quantity", ascending=False)
        )
        if not loc.empty:
            fig_loc = px.bar(loc, x="Location", y="Quantity")
            st.plotly_chart(fig_loc, use_container_width=True)
        else:
            st.info("No location data to summarize.")
    else:
        st.info("Location or Quantity column missing.")

    # On-hand now
    if has_outbound and "Quantity" in warehouse.columns:
        today = pd.Timestamp(date.today())
        on_hand_now = warehouse.loc[warehouse["Outbound_Date"] >= today, "Quantity"].sum()
        st.caption(f"**Inventory on hand (today):** {int(on_hand_now):,}")

# ========== CLIENTS ==========
with tabs[3]:
    st.subheader("Client Pickups & Deliveries")
    st.dataframe(clients, use_container_width=True)

    # Delivery status mix
    if "Status" in clients.columns and not clients.empty:
        st.markdown("**Delivery Status Mix**")
        st.bar_chart(clients["Status"].astype(str).value_counts())
    else:
        st.info("No client status data available.")

    # Next pickups within 7 days
    if "Pickup_Date" in clients.columns and not clients.empty:
        st.markdown("**Upcoming Pickups (≤ 7 days)**")
        upcoming_pickups = clients[
            (clients["Pickup_Date"] >= pd.Timestamp(date.today())) &
            (clients["Pickup_Date"] <= pd.Timestamp(date.today()) + pd.Timedelta(days=7))
        ].sort_values("Pickup_Date").head(10)
        if not upcoming_pickups.empty:
            cols_show = [c for c in ["Client_ID","Name","Pickup_Date","Delivery_Address","Status"] if c in clients.columns]
            st.dataframe(upcoming_pickups[cols_show], use_container_width=True)
        else:
            st.caption("No pickups in the next 7 days.")

# ---------- ROLE-BASED QUICK LINKS ----------
# (Assumes `role` is set in the sidebar and `f` is your filtered shipments df)
if role == "Logistics":
    st.info("Quick Logistics view: Focus on **Shipments** → Status Breakdown and **Warehouse** → Quantity by Location.")
elif role == "Finance":
    st.info("Quick Finance view: Check **Invoices** → Outstanding by Due Date and KPI strip (variance & paid%).")
elif role == "Service":
    st.info("Quick Service view: **Clients** tab → Delivery status mix. Use sidebar filters for affected routes.")
else:
    st.caption("Tip: Use the sidebar filters to narrow by origin/destination, status, and ETA window.")

# Dynamic hint based on current filter
if "Status" in f.columns and len(f) > 0:
    delayed_pct = (f["Status"].astype(str).str.lower().isin(["delayed", "pending customs"]).mean()) * 100
    if delayed_pct >= 20:
        st.warning(f"High delay rate in current view: {delayed_pct:.1f}% — check **Shipments → Alerts** for ETA-at-risk.")