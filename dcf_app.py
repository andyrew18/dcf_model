import math
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="DCF Equity Valuation App", layout="wide")

st.title("DCF Equity Valuation App")
st.markdown("This app estimates a stock's intrinsic value using a discounted cash flow model, compares it to the current market price, and explains each step so the user can understand the valuation process.")

with st.expander("What this app does"):
    st.markdown(
        """
        - Lets the user enter a ticker and key valuation assumptions.
        - Pulls current market data and some historical company information automatically.
        - Forecasts free cash flow, discounts it back to present value, and calculates terminal value.
        - Compares intrinsic value per share to the current market price.
        - Shows intermediate calculations so the valuation is transparent and can be replicated in Excel.
        """
    )


def fmt_num(x, pct=False):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "N/A"
    if pct:
        return f"{x:.1%}"
    ax = abs(x)
    if ax >= 1_000_000_000:
        return f"${x/1_000_000_000:,.2f}B"
    if ax >= 1_000_000:
        return f"${x/1_000_000:,.2f}M"
    if ax >= 1_000:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def safe_get(d, keys, default=np.nan):
    for k in keys:
        try:
            v = d.get(k, None)
            if v is not None:
                return v
        except Exception:
            pass
    return default


def get_company_data(ticker):
    tk = yf.Ticker(ticker)
    info = tk.info
    hist = tk.history(period="1y")
    price = None
    if not hist.empty and 'Close' in hist.columns:
        price = float(hist['Close'].dropna().iloc[-1])
    financials = tk.financials
    cashflow = tk.cashflow
    balance = tk.balance_sheet
    return info, hist, financials, cashflow, balance, price


def extract_base_inputs(info, financials, cashflow, balance):
    revenue = np.nan
    ebit = np.nan
    tax_rate = 0.21
    shares = np.nan
    cash = 0.0
    debt = 0.0

    try:
        if financials is not None and not financials.empty:
            idx = list(financials.index)
            for label in ["Total Revenue", "Operating Revenue", "Revenue"]:
                if label in idx:
                    revenue = float(financials.loc[label].dropna().iloc[0])
                    break
            for label in ["EBIT", "Operating Income", "Operating Income or Loss"]:
                if label in idx:
                    ebit = float(financials.loc[label].dropna().iloc[0])
                    break
    except Exception:
        pass

    try:
        shares = safe_get(info, ["sharesOutstanding", "impliedSharesOutstanding", "floatShares"])
        shares = float(shares) if pd.notna(shares) else np.nan
    except Exception:
        shares = np.nan

    try:
        tax_rate = safe_get(info, ["effectiveTaxRate"], 0.21)
        tax_rate = float(tax_rate) if pd.notna(tax_rate) else 0.21
        if tax_rate > 1:
            tax_rate = tax_rate / 100
        if tax_rate < 0 or tax_rate > 0.6:
            tax_rate = 0.21
    except Exception:
        tax_rate = 0.21

    try:
        if balance is not None and not balance.empty:
            idxb = list(balance.index)
            for label in ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash"]:
                if label in idxb:
                    cash = float(balance.loc[label].dropna().iloc[0])
                    break
            for label in ["Total Debt", "Current Debt And Capital Lease Obligation", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"]:
                if label in idxb:
                    debt = float(balance.loc[label].dropna().iloc[0])
                    break
    except Exception:
        pass

    if pd.isna(revenue) or revenue <= 0:
        revenue = safe_get(info, ["totalRevenue"], np.nan)
    if pd.isna(ebit) or revenue == 0:
        ebit = revenue * 0.15 if pd.notna(revenue) else np.nan

    op_margin = (ebit / revenue) if pd.notna(revenue) and revenue not in [0, np.nan] else 0.15
    if pd.isna(op_margin) or abs(op_margin) > 1:
        op_margin = 0.15

    return {
        "revenue": float(revenue) if pd.notna(revenue) else np.nan,
        "ebit": float(ebit) if pd.notna(ebit) else np.nan,
        "op_margin": float(op_margin),
        "tax_rate": float(tax_rate),
        "shares": float(shares) if pd.notna(shares) else np.nan,
        "cash": float(cash),
        "debt": float(debt),
    }


def build_dcf(base_revenue, years, growth_high, growth_fade, op_margin, tax_rate, fcf_conversion, wacc, terminal_growth):
    rows = []
    revenue = base_revenue
    growth_rates = np.linspace(growth_high, growth_fade, years)
    for year in range(1, years + 1):
        g = float(growth_rates[year - 1])
        revenue = revenue * (1 + g)
        ebit = revenue * op_margin
        nopat = ebit * (1 - tax_rate)
        fcf = nopat * fcf_conversion
        discount_factor = 1 / ((1 + wacc) ** year)
        pv_fcf = fcf * discount_factor
        rows.append([year, g, revenue, ebit, nopat, fcf, discount_factor, pv_fcf])

    df = pd.DataFrame(rows, columns=[
        "Year", "Revenue Growth", "Revenue", "EBIT", "NOPAT", "FCF", "Discount Factor", "PV of FCF"
    ])

    final_fcf = df.iloc[-1]["FCF"]
    terminal_fcf = final_fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1 + wacc) ** years)
    enterprise_value = df["PV of FCF"].sum() + pv_terminal

    return df, terminal_fcf, terminal_value, pv_terminal, enterprise_value


