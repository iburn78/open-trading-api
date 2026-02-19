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

###_ to do 
- make index bar chart
- make key indicators dashboard
- 대차잔고, 공매도 거래대금
- 외국인 주식 보유액 (시장 전체, Sector, 개별)
- CMA 잔고, 예탁금: 증시 대기 자금
- parameter setup: more descriptive
- Moving Average...: 이평선 설계 etc  
- Sync and Initial Value: should be exact, otherwise it is easily misleading
