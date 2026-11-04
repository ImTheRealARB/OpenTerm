/** Momentum, volatility, volume and statistics indicators (own pane unless noted). */
import { macd, rsi } from "../indicators";
import { atr, cci, mfi, obv, stoch, willr } from "../studies";
import { type A, cumsum, diff, emaN, hi, lag, linreg, lo, map, nanArr, rmaN, smaN, stdN, sumN, trueRange, wmaN, zip } from "./math";
import { type Category, type IndicatorDef, P } from "./types";

const m = (id: string, name: string, category: Category, plain: string, params: IndicatorDef["params"], outputs: string[], fn: IndicatorDef["fn"], pane: "price" | "lower" = "lower"): IndicatorDef => ({
  id, name, category, pane, params, outputs, plain, fn,
});

const roc = (c: A, n: number): A => zip(c, lag(c, n), (a, b) => (b === 0 ? NaN : (a / b - 1) * 100));

export function stochOf(src: A, n: number): A {
  const h = hi(src, n);
  const l = lo(src, n);
  return zip(src, h, (x, hh, i) => (hh === l[i] ? 50 : (100 * (x - l[i])) / (hh - l[i])));
}

export function ultosc(h: A, l: A, c: A, a = 7, b = 14, d = 28): A {
  const len = c.length;
  const bp = nanArr(len);
  const tr = nanArr(len);
  for (let i = 1; i < len; i++) {
    const lowest = Math.min(l[i], c[i - 1]);
    bp[i] = c[i] - lowest;
    tr[i] = Math.max(h[i], c[i - 1]) - lowest;
  }
  const avg = (n: number) => zip(sumN(bp, n), sumN(tr, n), (x, y) => x / y);
  const a1 = avg(a);
  const a2 = avg(b);
  const a3 = avg(d);
  return map(c, (_, i) => (100 * (4 * a1[i] + 2 * a2[i] + a3[i])) / 7);
}

export function fisher(h: A, l: A, n: number): A[] {
  const len = h.length;
  const fish = nanArr(len);
  const trig = nanArr(len);
  const hl2 = zip(h, l, (a, b) => (a + b) / 2);
  const hh = hi(hl2, n);
  const ll = lo(hl2, n);
  let v = 0;
  let f = 0;
  for (let i = n - 1; i < len; i++) {
    const range = hh[i] - ll[i];
    const x = range === 0 ? 0 : (hl2[i] - ll[i]) / range - 0.5;
    v = Math.max(-0.999, Math.min(0.999, 0.66 * x + 0.67 * v));
    const pf = f;
    f = 0.5 * Math.log((1 + v) / (1 - v)) + 0.5 * f;
    fish[i] = f;
    trig[i] = i === n - 1 ? NaN : pf;
  }
  return [fish, trig];
}

/** Schaff trend cycle: a MACD pushed through two smoothed stochastics so it swings 0..100. */
export function stc(c: A, fast = 23, slow = 50, cycle = 10, factor = 0.5): A {
  const line = zip(emaN(c, fast), emaN(c, slow), (a, b) => a - b);
  const smooth = (src: A): A => {
    const out = nanArr(src.length);
    let prev = NaN;
    for (let i = 0; i < src.length; i++) {
      if (!Number.isFinite(src[i])) continue;
      prev = Number.isFinite(prev) ? prev + factor * (src[i] - prev) : src[i];
      out[i] = prev;
    }
    return out;
  };
  const d1 = smooth(stochOf(line, cycle));
  return smooth(stochOf(d1, cycle));
}

export function connorsRsi(c: A, rsiN = 3, streakN = 2, rankN = 100): A {
  const len = c.length;
  const streak = nanArr(len);
  let s = 0;
  for (let i = 1; i < len; i++) {
    s = c[i] > c[i - 1] ? (s > 0 ? s + 1 : 1) : c[i] < c[i - 1] ? (s < 0 ? s - 1 : -1) : 0;
    streak[i] = s;
  }
  const r1 = rsi(c, rsiN);
  const r2 = rsi(Float64Array.from(streak, (x) => (Number.isFinite(x) ? x : 0)), streakN);
  const ch = roc(c, 1);
  const rank = nanArr(len);
  for (let i = rankN; i < len; i++) {
    let below = 0;
    for (let j = i - rankN; j < i; j++) if (ch[j] < ch[i]) below++;
    rank[i] = (100 * below) / rankN;
  }
  return map(c, (_, i) => (r1[i] + r2[i] + rank[i]) / 3);
}

