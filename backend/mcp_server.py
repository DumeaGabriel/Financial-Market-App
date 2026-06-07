"""
Financial Data Warehouse - MCP Server
======================================
Exposes the Financial DWH REST API as MCP tools for Claude Desktop (and other MCP clients).
All tools are read-only and call the existing FastAPI consumption layer.

Usage:
    pip install mcp httpx python-dotenv
    python mcp_server.py

Environment variables (set in shell, .env file, or Claude Desktop config):
    DWH_API_BASE_URL        FastAPI base URL (default: http://localhost:8000)
    DWH_MAX_LIMIT           Hard cap on page size (default: 100)
    DWH_MAX_DATE_RANGE_DAYS Max date range for time-series queries (default: 365)
    DWH_DEFAULT_LIMIT       Default page size (default: 20)
    DWH_EARLIEST_DATE       Earliest accepted date, YYYY-MM-DD (default: 2000-01-01)

Claude Desktop config (claude_desktop_config.json):
    {
        "mcpServers": {
            "financial-dwh": {
                "command": "python",
                "args": ["mcp_server.py"],
                "env": {
                    "DWH_API_BASE_URL": "http://localhost:8000"
                }
            }
        }
    }
"""

import json
import os
import re
from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

# Load .env file if present (requires python-dotenv; silently skipped if not installed)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration — all values overridable via environment variables
# ---------------------------------------------------------------------------

API_BASE_URL        = os.getenv("DWH_API_BASE_URL",        "http://localhost:8000")
MAX_LIMIT           = int(os.getenv("DWH_MAX_LIMIT",           "100"))
MAX_DATE_RANGE_DAYS = int(os.getenv("DWH_MAX_DATE_RANGE_DAYS", "365"))
DEFAULT_LIMIT       = int(os.getenv("DWH_DEFAULT_LIMIT",       "20"))
DEFAULT_OFFSET      = 0

_EARLIEST_DATE_STR  = os.getenv("DWH_EARLIEST_DATE", "2000-01-01")
EARLIEST_DATE       = datetime.strptime(_EARLIEST_DATE_STR, "%Y-%m-%d").date()
# Allow predictions up to 2 years in the future; adjust via DWH_MAX_DATE_RANGE_DAYS if needed
LATEST_DATE         = date.today() + timedelta(days=365 * 2)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_date(value: str, field_name: str) -> date:
    """
    Parse and validate a YYYY-MM-DD date string.

    Checks:
    - Format matches YYYY-MM-DD
    - Is a real calendar date (no Feb 30, etc.)
    - Falls within [EARLIEST_DATE, LATEST_DATE]
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"'{field_name}' must be in YYYY-MM-DD format, got: '{value}'")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"'{field_name}' is not a valid calendar date: '{value}'")
    if parsed < EARLIEST_DATE:
        raise ValueError(
            f"'{field_name}' ({value}) is before the earliest accepted date ({EARLIEST_DATE}). "
            "Check for typos (e.g. wrong century)."
        )
    if parsed > LATEST_DATE:
        raise ValueError(
            f"'{field_name}' ({value}) is too far in the future (max accepted: {LATEST_DATE})."
        )
    return parsed


def _validate_date_range(start_str: str, end_str: str) -> tuple[date, date]:
    """
    Validate a pair of YYYY-MM-DD date strings as a half-open range [start, end).

    Raises ValueError if either date is invalid, end <= start, or the range
    exceeds MAX_DATE_RANGE_DAYS.
    """
    start_date = _validate_date(start_str, "startBusinessDate")
    end_date   = _validate_date(end_str,   "endBusinessDate")
    if end_date <= start_date:
        raise ValueError(
            f"'endBusinessDate' ({end_str}) must be after 'startBusinessDate' ({start_str}). "
            "Note: the range is half-open [start, end)."
        )
    delta = (end_date - start_date).days
    if delta > MAX_DATE_RANGE_DAYS:
        raise ValueError(
            f"Date range too large: {delta} days requested, maximum allowed is "
            f"{MAX_DATE_RANGE_DAYS} days. Please narrow your range and paginate if needed."
        )
    return start_date, end_date


def _validate_month_range(
    start_year: Optional[int],
    start_month: Optional[int],
    end_year: Optional[int],
    end_month: Optional[int],
) -> None:
    """
    Validate that a year/month range is logically ordered.
    Only checked when both endpoints are fully specified.
    """
    if start_year is not None and end_year is not None:
        s = (start_year, start_month if start_month is not None else 1)
        e = (end_year,   end_month   if end_month   is not None else 12)
        if e < s:
            raise ValueError(
                f"End period ({end_year}-{end_month or 12:02d}) must not precede "
                f"start period ({start_year}-{start_month or 1:02d})."
            )


def _validate_pagination(offset: Any, limit: Any) -> tuple[int, int]:
    """Validate and clamp pagination parameters."""
    try:
        offset = int(offset)
        limit  = int(limit)
    except (TypeError, ValueError):
        raise ValueError("'offset' and 'limit' must be integers.")
    if offset < 0:
        raise ValueError("'offset' must be >= 0.")
    if limit < 1:
        raise ValueError("'limit' must be >= 1.")
    if limit > MAX_LIMIT:
        raise ValueError(f"'limit' must be <= {MAX_LIMIT}. Requested: {limit}.")
    return offset, limit


def _error(message: str) -> list[types.TextContent]:
    """Return a structured error response."""
    payload = {"error": True, "message": message}
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]


def _ok(data: Any) -> list[types.TextContent]:
    """Return a structured success response."""
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


async def _get(path: str, params: Optional[Dict] = None) -> Any:
    """
    Perform an async GET against the FastAPI backend using httpx streaming.

    Using client.stream() releases the socket as soon as headers arrive and
    reads the body incrementally, which avoids blocking on large responses.
    A 60-second timeout is used (vs 30 previously) to accommodate larger payloads.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("GET", f"{API_BASE_URL}{path}", params=params) as response:
            # Read body incrementally so the socket is not held open unnecessarily
            body = await response.aread()
            if response.status_code == 404:
                try:
                    detail = json.loads(body).get("detail", "Resource not found.")
                except Exception:
                    detail = "Resource not found."
                raise LookupError(detail)
            if response.status_code != 200:
                try:
                    detail = json.loads(body).get("detail", body.decode())
                except Exception:
                    detail = body.decode()
                raise RuntimeError(f"Backend returned HTTP {response.status_code}: {detail}")
            return json.loads(body)

