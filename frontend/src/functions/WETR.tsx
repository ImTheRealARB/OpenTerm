/**
 * WETR: weather for commodity decisions. `WETR` = the demand-city basket (7-day heating / cooling degree days, F-days, base 65 F, equal-weighted);
 * `WETR <place | lat,lon>` = that place's 7-day forecast (Open-Meteo), plus NWS alerts for US points when SEC_USER_AGENT names a contact.
 * Keys: B basket / place, E CSV, F5 refresh.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, worldApi, type Envelope, type WetrPayload, type WxBasketRow, type WxDay } from "../net/api";
import { alertColor, alertLine, fmtDd, fmtTemp, placeArg } from "./energyArgs";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const DAY_COLUMNS: Column<WxDay>[] = [
  { title: "DATE", width: 11, text: (r) => r.date, color: () => "acc" },
  { title: "MAX", width: 7, align: "right", text: (r) => fmtTemp(r.tmax) },
  { title: "MIN", width: 7, align: "right", text: (r) => fmtTemp(r.tmin) },
  { title: "MEAN", width: 7, align: "right", text: (r) => fmtTemp(r.tmean) },
  { title: "HDD", width: 7, align: "right", text: (r) => fmtDd(r.hdd) },
  { title: "CDD", width: 7, align: "right", text: (r) => fmtDd(r.cdd) },
  { title: "RAIN MM", width: 8, align: "right", text: (r) => (r.precip == null ? "" : r.precip.toFixed(1)) },
  { title: "WIND KM/H", width: 10, align: "right", text: (r) => (r.wind == null ? "" : r.wind.toFixed(0)) },
  { title: "SKY", width: 26, text: (r) => r.sky ?? "", color: () => "dim" },
];
const BASKET_COLUMNS: Column<WxBasketRow>[] = [
  { title: "CITY", width: 14, text: (r) => r.city.toUpperCase(), color: () => "acc" },
  { title: "HDD 7D", width: 8, align: "right", text: (r) => fmtDd(r.hdd) },
  { title: "CDD 7D", width: 8, align: "right", text: (r) => fmtDd(r.cdd) },
  { title: "MEAN", width: 7, align: "right", text: (r) => fmtTemp(r.tmean) },
  { title: "HIGH", width: 7, align: "right", text: (r) => fmtTemp(r.tmax) },
  { title: "LOW", width: 7, align: "right", text: (r) => fmtTemp(r.tmin) },
  { title: "DAYS", width: 5, align: "right", text: (r) => String(r.days), color: (r) => (r.days < 7 ? "warn" : "dim") },
];

export default function WETR({ panelId, args }: FunctionProps) {
  const place = useMemo(() => placeArg(args), [args]);
  const [env, setEnv] = useState<Envelope<WetrPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [basketView, setBasketView] = useState(!place);
  const grid = useRef<GridHandle>(null);

  const load = useCallback(
    (fresh: boolean) => {
      setLoading(true);
      return worldApi
        .wetr(place, fresh)
        .then((e) => {
          setEnv(e);
          setError(null);
        })
        .catch((e: ApiError) => {
          setEnv(null);
          setError(e);
        })
        .finally(() => setLoading(false));
    },
    [place],
  );
  useEffect(() => {
    setBasketView(!place);
    void load(false);
  }, [place, load]);

  const d = env?.data;
  const days = useMemo(() => d?.forecast?.days ?? [], [d]);
  const basket = useMemo(() => d?.basket.rows ?? [], [d]);
  const showBasket = basketView || !d?.forecast;
  const latest = useLatest({ n: showBasket ? basket.length : days.length });
  useCsvExport(panelId, () => (d ? (showBasket ? gridCsv("WETR_BASKET", BASKET_COLUMNS, basket) : gridCsv("WETR_" + (d.place?.name ?? "PLACE").replace(/\W+/g, "_"), DAY_COLUMNS, days)) : null));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        if (navKey(e, grid.current, latest.current.n)) return true;
        if (e.key === "F5") {
          void load(true);
          return true;
        }
        if (e.key === "b" || e.key === "B") {
          setBasketView((v) => !v);
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const alerts = d?.alerts;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">WETR</span> {showBasket ? "DEMAND-CITY BASKET · 7-DAY DEGREE DAYS" : `${(d?.place?.name ?? place).toUpperCase()} · 7-DAY FORECAST`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {d?.forecast ? "B BASKET / PLACE · " : ""}E CSV · F5 REFRESH</span>
      </div>
      {d && (
        <div className="dim">
          {d.note} FORECAST MODEL OUTPUT, NOT AN OBSERVATION.
          {showBasket && ` BASKET: ${d.basket.weighting}.`}
        </div>
      )}
      {d && showBasket && d.basket.average && (
        <div className="line">
          BASKET AVERAGE HDD <span className="acc">{d.basket.average.hdd.toFixed(1)}</span> · CDD <span className="acc">{d.basket.average.cdd.toFixed(1)}</span> <span className="dim">(7 DAYS, F-DAYS)</span>
        </div>
      )}
      {d && !showBasket && d.forecast && (
        <div className="line">
          {d.forecast.hdd.toFixed(1)} HDD · {d.forecast.cdd.toFixed(1)} CDD OVER {d.forecast.days_counted} DAYS <span className="dim">· {d.place?.lat.toFixed(2)},{d.place?.lon.toFixed(2)} · {d.forecast.tz}</span>
          {d.place?.others && d.place.others.length > 0 && <span className="dim"> · OTHER MATCHES: {d.place.others.join("; ").toUpperCase()}</span>}
        </div>
      )}
      {alerts && !showBasket && (
        <>
          {alerts.status === "OK" && (
            <div className="warn">NWS ALERTS: {alerts.items.length} ACTIVE</div>
          )}
          {alerts.items.slice(0, 4).map((a, i) => (
            <div key={i} className={alertColor(a)}>{alertLine(a)}</div>
          ))}
          {alerts.status !== "OK" && <div className={alerts.status === "NONE" ? "dim" : "warn"}>{alerts.note}</div>}
        </>
      )}
      <ErrorLine error={error} hasData={!!d} usage="WETR HOUSTON" />
      {showBasket ? <Grid ref={grid} columns={BASKET_COLUMNS} rows={basket} /> : <Grid ref={grid} columns={DAY_COLUMNS} rows={days} />}
    </div>
  );
}