export function klinger(h: A, l: A, c: A, v: A, fast = 34, slow = 55, sig = 13): A[] {
  const len = c.length;
  const vf = nanArr(len);
  let trend = 0;
  let cm = 0;
  let pdm = 0;
  for (let i = 1; i < len; i++) {
    const dm = h[i] - l[i];
    const t = h[i] + l[i] + c[i] > h[i - 1] + l[i - 1] + c[i - 1] ? 1 : -1;
    cm = i === 1 || t !== trend ? pdm + dm : cm + dm;
    trend = t;
    pdm = dm;
    vf[i] = cm === 0 ? 0 : v[i] * Math.abs(2 * (dm / cm) - 1) * t * 100;
  }
  const kvo = zip(emaN(vf, fast), emaN(vf, slow), (a, b) => a - b);
  return [kvo, emaN(kvo, sig)];
}

const mfv = (h: A, l: A, c: A, v: A): A => map(c, (x, i) => (h[i] === l[i] ? 0 : ((x - l[i] - (h[i] - x)) / (h[i] - l[i])) * v[i]));

export const MOMENTUM: IndicatorDef[] = [
  m("RSI", "Relative Strength Index", "momentum", "Scores recent gains against losses from 0 to 100; above 70 is stretched up, below 30 stretched down.", [P("length", 14)], ["rsi"], (c, p) => [rsi(c.c, p[0])]),
  m("MACD", "MACD", "momentum", "The gap between a fast and slow EMA; when it crosses its signal line momentum is shifting.", [P("fast", 12), P("slow", 26), P("signal", 9)], ["macd", "signal", "hist"], (c, p) => {
    const r = macd(c.c, p[0], p[1], p[2]);
    return [r.line, r.signal, r.hist];
  }),
  m("STOCH", "Stochastic oscillator", "momentum", "Shows where the close sits within the recent high-low range; near 100 is the top, near 0 the bottom.", [P("k", 14), P("d", 3)], ["k", "d"], (c, p) => {
    const r = stoch(c.h, c.l, c.c, p[0], p[1]);
    return [r.k, r.d];
  }),
  m("STOCHRSI", "Stochastic RSI", "momentum", "The stochastic formula applied to RSI; a faster, twitchier overbought/oversold gauge.", [P("rsi length", 14), P("stoch length", 14), P("k", 3), P("d", 3)], ["k", "d"], (c, p) => {
    const k = smaN(stochOf(rsi(c.c, p[0]), p[1]), p[2]);
    return [k, smaN(k, p[3])];
  }),
  m("CCI", "Commodity Channel Index", "momentum", "How far price is from its average in units of typical deviation; beyond +100 or -100 is unusual.", [P("length", 20)], ["cci"], (c, p) => [cci(c.h, c.l, c.c, p[0])]),
  m("WILLR", "Williams %R", "momentum", "Like stochastic but upside down: 0 is the top of the range, -100 the bottom.", [P("length", 14)], ["willr"], (c, p) => [willr(c.h, c.l, c.c, p[0])]),
  m("ROC", "Rate of change", "momentum", "Percent change in price over the last N bars.", [P("length", 12)], ["roc"], (c, p) => [roc(c.c, p[0])]),
  m("ROCR", "Rate of change ratio", "momentum", "Today's close divided by the close N bars ago; 1.0 means unchanged.", [P("length", 10)], ["rocr"], (c, p) => [zip(c.c, lag(c.c, p[0]), (a, b) => a / b)]),
  m("MOM", "Momentum", "momentum", "Price minus price N bars ago, in price units.", [P("length", 10)], ["mom"], (c, p) => [diff(c.c, p[0])]),
  m("TRIX", "TRIX", "momentum", "Percent change of a triple-smoothed EMA; filters out small moves and shows the underlying drive.", [P("length", 15)], ["trix"], (c, p) => {
    const e3 = emaN(emaN(emaN(c.c, p[0]), p[0]), p[0]);
    return [map(e3, (x, i) => (i ? 100 * (x / e3[i - 1] - 1) : NaN))];
  }),
  m("PPO", "Percentage price oscillator", "momentum", "MACD expressed as a percent of the slow EMA, so it compares across different priced stocks.", [P("fast", 12), P("slow", 26), P("signal", 9)], ["ppo", "signal", "hist"], (c, p) => {
    const s = emaN(c.c, p[1]);
    const ppo = zip(emaN(c.c, p[0]), s, (a, b) => (100 * (a - b)) / b);
    const sig = emaN(ppo, p[2]);
    return [ppo, sig, zip(ppo, sig, (a, b) => a - b)];
  }),
  m("APO", "Absolute price oscillator", "momentum", "The fast EMA minus the slow EMA in price units.", [P("fast", 12), P("slow", 26)], ["apo"], (c, p) => [zip(emaN(c.c, p[0]), emaN(c.c, p[1]), (a, b) => a - b)]),
  m("PO", "Price oscillator (SMA)", "momentum", "The percent gap between a fast and a slow simple moving average.", [P("fast", 10), P("slow", 20)], ["po"], (c, p) => [zip(smaN(c.c, p[0]), smaN(c.c, p[1]), (a, b) => (100 * (a - b)) / b)]),
  m("CMO", "Chande momentum oscillator", "momentum", "Net gains minus losses over N bars as a percent of total movement, -100 to 100.", [P("length", 14)], ["cmo"], (c, p) => {
    const d = diff(c.c);
    const up = sumN(map(d, (x) => (x > 0 ? x : 0)).fill(NaN, 0, 1), p[0]);
    const dn = sumN(map(d, (x) => (x < 0 ? -x : 0)).fill(NaN, 0, 1), p[0]);
    return [zip(up, dn, (a, b) => (a + b === 0 ? 0 : (100 * (a - b)) / (a + b)))];
  }),
  m("ULTOSC", "Ultimate oscillator", "momentum", "Blends buying pressure over three time frames to cut false signals; 30 low, 70 high.", [P("short", 7), P("mid", 14), P("long", 28)], ["uo"], (c, p) => [ultosc(c.h, c.l, c.c, p[0], p[1], p[2])]),
  m("AO", "Awesome oscillator", "momentum", "Fast minus slow average of the bar midpoints; shows momentum shifts as a histogram.", [P("fast", 5), P("slow", 34)], ["ao"], (c, p) => {
    const mp = zip(c.h, c.l, (a, b) => (a + b) / 2);
    return [zip(smaN(mp, p[0]), smaN(mp, p[1]), (a, b) => a - b)];
  }),
  m("AC", "Accelerator oscillator", "momentum", "How fast the Awesome oscillator is speeding up or slowing down; an early hint of a turn.", [P("fast", 5), P("slow", 34), P("smooth", 5)], ["ac"], (c, p) => {
    const mp = zip(c.h, c.l, (a, b) => (a + b) / 2);
    const ao = zip(smaN(mp, p[0]), smaN(mp, p[1]), (a, b) => a - b);
    return [zip(ao, smaN(ao, p[2]), (a, b) => a - b)];
  }),
  m("KST", "Know Sure Thing", "momentum", "Adds up smoothed rates of change over four horizons into one long-term momentum line.", [P("signal", 9)], ["kst", "signal"], (c, p) => {
    const part = (r: number, s: number) => smaN(roc(c.c, r), s);
    const a = part(10, 10);
    const b = part(15, 10);
    const d = part(20, 10);
    const e = part(30, 15);
    const kst = map(c.c, (_, i) => a[i] + 2 * b[i] + 3 * d[i] + 4 * e[i]);
    return [kst, smaN(kst, p[0])];
  }),
  m("TSI", "True Strength Index", "momentum", "Double-smoothed momentum scaled to -100..100; crossing zero flips the bias.", [P("long", 25), P("short", 13)], ["tsi"], (c, p) => {
    const d = diff(c.c);
    const num = emaN(emaN(d, p[0]), p[1]);
    const den = emaN(emaN(map(d, Math.abs), p[0]), p[1]);
    return [zip(num, den, (a, b) => (b === 0 ? 0 : (100 * a) / b))];
  }),
  m("COPPOCK", "Coppock curve", "momentum", "A weighted average of two long-term rates of change, made to spot market bottoms.", [P("roc 1", 14), P("roc 2", 11), P("wma", 10)], ["coppock"], (c, p) => [wmaN(zip(roc(c.c, p[0]), roc(c.c, p[1]), (a, b) => a + b), p[2])]),
  m("DPO", "Detrended price oscillator", "momentum", "Price with the trend removed so you can see the cycles around it.", [P("length", 20)], ["dpo"], (c, p) => {
    const s = smaN(c.c, p[0]);
    const k = Math.floor(p[0] / 2) + 1;
    return [map(c.c, (_, i) => (i - k >= 0 ? c.c[i - k] - s[i] : NaN))];
  }),
  m("FISHER", "Fisher transform", "momentum", "Reshapes price so turning points show up as sharp peaks and troughs.", [P("length", 9)], ["fisher", "trigger"], (c, p) => fisher(c.h, c.l, p[0])),
  m("STC", "Schaff trend cycle", "momentum", "A fast MACD-based cycle that swings between 0 and 100; above 75 up, below 25 down.", [P("fast", 23), P("slow", 50), P("cycle", 10)], ["stc"], (c, p) => [stc(c.c, p[0], p[1], p[2])]),
  m("CRSI", "Connors RSI", "momentum", "Averages a short RSI, an up/down streak RSI and a percent rank for mean-reversion signals.", [P("rsi", 3), P("streak", 2), P("rank", 100)], ["crsi"], (c, p) => [connorsRsi(c.c, p[0], p[1], p[2])]),
  m("BOP", "Balance of power", "momentum", "Who closed the bar in control: positive when buyers pushed the close towards the high.", [], ["bop"], (c) => [map(c.c, (x, i) => (c.h[i] === c.l[i] ? 0 : (x - c.o[i]) / (c.h[i] - c.l[i])))]),
  m("ELDER", "Elder Ray", "momentum", "Bull power (high minus EMA) and bear power (low minus EMA) show who is stronger.", [P("length", 13)], ["bull", "bear"], (c, p) => {
    const e = emaN(c.c, p[0]);
    return [zip(c.h, e, (a, b) => a - b), zip(c.l, e, (a, b) => a - b)];
  }),
  m("RVIG", "Relative Vigor Index", "momentum", "Compares where the bar closes with its range, since closes follow opens in uptrends.", [P("length", 10)], ["rvi", "signal"], (c, p) => {
    const sw = (a: A) => map(a, (_, i) => (i >= 3 ? (a[i] + 2 * a[i - 1] + 2 * a[i - 2] + a[i - 3]) / 6 : NaN));
    const num = sw(zip(c.c, c.o, (a, b) => a - b));
    const den = sw(zip(c.h, c.l, (a, b) => a - b));
    const rvi = zip(smaN(num, p[0]), smaN(den, p[0]), (a, b) => a / b);
    return [rvi, sw(rvi)];
  }),
  m("PRANK", "Percent rank", "momentum", "The share of the last N closes that were lower than today's.", [P("length", 100)], ["rank"], (c, p) => {
    const out = nanArr(c.c.length);
    for (let i = p[0]; i < c.c.length; i++) {
      let b = 0;
      for (let j = i - p[0]; j < i; j++) if (c.c[j] < c.c[i]) b++;
      out[i] = (100 * b) / p[0];
    }
    return [out];
  }, "lower"),
  m("ZSCORE", "Z-score", "other", "How many standard deviations the close is from its average; beyond 2 is unusual.", [P("length", 20)], ["z"], (c, p) => {
    const s = smaN(c.c, p[0]);
    const d = stdN(c.c, p[0]);
    return [map(c.c, (x, i) => (d[i] === 0 ? 0 : (x - s[i]) / d[i]))];
  }),
  m("AUTOCORR", "Autocorrelation", "other", "How closely price follows its own past: near 1 trending smoothly, near 0 random.", [P("length", 20), P("lag", 1)], ["corr"], (c, p) => {
    const n = p[0];
    const y = lag(c.c, p[1]);
    const out = nanArr(c.c.length);
    for (let i = n - 1 + p[1]; i < c.c.length; i++) {
      let sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
      for (let j = i - n + 1; j <= i; j++) {
        sx += c.c[j]; sy += y[j]; sxx += c.c[j] ** 2; syy += y[j] ** 2; sxy += c.c[j] * y[j];
      }
      const den = Math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy));
      out[i] = den === 0 ? 0 : (n * sxy - sx * sy) / den;
    }
    return [out];
  }),
];

