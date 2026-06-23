import re
import os
os.environ.setdefault("PYTHONUTF8", "1")

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
from openai import OpenAI, RateLimitError
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator

st.set_page_config(
    page_title="Aktien KPI Analyse",
    page_icon="📈",
    layout="wide"
)

# ─── Session State ────────────────────────────────────────────────────────────
if "ticker" not in st.session_state:
    st.session_state.ticker = ""
if "ki_analyse" not in st.session_state:
    st.session_state.ki_analyse = None
if "ki_ticker" not in st.session_state:
    st.session_state.ki_ticker = None
if "ki_modell" not in st.session_state:
    st.session_state.ki_modell = None

def waehle_ticker(t):
    st.session_state.ticker = t

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

@st.cache_data(ttl=86400, show_spinner=False)
def uebersetze_de(text: str) -> str:
    if not text:
        return text
    try:
        return GoogleTranslator(source="en", target="de").translate(text[:4999])
    except Exception:
        return text

def ist_ungueltig(wert):
    return wert is None or (isinstance(wert, float) and pd.isna(wert))

# ─── BeautifulSoup Web Scraping ───────────────────────────────────────────────
# Zweite Datenquelle neben yfinance: Markt- und Sektor-P/E-Benchmarks werden
# direkt von Finanzportalen gescrapt, um die KPI-Bewertung einzuordnen.
@st.cache_data(ttl=3600, show_spinner=False)
def scrape_sp500_pe():
    """Scrapt den aktuellen S&P 500 P/E-Ratio von multpl.com als Marktbenchmark."""
    try:
        url = "https://www.multpl.com/s-p-500-pe-ratio"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        current_div = soup.find(id="current")
        if current_div:
            treffer = re.findall(r"\d+[\.,]\d+", current_div.get_text())
            if treffer:
                return float(treffer[0].replace(",", "."))
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def scrape_sektor_pe():
    """Scrapt Sektor-P/E-Benchmarks von finviz.com als kontextbezogene Vergleichswerte."""
    benchmarks = {}
    try:
        url = "https://finviz.com/groups.ashx?g=sector&v=120"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table.t-group tr") or soup.select("table tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 3:
                name = cells[0].get_text(strip=True)
                pe_text = cells[2].get_text(strip=True)
                if name and pe_text and pe_text not in ("-", ""):
                    try:
                        benchmarks[name] = float(pe_text)
                    except ValueError:
                        pass
    except Exception:
        pass
    return benchmarks

# ─── KPI-Scoring (Score 0–100) ────────────────────────────────────────────────
# Vier fundamentale Kennzahlen, jede wird auf eine Skala von 0 (unterbewertet)
# bis 100 (überbewertet) abgebildet und anschließend gewichtet kombiniert.
def score_pe(wert):
    if ist_ungueltig(wert) or wert <= 0:
        return None
    if wert < 10:  return 8
    if wert < 15:  return 22
    if wert < 20:  return 38
    if wert < 25:  return 50
    if wert < 30:  return 63
    if wert < 40:  return 76
    if wert < 55:  return 87
    return 93

def score_roe(wert):
    if ist_ungueltig(wert):
        return None
    if wert > 0.35: return 12
    if wert > 0.25: return 24
    if wert > 0.20: return 36
    if wert > 0.15: return 46
    if wert > 0.10: return 57
    if wert > 0.05: return 70
    if wert > 0.00: return 82
    return 92

def score_de(wert):
    if ist_ungueltig(wert):
        return None
    de = wert / 100 if abs(wert) > 5 else wert
    if de < 0:    return 90
    if de < 0.25: return 14
    if de < 0.50: return 27
    if de < 1.00: return 42
    if de < 1.50: return 55
    if de < 2.50: return 68
    if de < 4.00: return 80
    return 90

def score_ebitda(wert):
    if ist_ungueltig(wert) or wert <= 0:
        return None
    if wert < 5:  return 8
    if wert < 8:  return 22
    if wert < 11: return 38
    if wert < 14: return 50
    if wert < 18: return 63
    if wert < 22: return 76
    if wert < 30: return 86
    return 93

