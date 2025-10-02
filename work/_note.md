# Goal

To develop a robust stock 'trader' using the KIS Open API for Korean public stocks
First, focus on building an MVP (minimum viable product)

# Architecture

## KIS System
- Operated by KIS (the API provider)
- Contains account info
- Provides both REST API and a Websocket API (for real-time stock price data)

## Trader Components 
### Account Manager
- Data: a Dataframe containing asset information
    - stock code (or code)
    - number of shares
    - average purchase price
    - available cash total
- Functions: 
    - loader: loads account data from KIS
    - checker: verifies that the current data matches the data in KIS 
        - should be run after each trading action or whenever data changes occur
        - Raises an alert if a mismatch found

### Trade Target Manager(TTM)
- Data1: a Dataframe containing trade targets
    - list of codes to trade
    - target return as percentage for a specific target
    - target purchase price for a specific target
    - max allowed capital allocation for a specific target
- Data2: a Dataframe containing current progress data achieving the target in Data1
    - number of shares purchased
    - capital used
    - average purchase price
    - current return rate
    - absolute return amount
- Functions:
    - loader: load Data1 from a certain external sources (to be developed independently)
    - updater: update Data2 after any trade action or periodic price update

### Trade Executor
- Functions
    - Buy:
    - Sell: 
    - Cancel buy: 
    - Cancel sell: 
    - Cancel all:
    - Stop trading:
    - Checker: check if any action performed as intended
    - Updater: update TTM after each action above

### Monitor
- Functions:
    - Visualize data and progress

### Guide book 
- Wikidocs
    - https://wikidocs.net/book/7847

---

### Notes: 
- Every orders that are not processed is cancelled over night
- 모의투자 has some limitations: e.g., price < 1000 does not go through.
- Race conditions could occur when getting responses from API server: e.g., 1) direct response of the command, 2) websocket response 
- Revise is basically the same as cancel and then re-order
- Cancelled order is only progressed up to order.processed quantity

