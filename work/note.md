## Purpose
To develop a robust stock 'trader', like a well-built organization, where roles and responsibilities are clearly defined.

Key features:
- Encapsulation – clean separation of functionality behind clear interfaces.
- Autonomy – multiple independent agents acting with clear principles like elite human traders.
- Resilience – robust, fail-safe behavior under edge cases.
- Adaptability – flexible strategies driven by principles, open to new ideas.


## To develop
### System
- Disaster recovery (disconnect from the API server - how to reconnect safely)
- State reconciliation - e.g., periodic sync with account and OrderManager/Agent
- Monitoring and alert / system dashboard on health and status
- Configuration management - centralized control/constants/set-up panel
- Performance optimization (e.g., profiling with cProfile(sync), yappi(async))
- Risk management 
- Back-testing framework / random price simulator (may use custom ones)

### AgentManager 
- make it run each agent only once: use local lock file method etc
- manage agents (1. easy to see like EXCEL, 2. more advanced)
- agent manager to use multi cmd/terminal (e.g., multiple thread)
- sync with account
- every day, agent clean-up is required, such as remaining incompleted order / market close handling 
- review over-night behavior of server and agent: technically
    * order_manager records data daily (keeps for multiple days)
    * agent order_book keeps all orders
    * bars (raw_bars and etc) has to be compressed
- assign setting (id, dp, code) checker (e.g., if code is correct, id, and dp are unique)
- link with financial data of the target
- make multi-day (longer terms/overnight logic) data gathering / actions / sync possible 

### Strategy ideas
- SEC vs SEC preferred: check arbitrage opp.
- Foreign follower
- Value / Volatility tracker
- Volume trigger strategy
- PER base valuation 
- Catching slow moving trend (vol / price)


## (###_) Issues / immediate to develop 
- Dashboard webpage refresh, can it be done automatically? 
- displaying key data in the dash board (regarding volume and price etc...)
- on KIS connector reconnect, agent - wise action is necessary (at least subscriptions)
    - agent may need to re-register, while it is recorded as registered, etc. (on reconnection); 
    - resubscription maybe necessary, and make double subscription => do not raise / allow...
    - if subscription is suspended (by KIS server), server may reconnect it (or at least agent shows it)
    ```
    Traceback (most recent call last):
    File "C:\Users\user\projects\optrading\work\core\kis\kis_connect.py", line 345, in run_websocket
        await self._subscriber()
    File "C:\Users\user\projects\optrading\work\core\kis\kis_connect.py", line 213, in _subscriber
        async for raw in self.ws:
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\websockets\asyncio\connection.py", line 242, in __aiter__
        yield await self.recv()
            ^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\websockets\asyncio\connection.py", line 322, in recv
        raise self.protocol.close_exc from self.recv_exc
    websockets.exceptions.ConnectionClosedError: no close frame received or sent
    ```

- handling of the following (seems connection stays): 
    ```
    0212_104840.226 [ERROR] > [url_fetch] request failed: Server disconnected without sending a response.
    Traceback (most recent call last):
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_transports\default.py", line 101, in map_httpcore_exceptions
        yield
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_transports\default.py", line 394, in handle_async_request
        resp = await self._pool.handle_async_request(req)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpcore\_async\connection_pool.py", line 256, in handle_async_request
        raise exc from None
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpcore\_async\connection_pool.py", line 236, in handle_async_request
        response = await connection.handle_async_request(
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpcore\_async\connection.py", line 103, in handle_async_request
        return await self._connection.handle_async_request(request)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpcore\_async\http11.py", line 136, in handle_async_request
        raise exc
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpcore\_async\http11.py", line 106, in handle_async_request
        ) = await self._receive_response_headers(**kwargs)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpcore\_async\http11.py", line 177, in _receive_response_headers
        event = await self._receive_event(timeout=timeout)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpcore\_async\http11.py", line 231, in _receive_event
        raise RemoteProtocolError(msg)
    httpcore.RemoteProtocolError: Server disconnected without sending a response.

    The above exception was the direct cause of the following exception:

    Traceback (most recent call last):
    File "C:\Users\user\projects\optrading\work\core\kis\kis_connect.py", line 142, in url_fetch
        resp = await self.httpx_client.post(
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_client.py", line 1859, in post
        return await self.request(
            ^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_client.py", line 1540, in request
        return await self.send(request, auth=auth, follow_redirects=follow_redirects)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_client.py", line 1629, in send
        response = await self._send_handling_auth(
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_client.py", line 1657, in _send_handling_auth
        response = await self._send_handling_redirects(
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_client.py", line 1694, in _send_handling_redirects
        response = await self._send_single_request(request)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_client.py", line 1730, in _send_single_request
        response = await transport.handle_async_request(request)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_transports\default.py", line 393, in handle_async_request
        with map_httpcore_exceptions():
    File "C:\Users\user\AppData\Local\Programs\Python\Python311\Lib\contextlib.py", line 155, in __exit__
        self.gen.throw(typ, value, traceback)
    File "C:\Users\user\projects\optrading\venv\Lib\site-packages\httpx\_transports\default.py", line 118, in map_httpcore_exceptions
        raise mapped_exc(message) from exc
    httpx.RemoteProtocolError: Server disconnected without sending a response. 
    ```