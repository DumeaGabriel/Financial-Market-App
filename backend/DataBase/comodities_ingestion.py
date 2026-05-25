from datetime import datetime, timezone
import yfinance as yf
from pymongo import MongoClient, ASCENDING, DESCENDING

client = MongoClient("mongodb://localhost:27017")
db = client["financial_dwh"]

assets_col = db["assets"]
sources_col = db["data_sources"]
timeseries_col = db["time_series"]

SOURCE_ID = "yahoo_finance_commodities"
SOURCE_NAME = "Yahoo Finance"

COMMODITY_SYMBOLS = ["GC=F", "SI=F", "HG=F", "CL=F", "NG=F", "ZC=F"]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def create_indexes():
    assets_col.create_index([("asset_id", ASCENDING)], unique=True)
    sources_col.create_index([("source_id", ASCENDING)], unique=True)
    timeseries_col.create_index([
        ("asset_id", ASCENDING),
        ("source_id", ASCENDING),
        ("business_date", ASCENDING),
        ("system_date", DESCENDING)
    ])


def ensure_source():
    sources_col.update_one(
        {"source_id": SOURCE_ID},
        {
            "$setOnInsert": {
                "source_id": SOURCE_ID,
                "name": SOURCE_NAME,
                "description": "Commodity futures market data from Yahoo Finance via yfinance",
                "provider_type": "PYTHON_WRAPPER",
                "base_url": "https://finance.yahoo.com",
                "dataset_or_endpoint": "Ticker.info + Ticker.history(period='3mo')",
                "asset_classes_supported": ["commodity"],
                "attributes_supported": ["open", "high", "low", "close", "volume"],
                "system_date": utc_now()
            }
        },
        upsert=True
    )


def get_ticker_info_safe(ticker):
    try:
        info = ticker.info
        if isinstance(info, dict):
            return info
    except Exception:
        pass
    return {}


def normalize_commodity_name(symbol, info):
    if info.get("shortName"):
        return info["shortName"]
    if info.get("longName"):
        return info["longName"]

    fallback_names = {
        "GC=F": "Gold Futures",
        "SI=F": "Silver Futures",
        "HG=F": "Copper Futures",
        "CL=F": "Crude Oil Futures",
        "NG=F": "Natural Gas Futures",
        "ZC=F": "Corn Futures"
    }
    return fallback_names.get(symbol, symbol)


def build_asset_doc(symbol, info):
    return {
        "asset_id": symbol,
        "asset_class": "commodity",
        "symbol": symbol,
        "name": normalize_commodity_name(symbol, info),
        "region": info.get("country") or "global",
        "description": info.get("description") or f"Commodity futures asset {symbol} from Yahoo Finance",
        "attributes": {
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            "quote_type": info.get("quoteType"),
            "market": info.get("market"),
            "instrument_type": "futures"
        },
        "system_date": utc_now()
    }


def ensure_asset(symbol, info):
    asset_doc = build_asset_doc(symbol, info)

    result = assets_col.update_one(
        {"asset_id": symbol},
        {
            "$set": {
                "asset_class": asset_doc["asset_class"],
                "symbol": asset_doc["symbol"],
                "name": asset_doc["name"],
                "region": asset_doc["region"],
                "description": asset_doc["description"],
                "attributes": asset_doc["attributes"]
            },
            "$setOnInsert": {
                "system_date": asset_doc["system_date"]
            }
        },
        upsert=True
    )

    if result.upserted_id is not None:
        print(f"Inserted asset: {symbol}")
    else:
        print(f"Asset already exists or updated: {symbol}")


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


def build_values(row):
    return {
        "open": safe_float(row.get("Open")),
        "high": safe_float(row.get("High")),
        "low": safe_float(row.get("Low")),
        "close": safe_float(row.get("Close")),
        "volume": safe_int(row.get("Volume"))
    }


def build_timeseries_doc(symbol, row_date, row, period):
    return {
        "asset_id": symbol,
        "source_id": SOURCE_ID,
        "business_date": row_date.date().isoformat(),
        "system_date": utc_now(),
        "business_year": row_date.year,
        "values": build_values(row),
        "deleted": False,
        "provenance": {
            "provider": SOURCE_NAME,
            "library": "yfinance",
            "symbol": symbol,
            "period": period
        }
    }


def latest_existing_doc(symbol, business_date):
    return timeseries_col.find_one(
        {
            "asset_id": symbol,
            "source_id": SOURCE_ID,
            "business_date": business_date
        },
        sort=[("system_date", DESCENDING)]
    )


def should_insert_new_version(existing_doc, new_doc):
    if existing_doc is None:
        return True
    if existing_doc.get("deleted") != new_doc.get("deleted"):
        return True
    if existing_doc.get("values") != new_doc.get("values"):
        return True
    return False


def ingest_commodity(symbol, period="3mo"):
    print(f"Ingesting {symbol}...")

    ticker = yf.Ticker(symbol)
    info = get_ticker_info_safe(ticker)
    history = ticker.history(period=period)

    ensure_asset(symbol, info)

    if history.empty:
        print(f"Skipping time series for {symbol}: no history returned")
        return

    inserted_count = 0
    skipped_count = 0

    for row_date, row in history.iterrows():
        new_doc = build_timeseries_doc(symbol, row_date, row, period)
        business_date = new_doc["business_date"]

        existing_doc = latest_existing_doc(symbol, business_date)

        if should_insert_new_version(existing_doc, new_doc):
            timeseries_col.insert_one(new_doc)
            inserted_count += 1
        else:
            skipped_count += 1

    print(f"{symbol}: inserted={inserted_count}, skipped={skipped_count}")


def run(period="3mo"):
    create_indexes()
    ensure_source()

    for symbol in COMMODITY_SYMBOLS:
        try:
            ingest_commodity(symbol, period=period)
        except Exception as e:
            print(f"Error ingesting {symbol}: {e}")


if __name__ == "__main__":
    run(period="3mo")