st.sidebar.header("User Inputs")
ticker = st.sidebar.text_input("Stock ticker", value="AAPL").upper().strip()
forecast_years = st.sidebar.slider("Forecast years", 5, 10, 5)

loaded = False
info = hist = financials = cashflow = balance = None
price = None
base = {
    "revenue": 1000000000.0,
    "op_margin": 0.15,
    "tax_rate": 0.21,
    "shares": 100000000.0,
    "cash": 0.0,
    "debt": 0.0,
}

if ticker:
    try:
        info, hist, financials, cashflow, balance, price = get_company_data(ticker)
        ext = extract_base_inputs(info, financials, cashflow, balance)
        for k, v in ext.items():
            if pd.notna(v):
                base[k] = v
        loaded = True
    except Exception as e:
        st.error(f"Could not load market data for {ticker}. Try another ticker. Error: {e}")

st.sidebar.subheader("Forecast Assumptions")
revenue_growth_yr1 = st.sidebar.number_input("Initial revenue growth (%)", min_value=-20.0, max_value=40.0, value=8.0, step=0.5) / 100
revenue_growth_terminal = st.sidebar.number_input("Final forecast year growth (%)", min_value=-5.0, max_value=15.0, value=3.0, step=0.5) / 100
operating_margin = st.sidebar.number_input("Operating margin (%)", min_value=-20.0, max_value=60.0, value=float(base["op_margin"] * 100 if pd.notna(base["op_margin"]) else 15.0), step=0.5) / 100
tax_rate = st.sidebar.number_input("Tax rate (%)", min_value=0.0, max_value=50.0, value=float(base["tax_rate"] * 100), step=0.5) / 100
fcf_conversion = st.sidebar.number_input("FCF conversion from NOPAT (%)", min_value=10.0, max_value=120.0, value=90.0, step=5.0) / 100
wacc = st.sidebar.number_input("Discount rate / WACC (%)", min_value=4.0, max_value=20.0, value=9.0, step=0.5) / 100
terminal_growth = st.sidebar.number_input("Terminal growth (%)", min_value=0.0, max_value=5.0, value=2.5, step=0.1) / 100

st.sidebar.subheader("Balance Sheet Inputs")
shares_out = st.sidebar.number_input("Shares outstanding", min_value=1.0, value=float(base["shares"] if pd.notna(base["shares"]) and base["shares"] > 0 else 100000000.0), step=1000000.0, format="%.0f")
cash = st.sidebar.number_input("Cash and equivalents ($)", min_value=0.0, value=float(max(base["cash"], 0.0)), step=1000000.0, format="%.0f")
debt = st.sidebar.number_input("Total debt ($)", min_value=0.0, value=float(max(base["debt"], 0.0)), step=1000000.0, format="%.0f")

base_revenue = st.sidebar.number_input("Base revenue ($)", min_value=1000000.0, value=float(base["revenue"] if pd.notna(base["revenue"]) and base["revenue"] > 0 else 1000000000.0), step=1000000.0, format="%.0f")

if terminal_growth >= wacc:
    st.error("Terminal growth must be less than the discount rate (WACC), or the terminal value formula will break.")
    st.stop()

company_name = info.get("shortName", ticker) if loaded and isinstance(info, dict) else ticker
market_cap = info.get("marketCap", None) if loaded and isinstance(info, dict) else None
sector = info.get("sector", "N/A") if loaded and isinstance(info, dict) else "N/A"
industry = info.get("industry", "N/A") if loaded and isinstance(info, dict) else "N/A"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Company", company_name)
c2.metric("Current Price", fmt_num(price) if price else "N/A")
c3.metric("Sector", sector)
c4.metric("Industry", industry)

if market_cap:
    st.caption(f"Market cap: {fmt_num(float(market_cap))}")

st.header("Model Inputs Explained")
exp1, exp2 = st.columns(2)
with exp1:
    st.markdown(
        """
        - **Ticker:** The stock being valued.
        - **Initial revenue growth:** The short-term growth assumption used in the early forecast years.
        - **Final forecast year growth:** The growth rate the company fades toward by the end of the forecast period.
        - **Operating margin:** Operating income as a percentage of revenue.
        - **Tax rate:** Used to convert EBIT into after-tax operating profit.
        """
    )
with exp2:
    st.markdown(
        """
        - **FCF conversion from NOPAT:** Approximates how much after-tax operating profit becomes free cash flow.
        - **WACC / discount rate:** The required return used to discount future cash flows back to present value.
        - **Terminal growth:** The long-run perpetual growth used in the terminal value formula.
        - **Cash, debt, and shares:** Used to bridge from enterprise value to equity value per share.
        """
    )

