from typing import TypedDict

import asyncpg


class TableData(TypedDict):
    tableId: int
    tableNumber: int
    isActive: bool


def table_from_row(row: asyncpg.Record) -> TableData:
    return {
        "tableId": row["id"],
        "tableNumber": row["number"],
        "isActive": row["is_active"],
    }
