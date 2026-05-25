from datetime import datetime, timezone
import yfinance as yf
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["financial_dwh"]

assets_col = db["assets"]
sources_col = db["data_sources"]
timeseries_col = db["time_series"]

SOURCE_ID = "yahoo_finance_daily"
SOURCE_NAME = "Yahoo Finance"

def ensure_source():
    sources_col.update_one(
        {"source_id": SOURCE_ID},
        {
            "$setOnInsert": {
                "source_id": SOURCE_ID,
                "name": SOURCE_NAME,
                "description": "Daily market data from Yahoo Finance via yfinance",
                "provider_type": "PYTHON_WRAPPER",
                "base_url": "https://finance.yahoo.com",
                "dataset_or_endpoint": "Ticker.history(period='1mo'/'max')",
                "asset_classes_supported": ["stock"],
                "attributes_supported": ["open", "high", "low", "close", "volume"],
                "system_date": datetime.now(timezone.utc).isoformat()
            }
        },
        upsert=True
    )

def ensure_asset(ticker_symbol, info):
    asset_doc = {
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
        "system_date": datetime.now(timezone.utc).isoformat()
    }

    assets_col.update_one(
        {"asset_id": ticker_symbol},
        {"$setOnInsert": asset_doc},
        upsert=True
    )

def ingest_ticker(ticker_symbol, period="1mo"):
    ensure_source()

    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    ensure_asset(ticker_symbol, info)

    history = ticker.history(period=period)

    if history.empty:
        print(f"No history returned for {ticker_symbol}")
        return

    now_system_date = datetime.now(timezone.utc).isoformat()

    for idx, row in history.iterrows():
        business_date = idx.date().isoformat()

        doc = {
            "asset_id": ticker_symbol,
            "source_id": SOURCE_ID,
            "business_date": business_date,
            "system_date": now_system_date,
            "business_year": idx.year,
            "values": {
                "open": None if row.get("Open") != row.get("Open") else float(row.get("Open")),
                "high": None if row.get("High") != row.get("High") else float(row.get("High")),
                "low": None if row.get("Low") != row.get("Low") else float(row.get("Low")),
                "close": None if row.get("Close") != row.get("Close") else float(row.get("Close")),
                "volume": None if row.get("Volume") != row.get("Volume") else int(row.get("Volume"))
            },
            "deleted": False,
            "provenance": {
                "provider": SOURCE_NAME,
                "library": "yfinance",
                "symbol": ticker_symbol,
                "period": period
            }
        }

        existing = timeseries_col.find_one({
            "asset_id": doc["asset_id"],
            "source_id": doc["source_id"],
            "business_date": doc["business_date"],
            "system_date": doc["system_date"]
        })

        if not existing:
            timeseries_col.insert_one(doc)

    print(f"Ingestion finished for {ticker_symbol}")

if __name__ == "__main__":
    ingest_ticker("AAPL", period="3mo")