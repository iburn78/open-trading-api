import asyncio

from core.base.settings import Service
from core.base.logger import LogSetup
from core.comm.server import Server

if __name__ == "__main__":
    service = Service.DEMO
    logger = LogSetup(service).logger
    server = Server(service, logger)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt: 
        logger.info("[Server] stopped by user (Ctrl+C)\n\n")