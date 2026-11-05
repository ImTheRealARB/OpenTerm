import { describe, expect, it } from "vitest";
import { chokepoints, toShapes as chokeShapes } from "./layers/chokepoints";
import { toShapes as eventShapes, toneOf } from "./layers/events";
import { DEFAULT_ON, LAYERS } from "./layers/index";
import { radius as portRadius, toShapes as portShapes } from "./layers/ports";
import { radius as quakeRadius, toShapes as quakeShapes, tone as quakeTone } from "./layers/quakes";
import { toShapes as vesselShapes } from "./layers/vessels";
import type { AisRow, GeoEvents, GeoPorts, GeoQuakes } from "../net/api";

const ship = (over: Partial<AisRow>): AisRow => ({
  mmsi: 1, name: "TEST", imo: null, type: "Tanker", type_code: 80, sog: 12, cog: 90, heading: null, nav: 0, nav_name: "UNDER WAY USING ENGINE",
  dest: null, eta: null, length: null, draught: null, lat: 26.4, lon: 56.3, seen: 1_700_000_000, static_age_s: null, ...over,
});

describe("layer registry", () => {
  it("has unique ids and number keys, every layer fully described", () => {
    expect(new Set(LAYERS.map((l) => l.id)).size).toBe(LAYERS.length);
    expect(new Set(LAYERS.map((l) => l.key)).size).toBe(LAYERS.length);
    for (const l of LAYERS) {
      for (const f of [l.name, l.source, l.shapes, l.colour, l.refresh]) expect(f.length).toBeGreaterThan(3);
      expect(l.load).toBeTypeOf("function");
    }
  });
  it("defaults to keyless layers only, and names the key a layer needs", () => {
    for (const id of DEFAULT_ON) expect(LAYERS.find((l) => l.id === id)?.needsKey).toBeUndefined();
    expect(LAYERS.find((l) => l.id === "vessels")?.needsKey).toBe("AISSTREAM_API_KEY");
    expect(chokepoints.perArea).toBeUndefined();
  });
});

describe("vessels", () => {
  const payload = (rows: AisRow[]) => ({ area: "HORMUZ", box: [25.8, 55.6, 27, 57] as [number, number, number, number], rows, truncated: 0, received: 5, capped: false, listened_s: 8, fixture: false, note: "" });
  it("colours by what the ship reports: moving, stopped, trouble", () => {
    const [moving, stopped, trouble, noSpeed] = vesselShapes(payload([ship({ mmsi: 1 }), ship({ mmsi: 2, sog: 0.1 }), ship({ mmsi: 3, nav_name: "AGROUND" }), ship({ mmsi: 4, sog: null })]));
    expect([moving.tone, stopped.tone, trouble.tone, noSpeed.tone]).toEqual(["acc", "dim", "warn", "dim"]);
  });
  it("draws only ships inside the box that was asked for", () => {
    const shapes = vesselShapes(payload([ship({ mmsi: 1, lat: 26.4, lon: 56.3 }), ship({ mmsi: 2, lat: 30.2, lon: 32.5 })]));
    expect(shapes.map((s) => s.id)).toEqual(["HORMUZ:1"]);
  });
  it("ids carry the area, so two listens never collide", () => {
    expect(vesselShapes(payload([ship({ mmsi: 7 })]))[0].id).toBe("HORMUZ:7");
  });
  it("labels crew-typed destination and an unnamed ship by MMSI, and never invents speed", () => {
    const [s] = vesselShapes(payload([ship({ name: "", mmsi: 99, sog: null, dest: "FUJAIRAH", static_age_s: 120 })]));
    expect(s.label).toBe("MMSI 99");
    expect(s.detail.find(([k]) => k === "SPEED")?.[1]).toBe("NOT REPORTED");
    expect(s.detail.find(([k]) => k === "DESTINATION")?.[1]).toContain("TYPED BY CREW");
  });
});

describe("ports", () => {
  const p: GeoPorts = { rows: [{ id: "p1", name: "Singapore", country: "Singapore", locode: "SG SIN", lat: 1.26, lon: 103.8, rank: 1, calls_per_day: 115, newest: "2026-10-30" }], skipped: 0, newest: "2026-10-30", note: "" };
  it("sizes dots by activity with a floor and a ceiling", () => {
    expect(portRadius(0)).toBe(2);
    expect(portRadius(1_000_000)).toBe(12);
    expect(portRadius(100)).toBeGreaterThan(portRadius(10));
    expect(portShapes(p)[0].r).toBeCloseTo(portRadius(115), 9);
  });
  it("keeps the data date, not the fetch time, as the observation time", () => {
    expect(portShapes(p)[0].time).toBe(Date.parse("2026-10-30T23:59:59Z") / 1000);
  });
});

describe("quakes", () => {
  const p: GeoQuakes = { rows: [
    { id: "a", lat: 1, lon: 2, depth_km: 10, mag: 7.2, mag_type: "mw", place: "X", time: 1_700_000_000, url: null, tsunami: true, alert: null, status: "reviewed" },
    { id: "b", lat: 1, lon: 2, depth_km: null, mag: null, mag_type: null, place: "Y", time: 1_700_000_001, url: null, tsunami: false, alert: null, status: null },
  ], skipped: 0, title: "", generated: null, note: "" };
  it("bigger quakes are bigger and redder, an unknown magnitude is not drawn as a big one", () => {
    expect(quakeRadius(7)).toBeGreaterThan(quakeRadius(5));
    expect(quakeTone(7.2)).toBe("err");
    expect(quakeTone(6.1)).toBe("warn");
    expect(quakeTone(5)).toBe("acc");
    expect(quakeTone(null)).toBe("acc");
  });
  it("shows the tsunami flag only when USGS set it", () => {
    const [a, b] = quakeShapes(p);
    expect(a.detail.some(([k]) => k === "TSUNAMI")).toBe(true);
    expect(b.detail.some(([k]) => k === "TSUNAMI")).toBe(false);
  });
});

describe("events", () => {
  const p: GeoEvents = { rows: [
    { id: "E1", title: "Cyclone", category: "severeStorms", category_title: "Severe Storms", lat: 14, lon: 80, time: 2, mag: 60, mag_unit: "kts", source: "JTWC", url: null, track: [[86, 11], [80, 14]] },
    { id: "E2", title: "Volcano", category: "volcanoes", category_title: "Volcanoes", lat: 1, lon: 2, time: 1, mag: null, mag_unit: null, source: null, url: null, track: [[2, 1]] },
  ], skipped: 0, title: "", note: "" };
  it("draws a path only for an event that has moved", () => {
    const shapes = eventShapes(p);
    expect(shapes.map((s) => `${s.kind}:${s.id}`)).toEqual(["pt:E1", "line:E1:path", "pt:E2"]);
    const line = shapes[1];
    expect(line.kind === "line" && line.pts).toEqual([[86, 11], [80, 14]]);
  });
  it("colours by kind of event", () => {
    expect(toneOf("severeStorms")).toBe("warn");
    expect(toneOf("volcanoes")).toBe("err");
    expect(toneOf("somethingNew")).toBe("fg");
  });
});

describe("chokepoints", () => {
  it("makes a rectangle from the box and points at the centre", () => {
    const [b] = chokeShapes({ rows: [{ id: "HORMUZ", name: "HORMUZ", box: [25.8, 55.6, 27, 57], lat: 26.4, lon: 56.3 }], note: "" });
    expect(b.kind).toBe("box");
    expect(b.kind === "box" && b.box).toEqual([25.8, 55.6, 27, 57]);
    expect(b.detail.some(([, v]) => v.includes("PRESS V"))).toBe(true);
  });
});
