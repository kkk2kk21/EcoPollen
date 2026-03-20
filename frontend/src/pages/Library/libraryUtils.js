export const DEFAULT_LIMIT = "12";

export function normalizeExpandedTerm(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

export function formatPublicationLabel(result) {
  if (result?.published_at) {
    const [year, month, day] = String(result.published_at).split("-");
    if (year && month && day) {
      return `${day}.${month}.${year}`;
    }
    if (year && month) {
      return `${month}.${year}`;
    }
    if (year) {
      return year;
    }
  }

  return result?.year ? String(result.year) : null;
}

export function countActiveFilters({
  activeSources,
  totalSourceCount,
  dateFrom,
  dateTo,
  author,
  language,
  onlyWithYear,
  limit,
}) {
  let count = 0;

  if (activeSources.length !== totalSourceCount) count += 1;
  if (dateFrom) count += 1;
  if (dateTo) count += 1;
  if ((author || "").trim()) count += 1;
  if (language !== "any") count += 1;
  if (onlyWithYear) count += 1;
  if (limit !== DEFAULT_LIMIT) count += 1;

  return count;
}

export function buildPaginationItems(totalPages, currentPage, maxSlots = 9) {
  if (!totalPages) return [];

  if (totalPages <= maxSlots) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const slots = Math.max(5, maxSlots);

  if (currentPage <= slots - 2) {
    const leadingPages = Array.from({ length: slots - 2 }, (_, index) => index + 1);
    return [...leadingPages, `ellipsis-${slots - 2}-${totalPages}`, totalPages];
  }

  if (currentPage >= totalPages - (slots - 3)) {
    const trailingStart = totalPages - (slots - 3);
    const trailingPages = Array.from(
      { length: totalPages - trailingStart + 1 },
      (_, index) => trailingStart + index
    );
    return [1, `ellipsis-1-${trailingStart}`, ...trailingPages];
  }

  const middleCount = Math.max(1, slots - 4);
  let start = currentPage - Math.floor((middleCount - 1) / 2);
  let end = start + middleCount - 1;

  if (start < 2) {
    start = 2;
    end = start + middleCount - 1;
  }

  if (end > totalPages - 1) {
    end = totalPages - 1;
    start = end - middleCount + 1;
  }

  return [
    1,
    `ellipsis-1-${start}`,
    ...Array.from({ length: end - start + 1 }, (_, index) => start + index),
    `ellipsis-${end}-${totalPages}`,
    totalPages,
  ];
}
