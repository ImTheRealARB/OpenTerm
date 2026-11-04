/**
 * Plain-English glossary for the GUI (pure data: no React, no imports).
 *
 * One short line per term, written for someone who knows what a stock is but not the jargon.
 * Keys are UPPER CASE; elements carry `data-term="<KEY>"` and `glossaryTip.ts` shows the line on hover and keyboard focus.
 * Loaded lazily (dynamic import) the first time a term is hovered or focused, so it costs nothing at startup.
 */
export const GLOSSARY: Readonly<Record<string, string>> = {
  "P/E": "Price-to-earnings ratio: the share price divided by the company's earnings per share over the last 12 months. A higher number means investors pay more for each dollar of profit.",
  "FORWARD P/E": "Price divided by the earnings per share analysts expect over the next 12 months.",
  "EPS": "Earnings per share: the company's profit after costs and tax, divided by its number of shares. It is the profit that belongs to one share.",
  "FORWARD EPS": "The earnings per share analysts expect for the next 12 months. It is a forecast, not a result.",
  "MARKET CAP": "Market capitalisation: the share price times the number of shares. It is what the whole company is worth on the stock market today.",
  "ENTERPRISE VALUE": "Market cap plus the company's debt minus its cash: roughly what it would cost to buy the whole business.",
  "DIVIDEND YIELD": "The yearly dividend (cash paid to shareholders) as a percent of the share price. 2% means $2 a year for every $100 invested.",
  "BETA": "How much the stock tends to move compared with the whole market. 1 moves with the market, above 1 moves more, below 1 moves less.",
  "P/B": "Price-to-book ratio: the share price divided by the company's net assets (what it owns minus what it owes) per share.",
  "P/S": "Price-to-sales ratio: the company's market cap divided by its yearly revenue (the money it takes in from selling things).",
  "EV/EBITDA": "Enterprise value divided by EBITDA (profit before interest, tax and write-offs). A way to compare companies with different debt levels; lower often means cheaper.",
  "ROE": "Return on equity: yearly profit divided by shareholders' money in the company. It shows how well the company turns your money into profit.",
  "ROA": "Return on assets: yearly profit divided by everything the company owns.",
  "MARGIN": "The share of each dollar of sales the company keeps as profit. A 20% margin means 20 cents of profit per dollar sold.",
  "52-WEEK RANGE": "The lowest and highest price of the last 52 weeks (one year). The marker shows where today's price sits between them.",
  "DAY RANGE": "The lowest and highest price so far today.",
  "VOLUME": "How many shares were traded today. High volume means lots of buying and selling.",
  "AVG VOLUME": "The usual number of shares traded per day, averaged over recent weeks. Compare it with today's volume to spot unusual activity.",
  "SHARES OUTSTANDING": "The total number of shares the company has issued and that investors hold.",
  "FLOAT": "The shares that are free to trade by the public (not held by insiders or the company itself).",
  "OHLC": "Open, High, Low, Close: the four prices of each chart bar. Where the period started, its highest and lowest points, and where it ended.",
  "OPEN": "The first price traded in the period (the day's first trade, for a daily bar).",
  "HIGH": "The highest price reached during the period.",
  "LOW": "The lowest price reached during the period.",
  "CLOSE": "The last price traded in the period. For a daily bar it is the end-of-day price.",
  "ADJUSTED CLOSE": "The closing price corrected for dividends and stock splits, so old prices can be fairly compared with new ones.",
  "CHANGE": "How much the price moved since the previous close, in money and in percent.",
  "BID": "The highest price a buyer is offering right now. If you sell immediately, this is what you get.",
  "ASK": "The lowest price a seller is asking right now. If you buy immediately, this is what you pay.",
  "SPREAD": "The gap between the bid and the ask. A small spread means it is cheap to trade in and out.",
  "DRAWDOWN": "How far a price or portfolio has fallen from its highest point, in percent. The maximum drawdown is the worst such fall.",
  "SHARPE": "Sharpe ratio: return earned per unit of ups-and-downs (risk). Higher is better; above 1 is generally considered good.",
  "SORTINO": "Like the Sharpe ratio, but it only counts the downward swings as risk, so big gains are not punished.",
  "CAGR": "Compound annual growth rate: the steady yearly percent growth that would turn the starting value into the ending value.",
  "VOLATILITY": "How much the price jumps around, shown as a yearly percent. Higher means a bumpier ride.",
  "YIELD": "The yearly income an investment pays as a percent of its price (interest on a bond, dividends on a stock).",
  "DURATION": "How sensitive a bond's price is to interest rates, in years. A duration of 5 means roughly a 5% price drop if rates rise 1 point.",
};

/** The line for a term (case-insensitive), or null when we have none. */
export function explain(term: string): string | null {
  return GLOSSARY[term.trim().toUpperCase()] ?? null;
}
