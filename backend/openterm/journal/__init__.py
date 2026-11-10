"""JRNL: the trade journal. Parsers, FIFO round trips, stats, behaviour diagnostics and the Shadow Account job.

Everything outside `shadow.py` is pure Python (the server imports it; pandas and numpy load only inside the job worker).
The idea (journal import, behaviour diagnostics, a rule-based "shadow" of your own trading) comes from HKUDS/Vibe-Trading
(MIT, see THIRD_PARTY.md); the code here is written fresh for the three brokers OpenTerm supports.
"""