dcf_df, terminal_fcf, terminal_value, pv_terminal, enterprise_value = build_dcf(
    base_revenue, forecast_years, revenue_growth_yr1, revenue_growth_terminal, operating_margin, tax_rate, fcf_conversion, wacc, terminal_growth
)

net_debt = debt - cash
equity_value = enterprise_value - net_debt
intrinsic_value_per_share = equity_value / shares_out if shares_out > 0 else np.nan
upside = (intrinsic_value_per_share / price - 1) if price and price > 0 else np.nan

st.header("Valuation Result")
r1, r2, r3, r4 = st.columns(4)
r1.metric("Enterprise Value", fmt_num(enterprise_value))
r2.metric("Equity Value", fmt_num(equity_value))
r3.metric("Intrinsic Value / Share", fmt_num(intrinsic_value_per_share))
r4.metric("Upside / Downside vs Market", fmt_num(upside, pct=True) if pd.notna(upside) else "N/A")

if pd.notna(upside):
    if upside > 0:
        st.success("Based on these assumptions, the stock appears undervalued because intrinsic value is above the current market price.")
    else:
        st.warning("Based on these assumptions, the stock appears overvalued because intrinsic value is below the current market price.")

st.header("Step-by-Step Valuation")
st.markdown("The DCF process below shows how the valuation is built from projected operating performance, converted into free cash flow, then discounted back to present value.")

display_df = dcf_df.copy()
for col in ["Revenue Growth", "Discount Factor"]:
    display_df[col] = display_df[col].map(lambda x: f"{x:.2%}")
for col in ["Revenue", "EBIT", "NOPAT", "FCF", "PV of FCF"]:
    display_df[col] = display_df[col].map(lambda x: f"{x:,.0f}")
st.dataframe(display_df, use_container_width=True, hide_index=True)

st.subheader("Terminal Value Breakdown")
term1, term2, term3, term4 = st.columns(4)
term1.metric("Final Year FCF", fmt_num(float(dcf_df.iloc[-1]['FCF'])))
term2.metric("FCF in Year n+1", fmt_num(terminal_fcf))
term3.metric("Terminal Value", fmt_num(terminal_value))
term4.metric("PV of Terminal Value", fmt_num(pv_terminal))

with st.expander("Show formulas used"):
    st.markdown(
        """
        - Revenue forecast: Prior year revenue × (1 + growth rate)
        - EBIT: Revenue × operating margin
        - NOPAT: EBIT × (1 - tax rate)
        - Free cash flow: NOPAT × FCF conversion
        - Present value of each year FCF: FCF / (1 + WACC)^t
        - Terminal value: Final year FCF × (1 + g) / (WACC - g)
        - Enterprise value: Sum of PV of forecast FCFs + PV of terminal value
        - Equity value: Enterprise value - debt + cash
        - Intrinsic value per share: Equity value / shares outstanding
        """
    )

st.header("Sensitivity Table")
st.markdown("This table shows how intrinsic value per share changes when the discount rate and terminal growth assumptions change. This helps show that DCF models are sensitive to key assumptions.")

wacc_vals = [max(0.04, wacc - 0.01), wacc, min(0.20, wacc + 0.01)]
g_vals = [max(0.0, terminal_growth - 0.01), terminal_growth, min(wacc - 0.005, terminal_growth + 0.01)]

sens = []
for g in g_vals:
    row = []
    for r in wacc_vals:
        if g >= r:
            row.append(np.nan)
        else:
            _, _, _, pv_t, ev = build_dcf(base_revenue, forecast_years, revenue_growth_yr1, revenue_growth_terminal, operating_margin, tax_rate, fcf_conversion, r, g)
            eq = ev - net_debt
            row.append(eq / shares_out)
    sens.append(row)

sens_df = pd.DataFrame(
    sens,
    index=[f"g = {x:.1%}" for x in g_vals],
    columns=[f"WACC = {x:.1%}" for x in wacc_vals]
)
st.dataframe(sens_df.style.format("${:,.2f}"), use_container_width=True)

st.header("Historical Context")
if loaded and hist is not None and not hist.empty:
    price_chart = hist[["Close"]].copy()
    st.line_chart(price_chart)
else:
    st.info("Historical price data was not available for this ticker in the current session.")

st.header("How to Use in Your Project")
st.markdown(
    """
    - Use this app link in the submission Excel file after deployment.
    - Take screenshots of one example valuation case.
    - Replicate the same assumptions and formulas in Excel.
    - Make sure the Excel output matches the app output for that example.
    - Test the app on another computer before submitting.
    """
)

st.header("Limitations")
st.markdown(
    """
    - This is an educational DCF model, so some values may be simplified depending on the data available from Yahoo Finance.
    - Intrinsic value depends heavily on growth, margin, WACC, and terminal growth assumptions.
    - Users should treat the output as an estimate, not a guaranteed fair value.
    """
)
