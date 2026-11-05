// Records the real answers the MAP panel's backend tests replay (run once, commit the files; tests never touch the network).
//   node scripts/record_map_fixtures.mjs
// Writes backend/tests/fixtures/{usgs_quakes_4_5_week,eonet_open_no_wildfires,portwatch_ports_db_top25}.json in the standard
// {"status", "recorded", "body"} shape that providers/fixtures.py `_load` reads.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "backend", "tests", "fixtures");
const today = new Date().toISOString().slice(0, 10);
const UA = { "User-Agent": "OpenTerm-fixture-recorder", Accept: "application/json" };

async function record(name, url, note) {
  const r = await fetch(url, { headers: UA });
  const body = JSON.parse(await r.text());
  writeFileSync(join(FIX, `${name}.json`), JSON.stringify({ status: r.status, recorded: `${today}, real ${note}`, body }));
  console.log(name, r.status);
  return body;
}

await record("usgs_quakes_4_5_week", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson", "USGS earthquake feed (M4.5+, past 7 days)");
// Wildfires are left out on purpose: 7,000+ open fire events, a 5 MB answer. The panel says so.
const cats = "severeStorms,volcanoes,floods,seaLakeIce,earthquakes,landslides,drought,dustHaze,manmade,snow,tempExtremes,waterColor";
await record("eonet_open_no_wildfires", `https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=100&category=${cats}`, "NASA EONET open events without wildfires");

// Port coordinates for the 25 ports of the PORTS fixture (portwatch_ports_top25.json), asked the way ports_geo asks.
const top = JSON.parse(readFileSync(join(FIX, "portwatch_ports_top25.json"), "utf8")).body.features.map((f) => f.attributes.portid);
const where = `portid IN (${top.map((i) => `'${i}'`).join(",")})`;
const params = new URLSearchParams({ f: "json", returnGeometry: "false", where, outFields: "portid,portname,country,ISO3,continent,fullname,lat,lon,vessel_count_total,LOCODE", resultRecordCount: "150" });
await record("portwatch_ports_db_top25", `https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/PortWatch_ports_database/FeatureServer/0/query?${params}`, "IMF PortWatch ArcGIS port list for the 25 busiest ports");
