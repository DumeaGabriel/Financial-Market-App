from datetime import datetime, timezone

import yfinance as yf
from pymongo.errors import DuplicateKeyError

from dal import DAL

SOURCE_ID = "yahoo_finance_crypto"
SOURCE_NAME = "Yahoo Finance"

CRYPTO_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "DOGE-USD"]

dal = DAL()
dal.create_indexes()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def build_source_doc():
    return {
        "source_id": SOURCE_ID,
        "name": SOURCE_NAME,
        "description": "Cryptocurrency market data from Yahoo Finance via yfinance",
        "provider_type": "PYTHON_WRAPPER",
        "base_url": "https://finance.yahoo.com",
        "dataset_or_endpoint": "Ticker.info + Ticker.history(period='1y')",
        "asset_classes_supported": ["crypto"],
        "attributes_supported": ["open", "high", "low", "close", "volume"],
        "system_date": utc_now(),
        "deleted": False
    }


def get_ticker_info_safe(ticker):
    try:
        info = ticker.info
        if isinstance(info, dict):
            return info
    except Exception:
        pass
    return {}


def build_asset_doc(symbol, info):
    return {
        "asset_id": symbol,
        "asset_class": "crypto",
        "symbol": symbol,
        "name": info.get("shortName") or info.get("longName") or symbol,
        "region": info.get("country") or "global",
        "description": info.get("description") or f"Cryptocurrency asset {symbol} from Yahoo Finance",
        "attributes": {
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            "quote_type": info.get("quoteType"),
            "market": info.get("market"),
            "underlying_symbol": symbol.split("-")[0] if "-" in symbol else symbol
        },
        "system_date": utc_now(),
        "deleted": False
    }


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


def save_source_metadata():
    try:
        dal.data_sources.save_version(build_source_doc())
        print(f"Source metadata saved or already present: {SOURCE_ID}")
    except DuplicateKeyError:
        print(f"Source metadata already exists: {SOURCE_ID}")
    except Exception as e:
        print(f"Source metadata error for {SOURCE_ID}: {e}")


def save_asset_metadata(symbol, info):
    try:
        dal.assets.save_version(build_asset_doc(symbol, info))
        print(f"Asset saved or updated: {symbol}")
    except DuplicateKeyError:
        print(f"Asset already exists, continuing with time series: {symbol}")
    except Exception as e:
        print(f"Asset save error for {symbol}: {e}")


def ingest_crypto(symbol, period="1y"):
    print(f"Ingesting {symbol}...")

    ticker = yf.Ticker(symbol)
    info = get_ticker_info_safe(ticker)

    try:
        history = ticker.history(period=period)
    except Exception as e:
        print(f"Failed to fetch history for {symbol}: {e}")
        return

    save_asset_metadata(symbol, info)

    if history is None or history.empty:
        print(f"Skipping time series for {symbol}: no history returned")
        return

    print(f"{symbol}: fetched {len(history)} history rows")

    inserted_count = 0
    skipped_count = 0
    failed_count = 0

    for row_date, row in history.iterrows():
        try:
            new_doc = build_timeseries_doc(symbol, row_date, row, period)

            before_count = dal.time_series.collection.count_documents({
                "asset_id": new_doc["asset_id"],
                "source_id": new_doc["source_id"],
                "business_date": new_doc["business_date"]
            })

            dal.time_series.save_version(new_doc)

            after_count = dal.time_series.collection.count_documents({
                "asset_id": new_doc["asset_id"],
                "source_id": new_doc["source_id"],
                "business_date": new_doc["business_date"]
            })

            if after_count > before_count:
                inserted_count += 1
            else:
                skipped_count += 1

        except DuplicateKeyError:
            skipped_count += 1
        except Exception as e:
            failed_count += 1
            print(f"Time series save error for {symbol} on {row_date}: {e}")

    print(
        f"{symbol}: time_series inserted={inserted_count}, "
        f"skipped={skipped_count}, failed={failed_count}"
    )


def run(period="1y"):
    save_source_metadata()

    for symbol in CRYPTO_SYMBOLS:
        try:
            ingest_crypto(symbol, period=period)
        except Exception as e:
            print(f"Error ingesting {symbol}: {e}")

    total_ts = dal.time_series.collection.count_documents({})
    print(f"Total documents in time_series: {total_ts}")


if __name__ == "__main__":
    run(period="1y")