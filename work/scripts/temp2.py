import asyncio
import websockets

dash_clients = set()

async def dash_handler(ws):
    dash_clients.add(ws)
    try:
        await ws.wait_closed()
    finally:
        dash_clients.remove(ws)

async def start_dash_server(port=8001):
    async with websockets.serve(dash_handler, "0.0.0.0", port):
        await asyncio.Future()  # run forever

async def dash_broadcast(text: str):
    for ws in set(dash_clients):
        try:
            await ws.send(text)
        except:
            dash_clients.remove(ws)


async def main():
    # Start server in background
    asyncio.create_task(start_dash_server())

    print('here')
    # Wait a bit so server starts
    await asyncio.sleep(5)
    print('there')
    # Wait a bit so server starts

    # Broadcast something
    await dash_broadcast("some text here....")

    # Keep running so clients can connect
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())