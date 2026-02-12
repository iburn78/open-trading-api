## Market information
- Every orders that are not processed is cancelled over night (KRX, NXT)

## KIS information
- 모의투자 has some limitations: e.g., price < 1000 does not go through.
- Revise is basically the same as cancel and then re-order

## Design notes
- let's use "###(underbar_)" to mark places that need attention / fix / develop
- Race conditions could occur when getting responses from API server: e.g., 1) direct response of the command, 2) websocket response 
- Cancelled order is only progressed up to order.processed quantity
- Each agent has a client instance (one to one)

## Tips
- Update windows terminal from old CMD to windows terminal and use this: winget install --id Microsoft.WindowsTerminal -e 