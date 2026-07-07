# Aktien KPI Analyser

Interaktive Streamlit-Webanwendung zur fundamentalen Aktienanalyse.  
Uni-Projekt im Kurs *Applied Finance*.

## Funktionsumfang

- **Fundamentalbewertung** – vier KPIs (P/E, ROE, EV/EBITDA, D/E) werden auf einer Skala 0–100 bewertet und zu einem gewichteten Gesamtscore zusammengefasst
- **Anpassbare Gewichtung** – Slider in der Seitenleiste erlauben sektorspezifische Anpassung der KPI-Gewichte
- **Marktbenchmarks** – aktueller S&P-500-P/E (multpl.com) und Sektor-P/E (finviz.com) werden per Web Scraping geladen
- **KI-Analyse** – lokales Text-Generation-Modell (Qwen2.5-1.5B-Instruct via HuggingFace Transformers) erstellt eine deutsche Fundamentalanalyse, kein API-Key erforderlich
- **Kursverlauf** – Candlestick-Chart mit 50- und 200-Tage-Gleitdurchschnitt

## Installation & Starten

```bash
uv sync
uv run streamlit run app.py
```

Beim ersten Start der KI-Analyse wird das Modell (~1,5 GB) automatisch von HuggingFace heruntergeladen.

## Datenquellen

| Quelle | Verwendung |
|--------|-----------|
| [yfinance](https://github.com/ranaroussi/yfinance) | Finanzkennzahlen, Kursdaten |
| [multpl.com](https://www.multpl.com/s-p-500-pe-ratio) | S&P-500-P/E als Marktbenchmark |
| [finviz.com](https://finviz.com/groups.ashx?g=sector&v=120) | Sektor-P/E-Vergleichswerte |
| [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) | Lokales LLM für KI-Analyse |
