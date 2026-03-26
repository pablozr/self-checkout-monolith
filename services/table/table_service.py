import asyncpg

from core.logger.logger import logger
from schemas.table import table_from_row


async def get_active_table_by_number(
    conn: asyncpg.Connection, table_number: int
) -> dict:
    try:
        row = await conn.fetchrow(
            """
            SELECT id, number, is_active
            FROM tables
            WHERE number = $1 AND is_active = TRUE
            """,
            table_number,
        )

        if not row:
            return {"status": False, "message": "Table not found or inactive", "data": {}}

        return {
            "status": True,
            "message": "Table retrieved successfully",
            "data": {"table": table_from_row(row)},
        }
    except Exception as e:
        logger.exception(e)
        return {"status": False, "message": "Internal server error", "data": {}}
