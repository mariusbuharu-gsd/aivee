// Unit tests for the price configurator's pure pricing function. Run with `node --test`.
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { plural, quote } from "../src/pricing.js";

const total = (input) => quote(input).monthly;

test("one location, up to 4 cameras, cloud: Standard base only", () => {
  const q = quote({ locations: 1, cameras: 4, mode: "cloud" });
  assert.equal(q.plan, "standard");
  assert.equal(q.monthly, 249);
  assert.equal(q.yearly, 249 * 12);
  assert.equal(q.lines.length, 1);
  assert.equal(q.hint, "");
});

test("one location: each camera above 4 costs 49", () => {
  assert.equal(total({ locations: 1, cameras: 5, mode: "cloud" }), 249 + 49);
  assert.equal(total({ locations: 1, cameras: 10, mode: "cloud" }), 249 + 6 * 49);
});

test("one location with more than 10 cameras stays Standard but hints at Pro", () => {
  const q = quote({ locations: 1, cameras: 11, mode: "cloud" });
  assert.equal(q.plan, "standard");
  assert.equal(q.monthly, 249 + 7 * 49);
  assert.match(q.hint, /598 lei/); // Pro: 549 + 1 extra camera
  assert.match(quote({ locations: 1, cameras: 11, mode: "edge-box" }).hint, /697 lei/); // + edge fee
  assert.equal(quote({ locations: 1, cameras: 10, mode: "cloud" }).hint, "");
});

test("two or more locations: Pro per location, 10 cameras included each", () => {
  const q = quote({ locations: 3, cameras: 10, mode: "cloud" });
  assert.equal(q.plan, "pro");
  assert.equal(q.monthly, 3 * 549);
  assert.equal(total({ locations: 3, cameras: 12, mode: "cloud" }), 3 * 549 + 2 * 49 * 3);
});

test("edge modes add a fee per location", () => {
  assert.equal(total({ locations: 1, cameras: 2, mode: "edge-box" }), 249 + 99);
  assert.equal(total({ locations: 1, cameras: 2, mode: "edge-pc" }), 249 + 49);
  assert.equal(total({ locations: 4, cameras: 16, mode: "edge-box" }), 4 * 549 + 6 * 49 * 4 + 4 * 99);
  assert.equal(total({ locations: 2, cameras: 1, mode: "edge-pc" }), 2 * 549 + 2 * 49);
});

test("the breakdown lines add up to the total", () => {
  for (const mode of ["cloud", "edge-box", "edge-pc"]) {
    for (const locations of [1, 2, 7, 20]) {
      for (const cameras of [1, 4, 5, 11, 16]) {
        const q = quote({ locations, cameras, mode });
        assert.equal(q.lines.reduce((s, l) => s + l.amount, 0), q.monthly);
      }
    }
  }
});

test("inputs are clamped to the supported ranges and rounded", () => {
  assert.deepEqual(quote({ locations: 0, cameras: 0, mode: "cloud" }), quote({ locations: 1, cameras: 1, mode: "cloud" }));
  assert.deepEqual(quote({ locations: 99, cameras: 99, mode: "cloud" }), quote({ locations: 20, cameras: 16, mode: "cloud" }));
  assert.deepEqual(quote({ locations: 2.4, cameras: Number.NaN, mode: "cloud" }), quote({ locations: 2, cameras: 1, mode: "cloud" }));
  assert.equal(quote({ locations: 1, cameras: 1, mode: "nope" }).monthly, 249);
});

test("Romanian counts take \"de\" from 20 up", () => {
  assert.equal(plural(1, "locație", "locații"), "1 locație");
  assert.equal(plural(19, "locație", "locații"), "19 locații");
  assert.equal(plural(20, "locație", "locații"), "20 de locații");
  assert.equal(plural(101, "cameră", "camere"), "101 camere");
  assert.equal(plural(120, "cameră", "camere"), "120 de camere");
  assert.equal(quote({ locations: 20, cameras: 16, mode: "cloud" }).lines[1].label, "120 de camere în plus");
});
