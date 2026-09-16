import { describe, it, expect } from "vitest";
import { bucketFillTimes } from "../gapHistogram";

const g = (filled, fill_minutes) => ({ filled, fill_minutes });

describe("bucketFillTimes", () => {
  it("buckets each filled gap into the bucket whose upper bound it does not exceed", () => {
    const gaps = [g(true, 10), g(true, 45), g(true, 90), g(true, 200), g(true, 400), g(true, 600)];
    const buckets = bucketFillTimes(gaps);
    expect(buckets.map((b) => b.count)).toEqual([1, 1, 1, 1, 1, 1, 0]);
  });

  it("counts unfilled gaps in a separate 'jamais' bucket, never assigning them a fake fill time", () => {
    const gaps = [g(true, 10), g(false, null), g(false, null)];
    const buckets = bucketFillTimes(gaps);
    const jamais = buckets.find((b) => b.key === "jamais");
    expect(jamais.count).toBe(2);
    expect(buckets.reduce((s, b) => s + b.count, 0)).toBe(3);
  });

  it("returns zero percent buckets rather than dividing by zero on an empty input", () => {
    const buckets = bucketFillTimes([]);
    expect(buckets.every((b) => b.count === 0 && b.pct === 0)).toBe(true);
  });

  it("a value exactly on a boundary falls in the lower bucket (inclusive upper bound)", () => {
    const buckets = bucketFillTimes([g(true, 30), g(true, 60)]);
    expect(buckets.find((b) => b.key === "0-30m").count).toBe(1);
    expect(buckets.find((b) => b.key === "30-60m").count).toBe(1);
  });
});
