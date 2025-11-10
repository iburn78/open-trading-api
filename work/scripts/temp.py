###_ agent reconnection: be able to retrieve order manager data 

# order_manager: continuously records and maintains all agent IDs
# operates on a day-to-day basis (no need to reference previous dates, though historical data exists on the server)
# [assumption] order_manager maintains accurate and complete data
# sync logic required:
#   - carefully design synchronization points (pause transaction processing, sync/connect, then resume so both order_manager and agents can process transactions simultaneously)
#   - introduce a lock (global or dedicated; doesn’t have to be global)
#   - wait until no incomplete orders remain, or cancel all incomplete orders (simplifies synchronization)

# cancel all and then reconnect might be the simplest (on reconnect)
# or need to make it a choice
# should be able to pick up exactly where it stands





#####
# viewing the snapshot of an agent
# agant orderbook has to have parse function 