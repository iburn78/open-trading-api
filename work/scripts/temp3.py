import asyncio
from temp2 import dash_broadcast


async def print():
    await dash_broadcast("some later text")

asyncio.run(print())

