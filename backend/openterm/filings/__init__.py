"""Phase 29 filings functions: FTS (SEC full-text search), MA (deal filings), LEGAL (SEC enforcement + court dockets),
BIO (a reporting owner's Form 3/4/5 filings), RELS (other listed classes of one issuer) and ESG (EPA greenhouse-gas emissions).

Everything in this package is PURE (no network, no FastAPI): parsers and table builders that the providers and `service.py` call, so
tests feed them recorded answers. Nothing here invents a value: a field a source does not give prints as a dash.
"""