# ---------------------------------------------------------------------------
# MCP Server setup
# ---------------------------------------------------------------------------

server = Server("financial-dwh")

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_assets",
            description=(
                "Returns a paginated list of asset identifiers available in the financial "
                "data warehouse. Use this tool first to discover which assets exist before "
                "fetching details or time-series data. "
                "Inputs: offset (default 0), limit (default 20, max 100). "
                "Output: { items: [...], offset, limit, count }."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "offset": {
                        "type": "integer",
                        "description": "Number of items to skip (for pagination). Default: 0.",
                        "default": DEFAULT_OFFSET,
                        "minimum": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Number of items to return. Default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}.",
                        "default": DEFAULT_LIMIT,
                        "minimum": 1,
                        "maximum": MAX_LIMIT,
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="get_asset_details",
            description=(
                "Returns the latest known details for a single asset identified by assetId. "
                "The result reflects the most recent version of the asset record stored in the warehouse. "
                "Use list_assets first if you do not know the assetId. "
                "Inputs: assetId (required). "
                "Output: asset entity object with all available fields."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assetId": {
                        "type": "string",
                        "description": "The unique identifier of the asset (e.g. 'AAPL', 'BTC-USD').",
                        "minLength": 1,
                    },
                },
                "required": ["assetId"],
            },
        ),

        types.Tool(
            name="list_data_sources",
            description=(
                "Returns a paginated list of data source identifiers available in the warehouse. "
                "A data source represents the origin of time-series records (e.g. a market feed). "
                "Use this tool to discover which sources exist before querying time-series data. "
                "Inputs: offset (default 0), limit (default 20, max 100). "
                "Output: { items: [...], offset, limit, count }."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "offset": {
                        "type": "integer",
                        "description": "Number of items to skip (for pagination). Default: 0.",
                        "default": DEFAULT_OFFSET,
                        "minimum": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Number of items to return. Default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}.",
                        "default": DEFAULT_LIMIT,
                        "minimum": 1,
                        "maximum": MAX_LIMIT,
                    },
                },
                "required": [],
            },
        ),

        types.Tool(
            name="get_data_source_details",
            description=(
                "Returns the latest known details for a single data source identified by dataSourceId. "
                "The result reflects the most recent version of the source record stored in the warehouse. "
                "Use list_data_sources first if you do not know the dataSourceId. "
                "Inputs: dataSourceId (required). "
                "Output: data source entity object with all available fields."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dataSourceId": {
                        "type": "string",
                        "description": "The unique identifier of the data source.",
                        "minLength": 1,
                    },
                },
                "required": ["dataSourceId"],
            },
        ),

        types.Tool(
            name="get_time_series_data",
            description=(
                "Returns daily OHLCV time-series records for a specific asset and data source "
                "within a bounded date range. Only the latest version of each business date is returned. "
                "Records are ordered newest-first. "
                "The date range [startBusinessDate, endBusinessDate) is half-open (start inclusive, end exclusive). "
                f"Maximum allowed range: {MAX_DATE_RANGE_DAYS} days. Requests exceeding this will be rejected. "
                f"Dates must be between {EARLIEST_DATE} and approximately {LATEST_DATE}. "
                "Inputs: assetId, dataSourceId, startBusinessDate (YYYY-MM-DD), endBusinessDate (YYYY-MM-DD), "
                "includeAttributes (optional bool, default false). "
                "Output: { data: { assetId, dataSourceId, records: [...] }, attributes? }."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assetId": {
                        "type": "string",
                        "description": "The unique identifier of the asset.",
                        "minLength": 1,
                    },
                    "dataSourceId": {
                        "type": "string",
                        "description": "The unique identifier of the data source.",
                        "minLength": 1,
                    },
                    "startBusinessDate": {
                        "type": "string",
                        "description": f"Start of the date range, inclusive. Format: YYYY-MM-DD. Min: {EARLIEST_DATE}.",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "endBusinessDate": {
                        "type": "string",
                        "description": "End of the date range, exclusive. Format: YYYY-MM-DD.",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "includeAttributes": {
                        "type": "boolean",
                        "description": "If true, includes the list of attribute keys found across all records. Default: false.",
                        "default": False,
                    },
                },
                "required": ["assetId", "dataSourceId", "startBusinessDate", "endBusinessDate"],
            },
        ),

        types.Tool(
            name="get_monthly_analytics",
            description=(
                "Returns pre-computed monthly analytics summaries from the warehouse. "
                "Each record contains aggregated metrics for a given asset/source/year/month combination: "
                "avg open, avg close, min low, max high, total volume, avg volume, and monthly return %. "
                "Filter by assetId, dataSourceId, symbol, assetClass, and/or a year-month range. "
                "When providing a range, endYear/endMonth must not precede startYear/startMonth. "
                "Inputs: all optional filters + offset/limit for pagination. "
                "Output: { items: [...], offset, limit, count }."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assetId":      {"type": "string",  "description": "Filter by asset identifier."},
                    "dataSourceId": {"type": "string",  "description": "Filter by data source identifier."},
                    "symbol":       {"type": "string",  "description": "Filter by ticker symbol (e.g. 'AAPL')."},
                    "assetClass":   {"type": "string",  "description": "Filter by asset class (e.g. 'stock', 'crypto')."},
                    "startYear":    {"type": "integer", "description": "Start year (inclusive)."},
                    "startMonth":   {"type": "integer", "description": "Start month 1-12 (inclusive).", "minimum": 1, "maximum": 12},
                    "endYear":      {"type": "integer", "description": "End year (inclusive)."},
                    "endMonth":     {"type": "integer", "description": "End month 1-12 (inclusive).", "minimum": 1, "maximum": 12},
                    "offset":       {"type": "integer", "description": "Pagination offset. Default: 0.", "default": 0, "minimum": 0},
                    "limit":        {"type": "integer", "description": f"Page size. Default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}.", "default": DEFAULT_LIMIT, "minimum": 1, "maximum": MAX_LIMIT},
                },
                "required": [],
            },
        ),

        types.Tool(
            name="get_predictions",
            description=(
                "Returns ML price predictions stored in the warehouse. "
                "Predictions are produced by a linear regression model trained per asset/source pair. "
                "Each record contains actual_open, predicted_open, close, low, high, model_type, and generated_at. "
                "Filter by assetId, dataSourceId, modelType, and/or a business date range. "
                f"Dates must be in YYYY-MM-DD format and between {EARLIEST_DATE} and approximately {LATEST_DATE}. "
                "Inputs: all optional filters + offset/limit for pagination. "
                "Output: { items: [...], offset, limit, count }. "
                "Do not use predictions as financial advice; they reflect model output only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "assetId":           {"type": "string", "description": "Filter by asset identifier."},
                    "dataSourceId":      {"type": "string", "description": "Filter by data source identifier."},
                    "modelType":         {"type": "string", "description": "Filter by model type (e.g. 'linear_regression_per_asset')."},
                    "startBusinessDate": {"type": "string", "description": f"Start date inclusive. Format: YYYY-MM-DD. Min: {EARLIEST_DATE}.", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "endBusinessDate":   {"type": "string", "description": "End date exclusive. Format: YYYY-MM-DD.", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "offset":            {"type": "integer", "description": "Pagination offset. Default: 0.", "default": 0, "minimum": 0},
                    "limit":             {"type": "integer", "description": f"Page size. Default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}.", "default": DEFAULT_LIMIT, "minimum": 1, "maximum": MAX_LIMIT},
                },
                "required": [],
            },
        ),
    ]

