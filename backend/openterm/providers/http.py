"""Constants several provider adapters share: the browser-style User-Agent and the Yahoo hosts.

They live here, not in yahoo.py, so a news, crypto or futures adapter does not depend on the Yahoo adapter just to send a header.
"""

# Sent as the User-Agent by every keyless adapter that talks to a public website API (Yahoo, Nasdaq, Binance, RSS feeds).
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
# Yahoo Finance hosts: chart/spark/quoteSummary on query1, search on query2.
BASE = "https://query1.finance.yahoo.com"
SEARCH_BASE = "https://query2.finance.yahoo.com"
