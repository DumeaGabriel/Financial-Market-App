from backend.DataBase.db import (
    create_indexes,
    list_assets,
    get_asset,
    list_sources,
    get_source,
    get_time_series,
    get_latest_version
)

create_indexes()

print("ASSETS:")
print(list_assets())

print("\nONE ASSET:")
print(get_asset("AAPL"))

print("\nSOURCES:")
print(list_sources())

print("\nONE SOURCE:")
print(get_source("alpha_vantage_daily"))

print("\nTIME SERIES:")
print(get_time_series("AAPL", "alpha_vantage_daily"))

print("\nLATEST VERSION:")
print(get_latest_version("AAPL", "alpha_vantage_daily", "2024-03-11"))