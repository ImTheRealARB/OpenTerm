/**
 * Names people type that the US stock list (the "screener universe") cannot answer: indices, commodities, crypto, currencies,
 * nicknames ("google", "coke") and the big Indian companies. Pure data plus two tiny lookups; no React, no network.
 *
 * WHY A TABLE: "gold" must mean the gold price (GC=F), not Barrick Gold; "nasdaq" must mean the index, not Nasdaq Inc.;
 * "reliance" must mean Reliance Industries on the NSE, not Reliance Steel. A company-name search cannot know that, so these
 * words are decided up front. A phrase found here wins over the company list (see nlIndex.ts `resolvePhrase`).
 *
 * SYMBOLS follow what the app already uses (functions/boards.ts, the WEI / FX / CMDTY / CRYP boards), so a chart opened from
 * plain English is the same series the boards show: Yahoo style (`^GSPC`, `GC=F`, `BTC-USD`, `EURUSD=X`, `RELIANCE.NS`).
 *
 * KEYS are lower case, apostrophes removed, other punctuation turned into one space ("aliasKey" below). Add a name = add a
 * string to one of the lists; nothing else needs to change. Indian companies are on the NSE (`.NS`) because the owner is in
 * Bengaluru and Kite (the Indian data source) serves NSE first; the `label` says so on screen.
 */

import { editDistance } from "../gui/companySearch";

export interface Alias {
  /** Yahoo-style symbol to open. */
  symbol: string;
  /** Plain name shown in the "understood as" text, e.g. "Reliance Industries on NSE". */
  label: string;
}