def gesamtbewertung(score_gewicht_paare):
    gueltig = [(s, w) for s, w in score_gewicht_paare if s is not None and w > 0]
    if not gueltig:
        return None, "Nicht genug Daten", "#808080", 0
    gesamt_w = sum(w for _, w in gueltig)
    score = sum(s * w for s, w in gueltig) / gesamt_w
    if score < 38:
        return score, "Unterbewertet", "#00c853", len(gueltig)
    if score <= 60:
        return score, "Fair bewertet", "#ffd600", len(gueltig)
    return score, "Überbewertet", "#dd2c00", len(gueltig)

def kpi_farbe(score):
    if score is None: return "#808080"
    if score < 38:    return "#00c853"
    if score <= 60:   return "#ffd600"
    return "#dd2c00"

def kpi_label(score):
    if score is None: return "Keine Daten"
    if score < 38:    return "Unterbewertet"
    if score <= 60:   return "Fair bewertet"
    return "Überbewertet"

# ─── KI-Analyse via OpenRouter ────────────────────────────────────────────────
# Kostenloses Modell-Kontingent über OpenRouter (OpenAI-kompatible API), da die
# Gemini-Free-Tier-Quota kontoabhängig sofort ausgeschöpft war und Anthropic
# kostenpflichtiges Guthaben voraussetzt. Mehrere :free-Modelle als Fallback,
# da einzelne Modelle beim jeweiligen Upstream-Provider kurzfristig
# überlastet sein können (429 Rate-Limit) – betrifft das Freikontingent
# anderer Nutzer, nicht den eigenen API-Key.
KI_MODELLE = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "google/gemma-4-31b-it:free",
]