# ---------------------------------------------------------------------------
# Tool call handlers
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> list[types.TextContent]:

    # -----------------------------------------------------------------------
    # list_assets
    # -----------------------------------------------------------------------
    if name == "list_assets":
        try:
            offset, limit = _validate_pagination(
                arguments.get("offset", DEFAULT_OFFSET),
                arguments.get("limit", DEFAULT_LIMIT),
            )
            data = await _get("/api/v1/assets", params={"offset": offset, "limit": limit})
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": "/api/v1/assets",
                "semantics": "latest non-deleted version per asset",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)
        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except (LookupError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error(f"Cannot reach the Financial DWH API. Make sure the FastAPI server is running on {API_BASE_URL}")

    # -----------------------------------------------------------------------
    # get_asset_details
    # -----------------------------------------------------------------------
    elif name == "get_asset_details":
        try:
            asset_id = arguments.get("assetId", "").strip()
            if not asset_id:
                return _error("Invalid input: 'assetId' is required and must not be empty.")
            data = await _get(f"/api/v1/assets/{asset_id}")
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": f"/api/v1/assets/{asset_id}",
                "assetId": asset_id,
                "semantics": "latest non-deleted version of the asset record",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)
        except LookupError as e:
            return _error(f"Asset not found: {e}")
        except (ValueError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error(f"Cannot reach the Financial DWH API. Make sure the FastAPI server is running on {API_BASE_URL}")

    # -----------------------------------------------------------------------
    # list_data_sources
    # -----------------------------------------------------------------------
    elif name == "list_data_sources":
        try:
            offset, limit = _validate_pagination(
                arguments.get("offset", DEFAULT_OFFSET),
                arguments.get("limit", DEFAULT_LIMIT),
            )
            data = await _get("/api/v1/data-sources", params={"offset": offset, "limit": limit})
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": "/api/v1/data-sources",
                "semantics": "latest non-deleted version per data source",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)
        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except (LookupError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error(f"Cannot reach the Financial DWH API. Make sure the FastAPI server is running on {API_BASE_URL}")

    # -----------------------------------------------------------------------
    # get_data_source_details
    # -----------------------------------------------------------------------
    elif name == "get_data_source_details":
        try:
            source_id = arguments.get("dataSourceId", "").strip()
            if not source_id:
                return _error("Invalid input: 'dataSourceId' is required and must not be empty.")
            data = await _get(f"/api/v1/data-sources/{source_id}")
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint": f"/api/v1/data-sources/{source_id}",
                "dataSourceId": source_id,
                "semantics": "latest non-deleted version of the data source record",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)
        except LookupError as e:
            return _error(f"Data source not found: {e}")
        except (ValueError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error(f"Cannot reach the Financial DWH API. Make sure the FastAPI server is running on {API_BASE_URL}")

    # -----------------------------------------------------------------------
    # get_time_series_data
    # -----------------------------------------------------------------------
    elif name == "get_time_series_data":
        try:
            asset_id     = arguments.get("assetId", "").strip()
            source_id    = arguments.get("dataSourceId", "").strip()
            start_str    = arguments.get("startBusinessDate", "").strip()
            end_str      = arguments.get("endBusinessDate", "").strip()
            include_attrs = bool(arguments.get("includeAttributes", False))

            if not asset_id:
                return _error("Invalid input: 'assetId' is required.")
            if not source_id:
                return _error("Invalid input: 'dataSourceId' is required.")
            if not start_str:
                return _error("Invalid input: 'startBusinessDate' is required.")
            if not end_str:
                return _error("Invalid input: 'endBusinessDate' is required.")

            # Unified date-range validation (format, calendar, bounds, ordering, max span)
            _validate_date_range(start_str, end_str)

            data = await _get("/api/v1/data", params={
                "assetId":           asset_id,
                "dataSourceId":      source_id,
                "startBusinessDate": start_str,
                "endBusinessDate":   end_str,
                "includeAttributes": str(include_attrs).lower(),
            })

            data["_provenance"] = {
                "assetId":           asset_id,
                "dataSourceId":      source_id,
                "startBusinessDate": start_str,
                "endBusinessDate":   end_str,
                "semantics": "half-open interval [startBusinessDate, endBusinessDate), latest version per business date, ordered newest-first",
            }
            return _ok(data)

        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except LookupError as e:
            return _error(f"Not found: {e}")
        except RuntimeError as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error(f"Cannot reach the Financial DWH API. Make sure the FastAPI server is running on {API_BASE_URL}")

    # -----------------------------------------------------------------------
    # get_monthly_analytics
    # -----------------------------------------------------------------------
    elif name == "get_monthly_analytics":
        try:
            offset, limit = _validate_pagination(
                arguments.get("offset", DEFAULT_OFFSET),
                arguments.get("limit", DEFAULT_LIMIT),
            )

            params: Dict[str, Any] = {"offset": offset, "limit": limit}

            if arguments.get("assetId"):
                params["assetId"]      = arguments["assetId"].strip()
            if arguments.get("dataSourceId"):
                params["dataSourceId"] = arguments["dataSourceId"].strip()
            if arguments.get("symbol"):
                params["symbol"]       = arguments["symbol"].strip()
            if arguments.get("assetClass"):
                params["assetClass"]   = arguments["assetClass"].strip()

            start_year  = int(arguments["startYear"])  if arguments.get("startYear")  is not None else None
            start_month = int(arguments["startMonth"]) if arguments.get("startMonth") is not None else None
            end_year    = int(arguments["endYear"])    if arguments.get("endYear")    is not None else None
            end_month   = int(arguments["endMonth"])   if arguments.get("endMonth")   is not None else None

            # Validate month/year range ordering
            _validate_month_range(start_year, start_month, end_year, end_month)

            if start_year  is not None: params["startYear"]  = start_year
            if start_month is not None: params["startMonth"] = start_month
            if end_year    is not None: params["endYear"]    = end_year
            if end_month   is not None: params["endMonth"]   = end_month

            data = await _get("/api/v1/analytics/monthly", params=params)
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint":  "/api/v1/analytics/monthly",
                "filters":   {k: v for k, v in params.items() if k not in ("offset", "limit")},
                "semantics": "pre-computed monthly aggregations from warehouse time-series data",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)

        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except (LookupError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error(f"Cannot reach the Financial DWH API. Make sure the FastAPI server is running on {API_BASE_URL}")

    # -----------------------------------------------------------------------
    # get_predictions
    # -----------------------------------------------------------------------
    elif name == "get_predictions":
        try:
            offset, limit = _validate_pagination(
                arguments.get("offset", DEFAULT_OFFSET),
                arguments.get("limit", DEFAULT_LIMIT),
            )

            params: Dict[str, Any] = {"offset": offset, "limit": limit}

            if arguments.get("assetId"):
                params["assetId"]      = arguments["assetId"].strip()
            if arguments.get("dataSourceId"):
                params["dataSourceId"] = arguments["dataSourceId"].strip()
            if arguments.get("modelType"):
                params["modelType"]    = arguments["modelType"].strip()

            start_str = arguments.get("startBusinessDate", "").strip()
            end_str   = arguments.get("endBusinessDate",   "").strip()

            if start_str and end_str:
                # Both provided — full range validation (format, bounds, ordering, span)
                _validate_date_range(start_str, end_str)
                params["startBusinessDate"] = start_str
                params["endBusinessDate"]   = end_str
            elif start_str:
                _validate_date(start_str, "startBusinessDate")
                params["startBusinessDate"] = start_str
            elif end_str:
                _validate_date(end_str, "endBusinessDate")
                params["endBusinessDate"] = end_str

            data = await _get("/api/v1/analytics/predictions", params=params)
            data["_disclaimer"] = "Predictions are model output only and do not constitute financial advice."
            data["_provenance"] = {
                "warehouse": "financial-dwh",
                "endpoint":  "/api/v1/analytics/predictions",
                "filters":   {k: v for k, v in params.items() if k not in ("offset", "limit")},
                "semantics": "ML model predictions stored in warehouse, not real-time inference",
                "retrievedAt": datetime.utcnow().isoformat() + "Z",
            }
            return _ok(data)

        except ValueError as e:
            return _error(f"Invalid input: {e}")
        except (LookupError, RuntimeError) as e:
            return _error(str(e))
        except httpx.ConnectError:
            return _error(f"Cannot reach the Financial DWH API. Make sure the FastAPI server is running on {API_BASE_URL}")

    # -----------------------------------------------------------------------
    # Unknown tool
    # -----------------------------------------------------------------------
    else:
        return _error(f"Unknown tool: '{name}'.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())