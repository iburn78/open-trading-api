


###_ STOPS after certain stage... of trading... without any error msg
###_ STUCK status might be a real case - in server or client : _lock etc


1) Enable asyncio debug mode

This already tracks lock waits and slow tasks.

PYTHONASYNCIODEBUG=1 python app.py


Or in code:

import asyncio, logging

logging.basicConfig(level=logging.DEBUG)
asyncio.get_event_loop().set_debug(True)


You’ll get warnings like:

Executing <Task ...> took 2.5s
Task blocked waiting for <Lock ...> for 1.2s


CMD: 
set PYTHONASYNCIODEBUG=1




# order 3702 not processed even TR received A1
# order 3700 not processed B1


# for logging: submit -> ... make it easy to track!! 

# CHECK strategy logic: exceeding total cash hinders everything (sth wrong!! )