def erstelle_ki_analyse(api_key, name, ticker_sym, sektor, pe, roe, de, ebitda,
                        gesamt_score, gesamt_label, sp500_pe, sektor_pe):
    """
    Ruft ein KI-Modell über OpenRouter auf und liefert eine strukturierte Fundamentalanalyse.
    Das Ausgabeformat ist fest vorgegeben, damit alle Analysen einheitlich sind.
    """
    pe_str     = f"{pe:.1f}x"               if not ist_ungueltig(pe)     else "nicht verfügbar"
    roe_str    = f"{roe*100:.1f} %"          if not ist_ungueltig(roe)    else "nicht verfügbar"
    de_str     = f"{de:.1f} %"              if not ist_ungueltig(de)     else "nicht verfügbar"
    ebitda_str = f"{ebitda:.1f}x"           if not ist_ungueltig(ebitda) else "nicht verfügbar"
    markt_str  = f"{sp500_pe:.1f}x"         if sp500_pe                  else "nicht verfügbar"
    sektor_str = f"{sektor_pe:.1f}x"        if sektor_pe                 else "nicht verfügbar"
    score_str  = f"{gesamt_score:.1f}/100"  if gesamt_score is not None  else "nicht berechnet"

    prompt = f"""Du bist ein erfahrener Finanzanalyst. Analysiere die folgende Aktie anhand der bereitgestellten Fundamentalkennzahlen und erstelle eine strukturierte Bewertung.

**Unternehmen:** {name} ({ticker_sym})
**Sektor:** {sektor}

**Fundamentalkennzahlen:**
- P/E Ratio (Kurs-Gewinn-Verhältnis): {pe_str} | S&P 500 Durchschnitt: {markt_str} | Sektor-Durchschnitt: {sektor_str}
- ROE (Eigenkapitalrendite): {roe_str} | Benchmark: >15 % gilt als gut
- D/E Ratio (Verschuldungsgrad): {de_str} | Benchmark: <100 % gilt als konservativ
- EV/EBITDA: {ebitda_str} | Marktdurchschnitt: ~12–16x

**Modellbewertung:** {gesamt_label} (Score: {score_str})

Erstelle deine Analyse EXAKT in folgendem Format – weiche nicht davon ab:

## KI-Fundamentalanalyse: {name} ({ticker_sym})

### 1. Kennzahlenanalyse

**P/E Ratio ({pe_str}):**
[2–3 Sätze: Einschätzung des P/E im Vergleich zum Markt- und Sektordurchschnitt. Ist die Aktie teuer oder günstig bewertet?]

**ROE ({roe_str}):**
[2–3 Sätze: Einschätzung der Eigenkapitalrendite. Wie effizient arbeitet das Unternehmen mit dem Eigenkapital?]

**D/E Ratio ({de_str}):**
[2–3 Sätze: Einschätzung des Verschuldungsgrads. Welches Finanzierungsrisiko ergibt sich daraus?]

**EV/EBITDA ({ebitda_str}):**
[2–3 Sätze: Einschätzung des EV/EBITDA. Was sagt dieser Wert über die Bewertung unabhängig von der Kapitalstruktur aus?]

### 2. Gesamteinschätzung
[3–4 Sätze: Zusammenfassung aller vier Kennzahlen. Wo liegen Stärken, wo Schwächen?]

### 3. Wesentliche Risiken
- [Risiko 1 mit kurzer Begründung]
- [Risiko 2 mit kurzer Begründung]
- [Risiko 3 mit kurzer Begründung]

### 4. Fazit
**Bewertungsurteil: {gesamt_label}**
[1–2 abschließende Sätze zur Einordnung. Hinweis: Diese Analyse ersetzt keine professionelle Anlageberatung.]

Antworte ausschließlich auf Deutsch. Halte dich strikt an das vorgegebene Format."""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    letzter_fehler = None
    for modell in KI_MODELLE:
        try:
            response = client.chat.completions.create(
                model=modell,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content, modell
        except RateLimitError as e:
            letzter_fehler = e
            continue
    raise letzter_fehler

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📈 Aktien Analyse")
    st.markdown("---")
    ticker_eingabe = st.text_input(
        "Ticker-Symbol",
        value=st.session_state.ticker,
        placeholder="z. B. AAPL, SAP.DE …",
        help="z. B. AAPL, MSFT, GOOGL, SAP.DE, BMW.DE"
    )
    if ticker_eingabe.strip().upper() != st.session_state.ticker:
        st.session_state.ticker = ticker_eingabe.strip().upper()

    st.button("Analysieren", type="primary", use_container_width=True)

    st.markdown("---")
    st.markdown("### ⚖️ KPI-Gewichtung")
    st.caption("Passe die Gewichtung an den Sektor an. Wird automatisch auf 100 % normalisiert.")

    w_pe     = st.slider("📊 P/E Ratio",  0, 100, 35, step=5,
                         help="Universellste Bewertungskennzahl — Standard: 35 %")
    w_roe    = st.slider("💹 ROE",         0, 100, 25, step=5,
                         help="Qualitätsmerkmal des Geschäftsmodells — Standard: 25 %")
    w_de     = st.slider("🏦 D/E Ratio",   0, 100, 15, step=5,
                         help="Verschuldungsrisiko (sektorsensitiv) — Standard: 15 %")
    w_ebitda = st.slider("📈 EV/EBITDA",   0, 100, 25, step=5,
                         help="Kapitalstruktur-neutrale Bewertung — Standard: 25 %")

    gesamt_w = w_pe + w_roe + w_de + w_ebitda
    if gesamt_w > 0:
        wn_pe, wn_roe, wn_de, wn_ebitda = (
            w_pe / gesamt_w, w_roe / gesamt_w,
            w_de / gesamt_w, w_ebitda / gesamt_w
        )
    else:
        wn_pe = wn_roe = wn_de = wn_ebitda = 0.25

    st.markdown(f"""
**Normalisierte Gewichte:**
| KPI | Gewicht |
|-----|---------|
| P/E Ratio | **{wn_pe*100:.1f} %** |
| ROE | **{wn_roe*100:.1f} %** |
| D/E Ratio | **{wn_de*100:.1f} %** |
| EV/EBITDA | **{wn_ebitda*100:.1f} %** |
""")

    st.markdown("---")
    st.markdown("**Schnellauswahl:**")
    for label, tickers in [
        ("🇺🇸 USA",         ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK-B"]),
        ("🇩🇪 Deutschland", ["SAP.DE", "BMW.DE", "SIE.DE", "ALV.DE", "VOW3.DE"]),
        ("🇨🇭 Schweiz",     ["NESN.SW", "NOVN.SW"]),
    ]:
        st.caption(label)
        cols = st.columns(2)
        for i, t in enumerate(tickers):
            cols[i % 2].button(t, key=f"btn_{t}", use_container_width=True,
                               on_click=waehle_ticker, args=(t,))

    st.markdown("---")
    st.markdown("""
**Bewertungsskala:**
🟢 Unterbewertet (Score < 38)
🟡 Fair bewertet  (Score 38–60)
🔴 Überbewertet   (Score > 60)
""")

ticker = st.session_state.ticker

# ─── Hauptbereich ─────────────────────────────────────────────────────────────
st.title("📈 Aktien KPI Analyser")

if not ticker:
    st.markdown("""
    <div style="text-align:center; padding: 80px 20px; color:#8b949e;">
        <div style="font-size:4rem;">📈</div>
        <h2 style="color:#f0f6fc; margin:20px 0 10px 0;">Aktien-Fundamentalanalyse</h2>
        <p style="font-size:1.1rem; margin-bottom:8px;">
            Gib links ein Ticker-Symbol ein oder wähle eine Aktie aus der Schnellauswahl.
        </p>
        <p style="font-size:0.9rem;">z. B. <code>AAPL</code> · <code>MSFT</code> · <code>SAP.DE</code> · <code>NESN.SW</code></p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

with st.spinner("Lade Marktbenchmarks via Web Scraping…"):
    sp500_pe       = scrape_sp500_pe()
    sektor_pe_dict = scrape_sektor_pe()

with st.spinner(f"Lade Finanzdaten für **{ticker}** via yfinance…"):
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        hist  = stock.history(period="1y")
    except Exception as e:
        st.error(f"Fehler beim Laden der yfinance-Daten: {e}")
        st.stop()

if not info or not any(info.get(k) for k in ("quoteType", "longName", "shortName", "regularMarketPrice", "currentPrice")):
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
sektor_pe_ref = sektor_pe_dict.get(sektor)

col_h1, col_h2 = st.columns([3, 2])
with col_h1:
    st.subheader(f"🏢 {name_unt}  ({ticker})")
    st.markdown(f"**Sektor:** {sektor}  |  **Branche:** {branche}  |  **Land:** {land}")
    beschr_en = info.get("longBusinessSummary", "")
    if beschr_en:
        with st.expander("Unternehmensbeschreibung"):
            with st.spinner("Übersetze…"):
                beschr_de = uebersetze_de(beschr_en)
            st.write(beschr_de)

with col_h2:
    m1, m2 = st.columns(2)
    if preis:
        delta_str = f"{change:.2f} %" if change else None
        m1.metric(f"Kurs ({waehrung})", f"{preis:,.2f}", delta=delta_str)
    if mktcap:
        m2.metric("Marktkapitalisierung", fmt_gross(mktcap))
    if hoch_52w and tief_52w:
        st.markdown(f"📏 **52-Wochen-Spanne:** {tief_52w:,.2f} – {hoch_52w:,.2f}")
    if sp500_pe:
        st.markdown(f"📊 **S&P 500 P/E (Markt):** {sp500_pe:.1f}x")
    if sektor_pe_ref:
        st.markdown(f"🏭 **Sektor-P/E ({sektor}):** {sektor_pe_ref:.1f}x")

st.divider()

# ─── KPI-Werte ────────────────────────────────────────────────────────────────
pe_wert     = info.get("trailingPE")
roe_wert    = info.get("returnOnEquity")
de_wert     = info.get("debtToEquity")
ebitda_wert = info.get("enterpriseToEbitda")

pe_score     = score_pe(pe_wert)
roe_score    = score_roe(roe_wert)
de_score     = score_de(de_wert)
ebitda_score = score_ebitda(ebitda_wert)

score_gewicht_paare = [
    (pe_score,     wn_pe),
    (roe_score,    wn_roe),
    (de_score,     wn_de),
    (ebitda_score, wn_ebitda),
]
gesamt_score, gesamt_label, gesamt_farbe, anz_daten = gesamtbewertung(score_gewicht_paare)

pe_wert_str     = f"{pe_wert:.1f}x"      if not ist_ungueltig(pe_wert)     else "–"
roe_wert_str    = f"{roe_wert*100:.1f} %" if not ist_ungueltig(roe_wert)    else "–"
de_wert_str     = f"{de_wert:.1f} %"     if not ist_ungueltig(de_wert)     else "–"
ebitda_wert_str = f"{ebitda_wert:.1f}x"  if not ist_ungueltig(ebitda_wert) else "–"

if sp500_pe and not ist_ungueltig(pe_wert):
    pe_ref_text = f"Markt: {sp500_pe:.1f}x" + (f" | Sektor: {sektor_pe_ref:.1f}x" if sektor_pe_ref else "")
else:
    pe_ref_text = "Historischer Ø: ~17–22x"

kpi_liste = [
    {"name": "P/E Ratio",  "untertitel": "Kurs-Gewinn-Verhältnis",   "wert": pe_wert_str,
     "score": pe_score,     "gewicht": wn_pe,
     "beschr": "Kurs / Gewinn (letzte 12 Monate). Niedrig = günstiger bewertet.",
     "ref": pe_ref_text},
    {"name": "ROE",        "untertitel": "Eigenkapitalrendite",       "wert": roe_wert_str,
     "score": roe_score,    "gewicht": wn_roe,
     "beschr": "Nettogewinn / Eigenkapital. >15 % = gut, >25 % = exzellent.",
     "ref": "Buffett-Benchmark: >15 %"},
    {"name": "D/E Ratio",  "untertitel": "Verschuldungsgrad",         "wert": de_wert_str,
     "score": de_score,     "gewicht": wn_de,
     "beschr": "Fremdkapital / Eigenkapital (in %). Niedrig = konservative Finanzierung.",
     "ref": "Benchmark: <100 % konservativ"},
    {"name": "EV/EBITDA",  "untertitel": "Enterprise Value / EBITDA", "wert": ebitda_wert_str,
     "score": ebitda_score, "gewicht": wn_ebitda,
     "beschr": "Unternehmenswert / EBITDA. Kapitalstruktur-neutral. <10x günstig.",
     "ref": "Marktdurchschnitt: ~12–16x"},
]

# ─── Tabs ─────────────────────────────────────────────────────────────────────
t1, t2, t3 = st.tabs([
    "🎯 Fundamentalbewertung",
    "🤖 KI-Analyse",
    "📉 Kursverlauf",
])

# ── TAB 1: Fundamentalbewertung ───────────────────────────────────────────────
with t1:
    st.subheader("Fundamentalbewertung")

    with st.expander("ℹ️ Methodik & Begründung der KPI-Auswahl"):
        markt_zeile = f"Referenz: Benjamin Grahams Schwelle <15x, aktueller Markt {sp500_pe:.1f}x." if sp500_pe else "Historischer Marktdurchschnitt ~17–22x."
        st.markdown(f"""
**Bewertungsmodell – 4 KPIs der Fundamentalanalyse**

| KPI | Begründung | Standard-Gewicht |
|-----|-----------|-----------------|
| **P/E (Kurs-Gewinn-Verhältnis)** | Universellste Bewertungskennzahl. Misst direkt, wie viel Anleger pro Euro Gewinn zahlen. {markt_zeile} | **35 %** |
| **ROE (Eigenkapitalrendite)** | Qualitätsmerkmal des Geschäftsmodells. Hohe ROE (>15 %) signalisiert effizienten Kapitaleinsatz und rechtfertigt Bewertungsprämien (Buffett-Prinzip). | **25 %** |
| **EV/EBITDA** | Kapitalstruktur-neutrale Ergänzung zum P/E – verhindert Verzerrungen bei unterschiedlich hoch verschuldeten Unternehmen. | **25 %** |
| **D/E (Verschuldungsgrad)** | Risikoindikator für Finanzierungsstruktur. Erhält das niedrigste Gewicht, da Branchennormen stark variieren (Banken, Versorger naturgemäß höher verschuldet). | **15 %** |

**Score-Logik (pro KPI: 0–100):** Gewichteter Durchschnitt → **< 38 Unterbewertet · 38–60 Fair · > 60 Überbewertet**

*Schwellenwerte basieren auf historischen Marktdurchschnittswerten (Damodaran, Graham).*
        """)

    cols = st.columns(4)
    for i, kpi in enumerate(kpi_liste):
        sc     = kpi["score"]
        fb     = kpi_farbe(sc)
        lb     = kpi_label(sc)
        sc_str = str(sc) if sc is not None else "–"
        gw_str = f"{kpi['gewicht']*100:.0f} %"
        with cols[i]:
            st.markdown(f"""
            <div style="border:1px solid #30363d; border-radius:12px; padding:16px;
                        text-align:center; background:#0d1117; margin:4px 0; min-height:195px">
                <div style="color:#8b949e; font-size:0.72rem; margin-bottom:2px">{kpi['name']}</div>
                <div style="color:#6e7681; font-size:0.65rem; margin-bottom:8px">{kpi['untertitel']}</div>
                <div style="font-size:1.85rem; font-weight:700; color:#f0f6fc">{kpi['wert']}</div>
                <div style="color:{fb}; font-weight:600; font-size:0.88rem; margin-top:8px">{lb}</div>
                <div style="color:#8b949e; font-size:0.72rem; margin-top:4px">Score: {sc_str}/100</div>
                <div style="color:#4CAF50; font-size:0.70rem; margin-top:4px">Gewicht: {gw_str}</div>
            </div>
            """, unsafe_allow_html=True)
            st.caption(kpi["beschr"])
            st.caption(f"📊 {kpi['ref']}")

    st.divider()

    st.subheader("🎯 Gesamtbewertung")
    col_gauge, col_urteil = st.columns([1, 2])

    with col_gauge:
        if gesamt_score is not None:
            fig_g = go.Figure(go.Indicator(
                mode="gauge+number",
                value=gesamt_score,
                number={"suffix": "/100", "valueformat": ".1f"},
                title={"text": "Bewertungsscore"},
                gauge={
                    "axis": {"range": [0, 100], "tickvals": [0, 38, 60, 100],
                             "ticktext": ["0", "38", "60", "100"]},
                    "bar": {"color": "#1a1a2e", "thickness": 0.3},
                    "steps": [
                        {"range": [0,  38], "color": "#00c853"},
                        {"range": [38, 60], "color": "#ffd600"},
                        {"range": [60, 100], "color": "#dd2c00"},
                    ],
                },
            ))
            fig_g.update_layout(height=240, margin=dict(t=40, b=0, l=10, r=10))
            st.plotly_chart(fig_g, use_container_width=True)
        else:
            st.warning("Nicht genug Daten für einen Gesamtscore.")

    with col_urteil:
        gesamt_emoji = "🟢" if gesamt_label == "Unterbewertet" else ("🟡" if gesamt_label == "Fair bewertet" else "🔴")
        details_html = "<br>".join(
            f"• {k['name']}: Score {k['score']}/100 – {kpi_label(k['score'])} (Gewicht: {k['gewicht']*100:.0f} %)"
            if k['score'] is not None else f"• {k['name']}: Keine Daten"
            for k in kpi_liste
        )
        score_display = f"{gesamt_score:.1f}/100" if gesamt_score is not None else "–"
        st.markdown(f"""
        <div style="border-left:5px solid {gesamt_farbe}; border-radius:8px;
                    padding:20px; background:#0d1117; margin:10px 0">
            <h2 style="color:{gesamt_farbe}; margin:0 0 10px 0">{gesamt_emoji} {gesamt_label}</h2>
            <p style="color:#8b949e; margin:0 0 10px 0">
                Gewichteter Score: <strong style="color:#f0f6fc">{score_display}</strong>
                &nbsp;·&nbsp; Basis: <strong style="color:#f0f6fc">{anz_daten}</strong>/4 KPIs
            </p>
            <p style="color:#6e7681; font-size:0.82rem; line-height:1.6; margin:0 0 12px 0">
                {details_html}
            </p>
            <p style="color:#6e7681; font-size:0.78rem; margin:0">
                ⚠️ Score &lt; 38 = Unterbewertet · 38–60 = Fair · &gt; 60 = Überbewertet
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    col_pie, col_bar = st.columns(2)
    with col_pie:
        fig_pie = go.Figure(go.Pie(
            labels=["P/E Ratio", "ROE", "D/E Ratio", "EV/EBITDA"],
            values=[wn_pe*100, wn_roe*100, wn_de*100, wn_ebitda*100],
            hole=0.42,
            marker_colors=["#2196F3", "#4CAF50", "#FF9800", "#9C27B0"],
            textinfo="label+percent",
        ))
        fig_pie.update_layout(title="Gewichtungsverteilung", height=300,
                              margin=dict(t=40, b=0, l=0, r=0), showlegend=False)
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_bar:
        kpi_scores = [pe_score, roe_score, de_score, ebitda_score]
        fig_bar = go.Figure(go.Bar(
            x=["P/E Ratio", "ROE", "D/E Ratio", "EV/EBITDA"],
            y=[s if s is not None else 0 for s in kpi_scores],
            marker_color=[kpi_farbe(s) for s in kpi_scores],
            text=[str(s) if s is not None else "–" for s in kpi_scores],
            textposition="outside",
        ))
        fig_bar.add_hline(y=38, line_dash="dash", line_color="#ffd600",
                          annotation_text="38 – Grenze Unter/Fair", annotation_position="top left")
        fig_bar.add_hline(y=60, line_dash="dash", line_color="#dd2c00",
                          annotation_text="60 – Grenze Fair/Über", annotation_position="top left")
        if gesamt_score is not None:
            fig_bar.add_hline(y=gesamt_score, line_dash="dot", line_color=gesamt_farbe,
                              annotation_text=f"Gesamtscore: {gesamt_score:.1f}",
                              annotation_position="bottom right")
        fig_bar.update_layout(title="KPI-Scores (0 = unterbewertet, 100 = überbewertet)",
                              yaxis=dict(range=[0, 105], title="Score"), height=300)
        st.plotly_chart(fig_bar, use_container_width=True)

# ── TAB 2: KI-Analyse ─────────────────────────────────────────────────────────
with t2:
    st.subheader("🤖 KI-gestützte Fundamentalanalyse")
    st.caption("Die KI bewertet die vier Kennzahlen nach einem festen Ausgabemuster für einheitliche, vergleichbare Analysen.")

    try:
        api_key = st.secrets.get("OPENROUTER_API_KEY")
    except Exception:
        api_key = None

    if not api_key:
        api_key = st.text_input(
            "OpenRouter API-Key", type="password",
            help="Erforderlich für die KI-Analyse. Kostenlos erhältlich unter openrouter.ai/keys"
        )

    analyse_starten = st.button("🤖 KI-Analyse starten", type="primary",
                                disabled=not api_key)

    # Analyse nur neu generieren wenn Ticker sich geändert hat oder Button geklickt
    if analyse_starten and api_key:
        st.session_state.ki_analyse = None  # Cache löschen bei neuem Klick
        st.session_state.ki_ticker  = None

    if api_key and (st.session_state.ki_ticker != ticker or st.session_state.ki_analyse is None):
        if analyse_starten:
            with st.spinner("KI analysiert die Kennzahlen…"):
                try:
                    ergebnis, modell_verwendet = erstelle_ki_analyse(
                        api_key      = api_key,
                        name         = name_unt,
                        ticker_sym   = ticker,
                        sektor       = sektor,
                        pe           = pe_wert,
                        roe          = roe_wert,
                        de           = de_wert,
                        ebitda       = ebitda_wert,
                        gesamt_score = gesamt_score,
                        gesamt_label = gesamt_label,
                        sp500_pe     = sp500_pe,
                        sektor_pe    = sektor_pe_ref,
                    )
                    st.session_state.ki_analyse = ergebnis
                    st.session_state.ki_ticker  = ticker
                    st.session_state.ki_modell  = modell_verwendet
                except RateLimitError:
                    st.error("❌ Alle kostenlosen KI-Modelle sind aktuell überlastet. Bitte in ca. 1 Minute erneut versuchen.")
                except Exception as e:
                    st.error(f"❌ Fehler bei der KI-Analyse: {e}")

    if st.session_state.ki_analyse and st.session_state.ki_ticker == ticker:
        st.markdown(f"""
        <div style="border-left: 5px solid {gesamt_farbe}; border-radius: 8px;
                    padding: 4px 20px 16px 20px; background: #0d1117; margin: 12px 0;">
        """, unsafe_allow_html=True)
        st.markdown(st.session_state.ki_analyse)
        st.markdown("</div>", unsafe_allow_html=True)
        st.caption(f"⚠️ KI-Ausgabe nach festem Muster generiert. Kein Ersatz für professionelle Anlageberatung. Modell: {st.session_state.ki_modell} (via OpenRouter)")
    elif not analyse_starten:
        st.info("Klicke auf **KI-Analyse starten**, um eine KI-gestützte Bewertung der Kennzahlen zu erhalten.")

# ── TAB 3: Kursverlauf ────────────────────────────────────────────────────────
with t3:
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
    "Anlageberatung dar. Finanzdaten: yfinance · Marktbenchmarks: multpl.com & finviz.com (BeautifulSoup) · "
    "KI-Analyse: Llama 3.3 (über OpenRouter)."
)
