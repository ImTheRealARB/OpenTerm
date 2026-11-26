"""Phase 27 scanner: check a list of symbols against a BT rule (`SCAN SPX RSI14<30 AND CLOSE>SMA200`), index movers (MRR)
and scheduled scans. The rule grammar and its maths are the backtester's (`bt/rules.py`): one rule reader for BT, SCAN and
indicator alerts. Bars are fetched by the server (paced for Yahoo by `barfetch.fetch_bars`); the rule is evaluated in a job
worker (`scan.run`), because pandas never loads in the server process.
"""
