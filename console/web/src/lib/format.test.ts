import { fmtAgo, fmtBytes, fmtDuration, middleTruncate, stageName, stageNo } from "./format";

describe("format", () => {
  it("formats durations across scales", () => {
    expect(fmtDuration(null)).toBe("—");
    expect(fmtDuration(0.4)).toBe("<1 ms");
    expect(fmtDuration(14)).toBe("14 ms");
    expect(fmtDuration(14582)).toBe("14.6 s");
    expect(fmtDuration(5601)).toBe("5.60 s");
    expect(fmtDuration(125000)).toBe("2m 5s");
  });
  it("formats relative times", () => {
    const now = Date.parse("2026-10-01T12:00:00Z");
    expect(fmtAgo("2026-10-01T11:59:58Z", now)).toBe("just now");
    expect(fmtAgo("2026-10-01T11:59:30Z", now)).toBe("30s ago");
    expect(fmtAgo("2026-10-01T11:00:00Z", now)).toBe("1 h ago");
    expect(fmtAgo("2026-10-01T11:30:00Z", now)).toBe("30 min ago");
    expect(fmtAgo("2026-07-29T16:06:14Z", now)).toBe("64 days ago");
    expect(fmtAgo(null, now)).toBe("—");
  });
  it("keeps both ends of long ids", () => {
    const id = "05_MEDIUM_FUND_TRANSFER_WITH_VALIDATION__5E3A3BBB__PROC-.SP_TRANSFER_FUNDS__STMT_0022";
    const t = middleTruncate(id, 40);
    expect(t.length).toBeLessThanOrEqual(40);
    expect(t.startsWith("05_MEDIUM")).toBe(true);
    expect(t.endsWith("STMT_0022")).toBe(true);
  });
  it("formats sizes and stage keys", () => {
    expect(fmtBytes(992)).toBe("992 B");
    expect(fmtBytes(131450)).toBe("128.4 KB");
    expect(stageNo("07_synthesis")).toBe("07");
    expect(stageName("07_synthesis")).toBe("synthesis");
  });
});