export const VOLATILITY: IndicatorDef[] = [
  m("ATR", "Average True Range", "volatility", "The typical size of a bar's move including gaps; bigger means a wilder market.", [P("length", 14)], ["atr"], (c, p) => [atr(c.h, c.l, c.c, p[0])]),
  m("NATR", "Normalized ATR", "volatility", "ATR as a percent of the close so you can compare volatility between stocks.", [P("length", 14)], ["natr"], (c, p) => [zip(atr(c.h, c.l, c.c, p[0]), c.c, (a, b) => (100 * a) / b)]),
  m("TR", "True range", "volatility", "The full range of a single bar including any gap from the previous close.", [], ["tr"], (c) => [trueRange(c.h, c.l, c.c)]),
  m("RANGE", "Bar range", "volatility", "High minus low for each bar.", [], ["range"], (c) => [zip(c.h, c.l, (a, b) => a - b)]),
  m("STDEV", "Standard deviation", "volatility", "How widely closes are spread around their average over N bars.", [P("length", 20)], ["stdev"], (c, p) => [stdN(c.c, p[0])]),
  m("VAR", "Variance", "volatility", "The standard deviation squared; the raw measure of price dispersion.", [P("length", 20)], ["var"], (c, p) => [map(stdN(c.c, p[0]), (x) => x * x)]),
  m("HV", "Historical volatility", "volatility", "Annualised standard deviation of daily log returns, in percent.", [P("length", 20), P("periods per year", 252, 1, 100000)], ["hv"], (c, p) => {
    const lr = map(c.c, (x, i) => (i ? Math.log(x / c.c[i - 1]) : NaN));
    const out = nanArr(c.c.length);
    const n = p[0];
    for (let i = n; i < c.c.length; i++) {
      let s = 0;
      for (let j = i - n + 1; j <= i; j++) s += lr[j];
      const mu = s / n;
      let ss = 0;
      for (let j = i - n + 1; j <= i; j++) ss += (lr[j] - mu) ** 2;
      out[i] = Math.sqrt(ss / (n - 1 || 1)) * Math.sqrt(p[1]) * 100;
    }
    return [out];
  }),
  m("BBPB", "Bollinger %B", "volatility", "Where price sits inside the Bollinger Bands: 1 at the top band, 0 at the bottom.", [P("length", 20), { name: "mult", default: 2, min: 0.1, max: 10 }], ["pb"], (c, p) => {
    const mid = smaN(c.c, p[0]);
    const sd = stdN(c.c, p[0]);
    return [map(c.c, (x, i) => (sd[i] === 0 ? 0.5 : (x - (mid[i] - p[1] * sd[i])) / (2 * p[1] * sd[i])))];
  }),
  m("BBW", "Bollinger bandwidth", "volatility", "The width of the Bollinger Bands as a percent of the middle; a squeeze often comes before a big move.", [P("length", 20), { name: "mult", default: 2, min: 0.1, max: 10 }], ["bw"], (c, p) => {
    const mid = smaN(c.c, p[0]);
    const sd = stdN(c.c, p[0]);
    return [map(c.c, (_, i) => (100 * 2 * p[1] * sd[i]) / mid[i])];
  }),
  m("DONCHW", "Donchian width", "volatility", "The distance between the highest high and lowest low of the last N bars.", [P("length", 20)], ["width"], (c, p) => [zip(hi(c.h, p[0]), lo(c.l, p[0]), (a, b) => a - b)]),
  m("ULCER", "Ulcer index", "volatility", "Measures how deep and how long price has been below its recent peak; downside-only risk.", [P("length", 14)], ["ulcer"], (c, p) => {
    const mx = hi(c.c, p[0]);
    const r2 = map(c.c, (x, i) => (100 * (x - mx[i])) ** 2 / (mx[i] * mx[i]));
    return [map(smaN(r2.fill(NaN, 0, p[0] - 1), p[0]), Math.sqrt)];
  }),
  m("RVIV", "Relative Volatility Index", "volatility", "RSI-style gauge that uses the standard deviation of price instead of the change itself.", [P("stdev", 10), P("smooth", 14)], ["rvi"], (c, p) => {
    const sd = stdN(c.c, p[0]);
    const up = map(sd, (x, i) => (i && c.c[i] > c.c[i - 1] ? x : 0)).fill(NaN, 0, p[0]);
    const dn = map(sd, (x, i) => (i && c.c[i] < c.c[i - 1] ? x : 0)).fill(NaN, 0, p[0]);
    return [zip(emaN(up, p[1]), emaN(dn, p[1]), (a, b) => (a + b === 0 ? 50 : (100 * a) / (a + b)))];
  }),
  m("CHOP", "Choppiness index", "volatility", "Near 100 the market is moving sideways, near 0 it is trending hard.", [P("length", 14)], ["chop"], (c, p) => {
    const st = sumN(trueRange(c.h, c.l, c.c), p[0]);
    const hh = hi(c.h, p[0]);
    const ll = lo(c.l, p[0]);
    return [map(c.c, (_, i) => (hh[i] === ll[i] ? NaN : (100 * Math.log10(st[i] / (hh[i] - ll[i]))) / Math.log10(p[0])))];
  }),
  m("MASS", "Mass index", "volatility", "Adds up the widening of the high-low range to warn of a reversal; a bulge above 27 then a drop is the signal.", [P("ema", 9), P("sum", 25)], ["mass"], (c, p) => {
    const r = zip(c.h, c.l, (a, b) => a - b);
    const e1 = emaN(r, p[0]);
    return [sumN(zip(e1, emaN(e1, p[0]), (a, b) => a / b), p[1])];
  }),
];

