from datetime import datetime, timezone
import yfinance as yf

from dal import DAL

SOURCE_ID = "yahoo_finance_daily"
SOURCE_NAME = "Yahoo Finance"

dal = DAL()
dal.create_indexes()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value):
    if value is None:
        return None
    try:
        if value != value:
            return None
        return float(value)
    except Exception:
        return None


def safe_int(value):
    if value is None:
        return None
    try:
        if value != value:
            return None
        return int(value)
    except Exception:
        return None


def build_source_doc():
    return {
        "source_id": SOURCE_ID,
        "name": SOURCE_NAME,
        "description": "Daily market data from Yahoo Finance via yfinance",
        "provider_type": "PYTHON_WRAPPER",
        "base_url": "https://finance.yahoo.com",
        "dataset_or_endpoint": "Ticker.history(period='1mo'/'max')",
        "asset_classes_supported": ["stock"],
        "attributes_supported": ["open", "high", "low", "close", "volume"],
        "system_date": utc_now(),
        "deleted": False
    }


def build_asset_doc(ticker_symbol, info):
    return {
        "asset_id": ticker_symbol,
        "asset_class": "stock",
        "symbol": ticker_symbol,
        "name": info.get("shortName") or info.get("longName") or ticker_symbol,
        "region": info.get("country", "unknown"),
        "description": info.get("sector", "stock from Yahoo Finance"),
        "attributes": {
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            "industry": info.get("industry"),
            "quote_type": info.get("quoteType")
        },
        "system_date": utc_now(),
        "deleted": False
    }


def build_timeseries_doc(ticker_symbol, idx, row, period):
    return {
        "asset_id": ticker_symbol,
        "source_id": SOURCE_ID,
        "business_date": idx.date().isoformat(),
        "system_date": utc_now(),
        "business_year": idx.year,
        "values": {
            "open": safe_float(row.get("Open")),
            "high": safe_float(row.get("High")),
            "low": safe_float(row.get("Low")),
            "close": safe_float(row.get("Close")),
            "volume": safe_int(row.get("Volume"))
        },
        "deleted": False,
        "provenance": {
            "provider": SOURCE_NAME,
            "library": "yfinance",
            "symbol": ticker_symbol,
            "period": period
        }
    }


def ingest_ticker(ticker_symbol, period="3mo"):
    dal.data_sources.save_version(build_source_doc())

    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    history = ticker.history(period=period)

    dal.assets.save_version(build_asset_doc(ticker_symbol, info))

    if history.empty:
        print(f"No history returned for {ticker_symbol}")
        return

    inserted_count = 0

    for idx, row in history.iterrows():
        doc = build_timeseries_doc(ticker_symbol, idx, row, period)
        saved = dal.time_series.save_version(doc)

        if saved.get("system_date") == doc["system_date"]:
            inserted_count += 1

    print(f"Ingestion finished for {ticker_symbol}, inserted={inserted_count}")


if __name__ == "__main__":
    ingest_ticker("AAPL", period="3mo")