import asyncio

from app.core.config import settings
from app.core.db import execute_schema_bootstrap, open_connection
from app.core.logging import configure_logging, log_event
from app.monitoring import monitor_loop


async def main() -> None:
    configure_logging()
    execute_schema_bootstrap()
    log_event("worker.started", worker="monitor", interval_seconds=settings.monitor_interval_seconds)
    await monitor_loop(open_connection, settings.monitor_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
