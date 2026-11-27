from __future__ import annotations

import asyncio
import threading

import pytest

from api.blocking import run_blocking


def test_cancellation_waits_until_blocking_work_finishes():
    async def exercise():
        entered = asyncio.Event()
        released = threading.Event()
        loop = asyncio.get_running_loop()

        def work():
            loop.call_soon_threadsafe(entered.set)
            assert released.wait(timeout=5)
            return 1

        task = asyncio.create_task(run_blocking(work))
        await asyncio.wait_for(entered.wait(), timeout=2)
        try:
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            released.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(exercise())
