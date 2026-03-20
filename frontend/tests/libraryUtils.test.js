import {
  buildPaginationItems,
  countActiveFilters,
  DEFAULT_LIMIT,
  formatPublicationLabel,
  normalizeExpandedTerm,
} from "../src/pages/Library/libraryUtils.js";

describe("libraryUtils", () => {
  it("normalizes expanded term text", () => {
    expect(normalizeExpandedTerm("  Birch   Pollen ")).toBe("birch pollen");
  });

  it("formats publication label from full or partial date", () => {
    expect(formatPublicationLabel({ published_at: "2026-03-21" })).toBe("21.03.2026");
    expect(formatPublicationLabel({ published_at: "2026-03" })).toBe("03.2026");
    expect(formatPublicationLabel({ year: 2025 })).toBe("2025");
  });

  it("counts only active non-default filters", () => {
    const count = countActiveFilters({
      activeSources: ["crossref"],
      totalSourceCount: 4,
      dateFrom: "2026-01-01",
      dateTo: "",
      author: "Ivanov",
      language: "en",
      onlyWithYear: true,
      limit: DEFAULT_LIMIT,
    });

    expect(count).toBe(5);
  });

  it("builds compact pagination with ellipses", () => {
    expect(buildPaginationItems(5, 3)).toEqual([1, 2, 3, 4, 5]);
    expect(buildPaginationItems(20, 1, 7)).toEqual([1, 2, 3, 4, 5, "ellipsis-5-20", 20]);
    expect(buildPaginationItems(20, 10, 7)).toEqual([
      1,
      "ellipsis-1-9",
      9,
      10,
      11,
      "ellipsis-11-20",
      20,
    ]);
  });
});
