import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(
    page_title="Aktien KPI Analyse",
    page_icon="📈",
    layout="wide"
)

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────
def fmt_gross(wert):
    if wert is None or (isinstance(wert, float) and pd.isna(wert)):
        return "–"
    if abs(wert) >= 1e12:
        return f"{wert / 1e12:.2f} Bio."
    if abs(wert) >= 1e9:
        return f"{wert / 1e9:.2f} Mrd."
    if abs(wert) >= 1e6:
        return f"{wert / 1e6:.2f} Mio."
    return f"{wert:,.0f}"

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📈 Aktien Analyse")
    st.markdown("---")
    ticker = st.text_input(
        "Ticker-Symbol", value="AAPL",
        help="z. B. AAPL, MSFT, GOOGL, SAP.DE, BMW.DE"
    )
    st.button("Analysieren", type="primary", use_container_width=True)

# ─── Hauptbereich ─────────────────────────────────────────────────────────────
st.title("📈 Aktien KPI Analyser")

with st.spinner(f"Lade Finanzdaten für **{ticker}** via yfinance…"):
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        hist  = stock.history(period="1y")
    except Exception as e:
        st.error(f"Fehler beim Laden der yfinance-Daten: {e}")
        st.stop()

if not info or not info.get("quoteType"):
    st.error(f"Keine Daten für **{ticker}** gefunden. Bitte Ticker-Symbol prüfen.")
    st.stop()

# ─── Unternehmens-Header ──────────────────────────────────────────────────────
name_unt = info.get("longName", ticker)
sektor   = info.get("sector", "–")
branche  = info.get("industry", "–")
land     = info.get("country", "–")
waehrung = info.get("currency", "")
preis    = info.get("currentPrice") or info.get("regularMarketPrice")
change   = info.get("regularMarketChangePercent")
mktcap   = info.get("marketCap")
hoch_52w = info.get("fiftyTwoWeekHigh")
tief_52w = info.get("fiftyTwoWeekLow")

col_h1, col_h2 = st.columns([3, 2])
with col_h1:
    st.subheader(f"🏢 {name_unt}  ({ticker})")
    st.markdown(f"**Sektor:** {sektor}  |  **Branche:** {branche}  |  **Land:** {land}")
    beschr = info.get("longBusinessSummary", "")
    if beschr:
        with st.expander("Unternehmensbeschreibung"):
            st.write(beschr)

with col_h2:
    m1, m2 = st.columns(2)
    if preis:
        delta_str = f"{change:.2f} %" if change else None
        m1.metric(f"Kurs ({waehrung})", f"{preis:,.2f}", delta=delta_str)
    if mktcap:
        m2.metric("Marktkapitalisierung", fmt_gross(mktcap))
    if hoch_52w and tief_52w:
        st.markdown(f"📏 **52-Wochen-Spanne:** {tief_52w:,.2f} – {hoch_52w:,.2f}")

st.divider()

# ─── Kursverlauf ──────────────────────────────────────────────────────────────
st.subheader("Kursverlauf – letzte 12 Monate")

if hist.empty:
    st.warning("Keine historischen Kursdaten verfügbar.")
else:
    hist["MA50"]  = hist["Close"].rolling(50).mean()
    hist["MA200"] = hist["Close"].rolling(200).mean()

    fig_c = go.Figure()
    fig_c.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"], name="Kurs",
    ))
    fig_c.add_trace(go.Scatter(
        x=hist.index, y=hist["MA50"],
        name="50-Tage-Ø", line=dict(color="#ff9800", width=1.5),
    ))
    fig_c.add_trace(go.Scatter(
        x=hist.index, y=hist["MA200"],
        name="200-Tage-Ø", line=dict(color="#f44336", width=1.5),
    ))
    fig_c.update_layout(
        xaxis_rangeslider_visible=False,
        yaxis_title=f"Kurs ({waehrung})",
        height=480,
    )
    st.plotly_chart(fig_c, use_container_width=True)

    erster  = hist["Close"].iloc[0]
    letzter = hist["Close"].iloc[-1]
    rendite = (letzter - erster) / erster * 100

    c1, c2, c3 = st.columns(3)
    c1.metric("Kurs vor 12 Monaten", f"{erster:,.2f} {waehrung}")
    c2.metric("Aktueller Kurs",       f"{letzter:,.2f} {waehrung}")
    c3.metric("1-Jahres-Performance", f"{rendite:.2f} %", delta=f"{rendite:.2f} %")

# ─── Footer ───────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "⚠️ **Haftungsausschluss:** Diese App dient ausschließlich zu Bildungszwecken und stellt keine "
    "Anlageberatung dar. Finanzdaten: yfinance."
)