export const VOLUME: IndicatorDef[] = [
  m("OBV", "On-balance volume", "volume", "A running total that adds volume on up days and subtracts it on down days.", [], ["obv"], (c) => [obv(c.c, c.v)]),
  m("MFI", "Money Flow Index", "volume", "Volume-weighted RSI from 0 to 100; above 80 is overbought, below 20 oversold.", [P("length", 14)], ["mfi"], (c, p) => [mfi(c.h, c.l, c.c, c.v, p[0])]),
  m("ADL", "Accumulation/distribution line", "volume", "Running total of volume weighted by where each bar closed in its range; rising means buying.", [], ["adl"], (c) => [cumsum(mfv(c.h, c.l, c.c, c.v))]),
  m("CMF", "Chaikin money flow", "volume", "Buying versus selling pressure over N bars, -1 to 1; above zero means buyers dominate.", [P("length", 20)], ["cmf"], (c, p) => [zip(sumN(mfv(c.h, c.l, c.c, c.v), p[0]), sumN(c.v, p[0]), (a, b) => (b === 0 ? 0 : a / b))]),
  m("CHAIKINOSC", "Chaikin oscillator", "volume", "The MACD of the accumulation/distribution line; shows momentum in money flow.", [P("fast", 3), P("slow", 10)], ["cho"], (c, p) => {
    const adl = cumsum(mfv(c.h, c.l, c.c, c.v));
    return [zip(emaN(adl, p[0]), emaN(adl, p[1]), (a, b) => a - b)];
  }),
  m("FORCE", "Force index", "volume", "Price change times volume, smoothed; big positive values mean strong buying.", [P("length", 13)], ["force"], (c, p) => [emaN(zip(diff(c.c), c.v, (a, b) => a * b), p[0])]),
  m("EOM", "Ease of movement", "volume", "Shows how easily price moves per unit of volume; high values mean price rises on light volume.", [P("length", 14)], ["eom"], (c, p) => {
    const raw = map(c.c, (_, i) => {
      if (!i) return NaN;
      const dm = (c.h[i] + c.l[i]) / 2 - (c.h[i - 1] + c.l[i - 1]) / 2;
      const rg = c.h[i] - c.l[i];
      return rg === 0 || c.v[i] === 0 ? 0 : dm / (c.v[i] / 1e6 / rg);
    });
    return [smaN(raw, p[0])];
  }),
  m("NVI", "Negative volume index", "volume", "Only moves on days when volume fell, tracking what the quiet 'smart money' does.", [], ["nvi"], (c) => {
    const out = nanArr(c.c.length);
    let x = 1000;
    for (let i = 0; i < c.c.length; i++) {
      if (i && c.v[i] < c.v[i - 1]) x *= c.c[i] / c.c[i - 1];
      out[i] = x;
    }
    return [out];
  }),
  m("PVI", "Positive volume index", "volume", "Only moves on days when volume rose, tracking what the crowd does.", [], ["pvi"], (c) => {
    const out = nanArr(c.c.length);
    let x = 1000;
    for (let i = 0; i < c.c.length; i++) {
      if (i && c.v[i] > c.v[i - 1]) x *= c.c[i] / c.c[i - 1];
      out[i] = x;
    }
    return [out];
  }),
  m("PVT", "Price-volume trend", "volume", "A running total of volume scaled by the percent price change.", [], ["pvt"], (c) => [cumsum(map(c.c, (x, i) => (i ? ((x - c.c[i - 1]) / c.c[i - 1]) * c.v[i] : NaN)))]),
  m("KLINGER", "Klinger oscillator", "volume", "Compares volume flow with price trend over long and short spans to find turning points.", [P("fast", 34), P("slow", 55), P("signal", 13)], ["kvo", "signal"], (c, p) => klinger(c.h, c.l, c.c, c.v, p[0], p[1], p[2])),
  m("WAD", "Williams accumulation/distribution", "volume", "A running total of how far each close moved beyond the prior range; confirms or contradicts the trend.", [], ["wad"], (c) => {
    const d = map(c.c, (x, i) => {
      if (!i) return NaN;
      const pc = c.c[i - 1];
      if (x > pc) return x - Math.min(c.l[i], pc);
      if (x < pc) return x - Math.max(c.h[i], pc);
      return 0;
    });
    return [cumsum(d)];
  }),
  m("VOLSMA", "Volume average", "volume", "The average volume of the last N bars; tells you if today is busy or quiet.", [P("length", 20)], ["vol"], (c, p) => [smaN(c.v, p[0])]),
  m("VROC", "Volume rate of change", "volume", "Percent change in volume compared with N bars ago.", [P("length", 14)], ["vroc"], (c, p) => [roc(c.v, p[0])]),
  m("CLV", "Close location value", "volume", "Where the bar closed in its range: +1 at the high, -1 at the low.", [], ["clv"], (c) => [map(c.c, (x, i) => (c.h[i] === c.l[i] ? 0 : (x - c.l[i] - (c.h[i] - x)) / (c.h[i] - c.l[i])))]),
  m("LRANGLE", "Linear regression angle", "other", "The slope of the best-fit line turned into degrees; steeper means a faster trend.", [P("length", 25)], ["angle"], (c, p) => [map(linreg(c.c, p[0]).slope, (s) => (Math.atan(s) * 180) / Math.PI)]),
  m("CLOSEVSSMA", "Close vs SMA", "other", "Close minus its simple moving average; positive means price is above the average.", [P("length", 20)], ["diff"], (c, p) => [zip(c.c, smaN(c.c, p[0]), (a, b) => a - b)]),
  m("RMA_RANGE", "Average range (Wilder)", "volatility", "Wilder-smoothed high-low range, a simpler cousin of ATR that ignores gaps.", [P("length", 14)], ["arange"], (c, p) => [rmaN(zip(c.h, c.l, (a, b) => a - b), p[0])]),
];