/** Lower-case, apostrophes dropped, anything that is not a letter, digit or & becomes one space: "S&P 500" -> "s&p 500". */
export const aliasKey = (s: string): string =>
  s.toLowerCase().replace(/[’']/g, "").replace(/[^a-z0-9&]+/g, " ").replace(/\s+/g, " ").trim();

/** [names, symbol, label]. Longer names win automatically because callers try the longest word run first. */
const TABLE: [string[], string, string][] = [
  // ---- indices (same symbols as the WEI board) ----
  [["s&p 500", "s&p500", "sp500", "sp 500", "s and p 500", "s p 500", "snp 500", "standard and poors 500", "spx", "s&p", "the s&p"], "^GSPC", "S&P 500 index"],
  [["nasdaq", "nasdaq composite", "nasdaq index", "ixic", "the nasdaq"], "^IXIC", "Nasdaq Composite index"],
  [["nasdaq 100", "nasdaq100", "ndx"], "^NDX", "Nasdaq 100 index"],
  [["dow jones", "dow", "the dow", "dow jones industrial average", "dow jones industrials", "djia", "dji"], "^DJI", "Dow Jones Industrial Average"],
  [["russell 2000", "russell2000", "rut"], "^RUT", "Russell 2000 index"],
  [["vix", "volatility index", "fear index"], "^VIX", "CBOE Volatility Index"],
  [["dollar index", "dxy", "us dollar index"], "DX-Y.NYB", "US Dollar Index"],
  [["ftse 100", "ftse", "footsie"], "^FTSE", "FTSE 100 index"],
  [["dax", "dax 40", "dax 30"], "^GDAXI", "DAX index"],
  [["cac 40", "cac"], "^FCHI", "CAC 40 index"],
  [["euro stoxx 50", "eurostoxx 50", "euro stoxx"], "^STOXX50E", "Euro Stoxx 50 index"],
  [["nikkei", "nikkei 225"], "^N225", "Nikkei 225 index"],
  [["hang seng"], "^HSI", "Hang Seng index"],
  [["kospi"], "^KS11", "KOSPI index"],
  [["shanghai composite", "sse composite"], "000001.SS", "SSE Composite index"],
  [["asx 200", "asx200"], "^AXJO", "S&P/ASX 200 index"],
  [["tsx", "s&p tsx"], "^GSPTSE", "S&P/TSX Composite index"],
  [["bovespa", "ibovespa"], "^BVSP", "Ibovespa index"],
  [["nifty 50", "nifty50", "nifty", "nse nifty", "nse index"], "^NSEI", "Nifty 50 index"],
  [["bank nifty", "banknifty", "nifty bank"], "^NSEBANK", "Nifty Bank index"],
  [["sensex", "bse sensex", "bse"], "^BSESN", "BSE Sensex index"],

  // ---- commodities (futures, same symbols as the CMDTY board) ----
  [["gold", "gold price", "gold futures", "xauusd"], "GC=F", "Gold futures"],
  [["silver", "silver price", "silver futures"], "SI=F", "Silver futures"],
  [["oil", "crude", "crude oil", "oil price", "wti", "wti crude", "wti oil", "us oil"], "CL=F", "WTI crude oil futures"],
  [["brent", "brent crude", "brent oil"], "BZ=F", "Brent crude oil futures"],
  [["natural gas", "nat gas", "natgas", "gas price"], "NG=F", "Natural gas futures"],
  [["copper", "copper price"], "HG=F", "Copper futures"],
  [["platinum"], "PL=F", "Platinum futures"],
  [["palladium"], "PA=F", "Palladium futures"],

  // ---- crypto (USD pairs) ----
  [["bitcoin", "btc", "bitcoin price"], "BTC-USD", "Bitcoin in USD"],
  [["ethereum", "ether", "eth", "ethereum price"], "ETH-USD", "Ethereum in USD"],
  [["solana", "sol"], "SOL-USD", "Solana in USD"],
  [["dogecoin", "doge"], "DOGE-USD", "Dogecoin in USD"],
  [["ripple", "xrp"], "XRP-USD", "XRP in USD"],

  // ---- nicknames and old names for US companies ----
  [["google", "alphabet", "alphabet inc", "alphabet class a"], "GOOGL", "Alphabet (Google), class A"],
  [["alphabet class c", "google class c"], "GOOG", "Alphabet (Google), class C"],
  [["facebook", "meta", "meta platforms"], "META", "Meta Platforms (Facebook)"],
  [["coke", "coca cola", "coca cola company", "the coca cola company"], "KO", "Coca-Cola Company"],
  [["pepsi", "pepsico"], "PEP", "PepsiCo"],
  [["jpmorgan", "jp morgan", "jpmorgan chase", "jp morgan chase"], "JPM", "JPMorgan Chase"],
  [["berkshire", "berkshire hathaway", "berkshire b"], "BRK-B", "Berkshire Hathaway, class B"],
  [["berkshire a", "berkshire hathaway a", "berkshire class a", "berkshire hathaway class a"], "BRK-A", "Berkshire Hathaway, class A"],
  [["mcdonalds", "mc donalds", "mcdonald"], "MCD", "McDonald's"],
  [["3m", "3m company"], "MMM", "3M Company"],
  [["general electric", "ge aerospace"], "GE", "GE Aerospace (General Electric)"],
  [["at&t", "att"], "T", "AT&T"],
  [["p&g", "procter and gamble", "procter & gamble", "procter gamble"], "PG", "Procter & Gamble"],
  [["j&j", "johnson and johnson", "johnson & johnson"], "JNJ", "Johnson & Johnson"],
  [["tsmc", "taiwan semiconductor"], "TSM", "Taiwan Semiconductor (ADR)"],
  [["disney", "walt disney"], "DIS", "Walt Disney"],

  // ---- Indian large caps on the NSE ----
  [["reliance", "reliance industries", "ril"], "RELIANCE.NS", "Reliance Industries on NSE"],
  [["tcs", "tata consultancy", "tata consultancy services"], "TCS.NS", "Tata Consultancy Services on NSE"],
  [["hdfc bank", "hdfcbank", "hdfc"], "HDFCBANK.NS", "HDFC Bank on NSE"],
  [["infosys", "infy"], "INFY.NS", "Infosys on NSE"],
  [["icici bank", "icici"], "ICICIBANK.NS", "ICICI Bank on NSE"],
  [["bharti airtel", "airtel"], "BHARTIARTL.NS", "Bharti Airtel on NSE"],
  [["itc", "itc limited"], "ITC.NS", "ITC on NSE"],
  [["sbi", "state bank of india", "state bank"], "SBIN.NS", "State Bank of India on NSE"],
  [["hul", "hindustan unilever"], "HINDUNILVR.NS", "Hindustan Unilever on NSE"],
  [["l&t", "larsen and toubro", "larsen & toubro", "larsen toubro"], "LT.NS", "Larsen & Toubro on NSE"],
  [["bajaj finance"], "BAJFINANCE.NS", "Bajaj Finance on NSE"],
  [["bajaj finserv"], "BAJAJFINSV.NS", "Bajaj Finserv on NSE"],
  [["bajaj auto"], "BAJAJ-AUTO.NS", "Bajaj Auto on NSE"],
  [["hcl tech", "hcl technologies", "hcl"], "HCLTECH.NS", "HCL Technologies on NSE"],
  [["kotak", "kotak bank", "kotak mahindra", "kotak mahindra bank"], "KOTAKBANK.NS", "Kotak Mahindra Bank on NSE"],
  [["axis bank"], "AXISBANK.NS", "Axis Bank on NSE"],
  [["maruti", "maruti suzuki"], "MARUTI.NS", "Maruti Suzuki on NSE"],
  [["mahindra", "m&m", "mahindra and mahindra", "mahindra & mahindra"], "M&M.NS", "Mahindra & Mahindra on NSE"],
  [["sun pharma", "sun pharmaceutical"], "SUNPHARMA.NS", "Sun Pharma on NSE"],
  [["titan company"], "TITAN.NS", "Titan on NSE"],
  [["asian paints"], "ASIANPAINT.NS", "Asian Paints on NSE"],
  [["ultratech", "ultratech cement"], "ULTRACEMCO.NS", "UltraTech Cement on NSE"],
  [["nestle india"], "NESTLEIND.NS", "Nestle India on NSE"],
  [["wipro"], "WIPRO.NS", "Wipro on NSE"],
  [["tech mahindra"], "TECHM.NS", "Tech Mahindra on NSE"],
  [["power grid", "powergrid"], "POWERGRID.NS", "Power Grid on NSE"],
  [["ntpc"], "NTPC.NS", "NTPC on NSE"],
  [["ongc"], "ONGC.NS", "ONGC on NSE"],
  [["coal india"], "COALINDIA.NS", "Coal India on NSE"],
  // Tata Motors demerged in Oct 2025: TATAMOTORS.NS no longer quotes (Yahoo: no data; checked 2026-11-05). Yahoo's name search now
  // gives two NSE companies, both still named "Tata Motors": "Tata Motors Limited" (TMCV, trucks and buses, listed 2025-11-12) and
  // "Tata Motors Passenger Vehicles Limited" (TMPV, cars and Jaguar Land Rover; it kept the old share-price history).
  // An alias holds ONE symbol, so a "which one?" list is not possible here. Plain "tata motors" opens the company whose legal
  // name is exactly that (TMCV; it was also the larger by market cap that day), the label says which one it is, and TMPV has its own names.
  [["tata motors", "tata motors commercial", "tata motors commercial vehicles", "tata motors cv", "tmcv"], "TMCV.NS", "Tata Motors (commercial vehicles) on NSE"],
  [["tata motors passenger", "tata motors passenger vehicles", "tata motors pv", "tata motors cars", "tmpv"], "TMPV.NS", "Tata Motors Passenger Vehicles on NSE"],
  [["tata steel"], "TATASTEEL.NS", "Tata Steel on NSE"],
  [["tata power"], "TATAPOWER.NS", "Tata Power on NSE"],
  [["jsw steel"], "JSWSTEEL.NS", "JSW Steel on NSE"],
  [["adani enterprises"], "ADANIENT.NS", "Adani Enterprises on NSE"],
  [["adani ports"], "ADANIPORTS.NS", "Adani Ports on NSE"],
  [["hindalco"], "HINDALCO.NS", "Hindalco on NSE"],
  [["dr reddys", "dr reddy", "dr reddys laboratories"], "DRREDDY.NS", "Dr. Reddy's Laboratories on NSE"],
  [["cipla"], "CIPLA.NS", "Cipla on NSE"],
  [["eicher motors", "eicher", "royal enfield"], "EICHERMOT.NS", "Eicher Motors on NSE"],
  [["hero motocorp", "hero moto"], "HEROMOTOCO.NS", "Hero MotoCorp on NSE"],
  [["britannia"], "BRITANNIA.NS", "Britannia on NSE"],
  [["indusind bank", "indusind"], "INDUSINDBK.NS", "IndusInd Bank on NSE"],
  [["apollo hospitals"], "APOLLOHOSP.NS", "Apollo Hospitals on NSE"],
  [["grasim"], "GRASIM.NS", "Grasim on NSE"],
  [["vedanta"], "VEDL.NS", "Vedanta on NSE"],
  [["indian oil", "ioc"], "IOC.NS", "Indian Oil on NSE"],
  [["bharat electronics"], "BEL.NS", "Bharat Electronics on NSE"],
  [["tata consumer", "tata consumer products"], "TATACONSUM.NS", "Tata Consumer Products on NSE"],
];

/** Phrase -> alias, built once. A name listed twice keeps its first entry. */
const BY_NAME = new Map<string, Alias>();
for (const [names, symbol, label] of TABLE) {
  for (const n of names) {
    const k = aliasKey(n);
    if (!BY_NAME.has(k)) BY_NAME.set(k, { symbol, label });
  }
}

/**
 * Aliases whose single-word name is one or two letters away from `word` ("googel" -> google, "bitcon" -> bitcoin), best first, one
 * per symbol. Only words of 5+ letters, and never an exact match (that is a normal lookup).
 */
export function closestAliases(word: string, limit = 3): Alias[] {
  if (word.length < 5 || !/^[a-z]+$/.test(word)) return [];
  const max = word.length >= 7 ? 2 : 1;
  const found: { a: Alias; d: number }[] = [];
  for (const [key, a] of BY_NAME) {
    if (key === word || !/^[a-z]{5,}$/.test(key)) continue;
    const d = editDistance(word, key, max);
    if (d <= max && !found.some((f) => f.a.symbol === a.symbol)) found.push({ a, d });
  }
  return found.sort((x, y) => x.d - y.d).slice(0, limit).map((f) => f.a);
}

/** The longest alias phrase has this many words (lets callers skip runs that are too long to be an alias). */
export const MAX_ALIAS_WORDS = Math.max(...[...BY_NAME.keys()].map((k) => k.split(" ").length));

/** Exact alias for a word run, or null. */
export const lookupAlias = (run: string): Alias | null => BY_NAME.get(aliasKey(run)) ?? null;

// ---------------------------------------------------------------------------------------------------------------------
// Currencies: "eur usd", "usdinr", "dollar rupee", "pound to dollar", "rupee" -> Yahoo `XXXYYY=X`.
// ---------------------------------------------------------------------------------------------------------------------

/** Any two of these ISO 4217 codes make a pair ("eur sek" -> EURSEK=X). Yahoo quotes most crosses; a rare dead pair shows its own error. */
const ISO = new Set(
  ("usd eur gbp jpy chf cad aud nzd cny cnh hkd sgd inr krw twd thb myr idr php vnd aed sar qar kwd bhd omr ils try zar egp ngn " +
    "kes mxn brl ars clp cop pen sek nok dkk pln czk huf ron rub uah isk").split(" "),
);

/** Words people use for a currency -> ISO code. */
const CCY_WORDS: Record<string, string> = {
  dollar: "USD", dollars: "USD", buck: "USD", bucks: "USD", greenback: "USD", usd: "USD",
  rupee: "INR", rupees: "INR", inr: "INR",
  euro: "EUR", euros: "EUR",
  pound: "GBP", pounds: "GBP", sterling: "GBP", quid: "GBP",
  yen: "JPY",
  franc: "CHF", "swiss franc": "CHF",
  yuan: "CNY", renminbi: "CNY", rmb: "CNY",
  "canadian dollar": "CAD", loonie: "CAD",
  "australian dollar": "AUD", aussie: "AUD",
  "new zealand dollar": "NZD", kiwi: "NZD",
  "hong kong dollar": "HKD", "singapore dollar": "SGD",
  dirham: "AED", won: "KRW", ringgit: "MYR", baht: "THB", rand: "ZAR", peso: "MXN", lira: "TRY",
  krona: "SEK", krone: "NOK", rouble: "RUB", ruble: "RUB", riyal: "SAR",
};

/** Words that may sit between the two currencies ("dollar to rupee", "usd vs inr"). */
const PAIR_GLUE = new Set(["to", "vs", "versus", "against", "in", "per", "and", "/", "x"]);

/** Currency words that may stand alone ("rupee chart"); the others only make sense inside a pair. */
const SINGLE_OK = new Set("rupee rupees inr euro euros eur yen jpy yuan renminbi cny sterling gbp".split(" "));

const ccyOf = (w: string): string | null => {
  const word = CCY_WORDS[w];
  if (word) return word;
  return ISO.has(w) ? w.toUpperCase() : null;
};

/** Reads the words as one currency name ("hong kong dollar" is three words); returns [code, wordsUsed] or null. */
function readCcy(words: string[], at: number): [string, number] | null {
  for (let n = Math.min(3, words.length - at); n >= 1; n--) {
    const code = ccyOf(words.slice(at, at + n).join(" "));
    if (code) return [code, n];
  }
  return null;
}

/**
 * A currency pair from a whole phrase: "eur usd", "eurusd", "eur/usd", "dollar rupee", "usd to inr", "rupee dollar".
 * Null when the phrase is not exactly a pair (so "usd stock" is not one). One currency word alone ("rupee", "euro", "yen") is
 * read the way markets quote it against the dollar (USDINR, EURUSD, USDJPY).
 */
export function fxPair(run: string): Alias | null {
  const key = aliasKey(run.replace(/[/\-]/g, " "));
  if (!key) return null;
  let words = key.split(" ");
  // "eurusd" / "usdinr": one token made of two ISO codes.
  if (words.length === 1 && /^[a-z]{6}$/.test(words[0])) {
    const a = words[0].slice(0, 3);
    const b = words[0].slice(3);
    if (ISO.has(a) && ISO.has(b) && a !== b) words = [a, b];
  }
  const first = readCcy(words, 0);
  if (!first) return null;
  const [a, used] = first;
  let at = used;
  if (at < words.length && PAIR_GLUE.has(words[at])) at++;
  if (at === words.length) {
    // A single currency: the usual dollar quote. Only unambiguous words ("won" and "rand" are also plain English).
    if (a === "USD" || at !== used || !SINGLE_OK.has(words.slice(0, used).join(" "))) return null;
    const base = new Set(["EUR", "GBP", "AUD", "NZD"]).has(a);
    const [x, y] = base ? [a, "USD"] : ["USD", a];
    return { symbol: `${x}${y}=X`, label: `${x}/${y} exchange rate` };
  }
  const second = readCcy(words, at);
  if (!second || at + second[1] !== words.length) return null;
  const b = second[0];
  if (a === b) return null;
  return { symbol: `${a}${b}=X`, label: `${a}/${b} exchange rate` };
}
