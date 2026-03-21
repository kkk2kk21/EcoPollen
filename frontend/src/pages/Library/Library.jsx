import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../../shared/api/auth";
import filterIcon from "../../shared/icons/filter.svg";
import {
  buildPaginationItems,
  countActiveFilters,
  DEFAULT_LIMIT,
  formatPublicationLabel,
  normalizeExpandedTerm,
} from "./libraryUtils";
import "./Library.css";

const LIBRARY_SOURCES = [
  {
    key: "cyberleninka",
    label: "CyberLeninka",
    description: "Российская научная библиотека статей",
    searchHint: "РУ поиск",
  },
  {
    key: "crossref",
    label: "Crossref",
    description: "Международный индекс научных публикаций",
    searchHint: "РУ/EN поиск",
  },
  {
    key: "openalex",
    label: "OpenAlex",
    description: "Открытый агрегатор научных работ",
    searchHint: "РУ/EN поиск",
  },
  {
    key: "pubmed",
    label: "PubMed",
    description: "Международная биомедицинская база публикаций",
    searchHint: "EN поиск",
  },
];

const SORT_OPTIONS = [
  { value: "relevance", label: "По релевантности" },
  { value: "date_desc", label: "Новые" },
  { value: "date_asc", label: "Старые" },
];

const LANGUAGE_OPTIONS = [
  { value: "any", label: "Любой язык" },
  { value: "ru", label: "Русский" },
  { value: "en", label: "English" },
  { value: "other", label: "Смешанный / другой" },
];

function sourceLabel(sourceKey) {
  return LIBRARY_SOURCES.find((item) => item.key === sourceKey)?.label || sourceKey;
}

function getInitialSourceState() {
  return Object.fromEntries(LIBRARY_SOURCES.map((item) => [item.key, true]));
}

export default function Library() {
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [expandSearch, setExpandSearch] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [author, setAuthor] = useState("");
  const [language, setLanguage] = useState("any");
  const [onlyWithYear, setOnlyWithYear] = useState(false);
  const [sort, setSort] = useState("relevance");
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [sourceState, setSourceState] = useState(getInitialSourceState);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [showSearchFeedback, setShowSearchFeedback] = useState(false);
  const [pageInput, setPageInput] = useState("1");
  const [isFiltersOpen, setIsFiltersOpen] = useState(false);
  const [paginationPagesWidth, setPaginationPagesWidth] = useState(0);
  const requestIdRef = useRef(0);
  const pendingScrollRestoreRef = useRef(null);
  const paginationPagesRef = useRef(null);

  const activeSources = useMemo(
    () => LIBRARY_SOURCES.filter((item) => sourceState[item.key]).map((item) => item.key),
    [sourceState]
  );

  const activeFilterCount = useMemo(
    () =>
      countActiveFilters({
        activeSources,
        totalSourceCount: LIBRARY_SOURCES.length,
        dateFrom,
        dateTo,
        author,
        language,
        onlyWithYear,
        limit,
      }),
    [activeSources, dateFrom, dateTo, author, language, onlyWithYear, limit]
  );

  const visibleExpandedTerms = useMemo(() => {
    const baseQuery = normalizeExpandedTerm(data?.query || query);
    const seen = new Set();

    return (data?.expanded_terms || []).filter((term) => {
      const normalizedTerm = normalizeExpandedTerm(term);
      if (!normalizedTerm || normalizedTerm === baseQuery || seen.has(normalizedTerm)) {
        return false;
      }
      seen.add(normalizedTerm);
      return true;
    });
  }, [data, query]);

  function toggleSource(key) {
    setSourceState((prev) => {
      const nextState = { ...prev, [key]: !prev[key] };
      const enabledCount = Object.values(nextState).filter(Boolean).length;
      return enabledCount ? nextState : prev;
    });
  }

  function resetFilters() {
    setDateFrom("");
    setDateTo("");
    setAuthor("");
    setLanguage("any");
    setOnlyWithYear(false);
    setLimit(DEFAULT_LIMIT);
    setSourceState(getInitialSourceState());
  }

  function buildSearchSnapshot(overrides = {}) {
    const nextSourceState = overrides.sourceState ?? sourceState;
    const nextActiveSources =
      overrides.activeSources ??
      LIBRARY_SOURCES.filter((item) => nextSourceState[item.key]).map((item) => item.key);

    return {
      query: (overrides.query ?? query).trim(),
      expandSearch: overrides.expandSearch ?? expandSearch,
      dateFrom: overrides.dateFrom ?? dateFrom,
      dateTo: overrides.dateTo ?? dateTo,
      author: overrides.author ?? author,
      language: overrides.language ?? language,
      onlyWithYear: overrides.onlyWithYear ?? onlyWithYear,
      sort: overrides.sort ?? sort,
      limit: overrides.limit ?? limit,
      activeSources: nextActiveSources,
    };
  }

  async function runSearch(nextPage = 1, options = {}) {
    const {
      closeFilters = false,
      queryOverride,
      searchSnapshot,
      suppressSearchFeedback = false,
      preserveScroll = false,
    } = options;
    const snapshot = buildSearchSnapshot({
      ...(searchSnapshot || {}),
      query: queryOverride ?? searchSnapshot?.query ?? query,
    });
    const searchQuery = snapshot.query;

    if (preserveScroll && typeof window !== "undefined") {
      pendingScrollRestoreRef.current = window.scrollY;
    } else {
      pendingScrollRestoreRef.current = null;
    }

    setErr("");

    if (!searchQuery) {
      setErr("Введите поисковый запрос.");
      return;
    }

    if (snapshot.activeSources.length === 0) {
      setErr("Выберите хотя бы один источник поиска.");
      return;
    }

    if (snapshot.dateFrom && snapshot.dateTo && snapshot.dateFrom > snapshot.dateTo) {
      setErr("Дата публикации: начальная дата не может быть больше конечной.");
      return;
    }

    const params = new URLSearchParams({
      q: searchQuery,
      page: String(nextPage),
      limit: snapshot.limit,
      sort: snapshot.sort,
      sources: snapshot.activeSources.join(","),
    });

    if (snapshot.expandSearch) params.set("expand_query", "true");
    if (snapshot.dateFrom) params.set("date_from", snapshot.dateFrom);
    if (snapshot.dateTo) params.set("date_to", snapshot.dateTo);
    if (snapshot.author.trim()) params.set("author", snapshot.author.trim());
    if (snapshot.language !== "any") params.set("language", snapshot.language);
    if (snapshot.onlyWithYear) params.set("only_with_year", "true");

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setIsSearching(true);
    setShowSearchFeedback(!suppressSearchFeedback);

    try {
      const result = await apiFetch(`/api/v1/library/search?${params.toString()}`);
      if (requestId !== requestIdRef.current) {
        return;
      }
      setData(result);
      if (closeFilters) {
        setIsFiltersOpen(false);
      }
    } catch (searchError) {
      if (requestId !== requestIdRef.current) {
        return;
      }
      pendingScrollRestoreRef.current = null;
      setErr(String(searchError));
    } finally {
      if (requestId === requestIdRef.current) {
        setIsSearching(false);
        setShowSearchFeedback(false);
      }
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    const normalizedQuery = queryInput.trim();
    setQuery(normalizedQuery);
    runSearch(1, {
      queryOverride: normalizedQuery,
      searchSnapshot: buildSearchSnapshot({ query: normalizedQuery }),
    });
  }

  function handleApplyFilters() {
    const normalizedQuery = queryInput.trim() || query;
    setQuery(normalizedQuery);
    const snapshot = buildSearchSnapshot({ query: normalizedQuery });
    runSearch(1, {
      closeFilters: true,
      queryOverride: normalizedQuery,
      searchSnapshot: snapshot,
    });
  }

  function handlePageInputChange(event) {
    const digitsOnly = event.target.value.replace(/[^\d]/g, "");
    if (!digitsOnly) {
      setPageInput("");
      return;
    }

    const maxPage = data?.pagination?.total_pages;
    if (!maxPage) {
      setPageInput(digitsOnly);
      return;
    }

    const numericValue = Number(digitsOnly);
    if (!Number.isFinite(numericValue)) {
      setPageInput(String(data.pagination.page));
      return;
    }

    setPageInput(String(Math.max(1, Math.min(maxPage, numericValue))));
  }

  function normalizePageInputValue(inputValue = pageInput) {
    const pagination = data?.pagination;
    if (!pagination?.total_pages) {
      return null;
    }

    const parsed = Number(inputValue);
    if (!Number.isFinite(parsed)) {
      return pagination.page;
    }

    return Math.max(
      1,
      Math.min(pagination.total_pages, Math.trunc(parsed))
    );
  }

  function syncPageInputWithBounds(inputValue = pageInput) {
    const normalized = normalizePageInputValue(inputValue);
    if (normalized === null) {
      return;
    }
    setPageInput(String(normalized));
  }

  function commitPageInput(inputValue = pageInput) {
    const pagination = data?.pagination;
    const normalized = normalizePageInputValue(inputValue);
    if (!pagination?.total_pages || normalized === null) {
      return;
    }

    setPageInput(String(normalized));

    if (normalized !== pagination.page) {
      runSearch(normalized, {
        suppressSearchFeedback: true,
        preserveScroll: true,
      });
    }
  }

  const pagination = data?.pagination;

  useEffect(() => {
    if (!data) {
      return undefined;
    }

    runSearch(1, { suppressSearchFeedback: true });
    return undefined;
  }, [sort]);

  useEffect(() => {
    if (!data?.pagination?.page) {
      return;
    }
    setPageInput(String(data.pagination.page));
  }, [data?.pagination?.page]);

  useLayoutEffect(() => {
    if (pendingScrollRestoreRef.current === null || typeof window === "undefined") {
      return;
    }

    const preservedScrollY = pendingScrollRestoreRef.current;
    pendingScrollRestoreRef.current = null;
    window.scrollTo({ top: preservedScrollY, behavior: "auto" });
  }, [data]);

  useLayoutEffect(() => {
    const element = paginationPagesRef.current;
    if (!element) {
      return undefined;
    }

    const updateWidth = () => setPaginationPagesWidth(element.clientWidth);
    updateWidth();

    if (typeof ResizeObserver === "undefined") {
      return undefined;
    }

    const observer = new ResizeObserver(() => updateWidth());
    observer.observe(element);

    return () => observer.disconnect();
  }, [pagination?.total_pages]);

  const maxVisiblePaginationButtons = useMemo(() => {
    if (typeof window === "undefined") {
      return 9;
    }

    if (window.innerWidth > 720) {
      return 9;
    }

    const mobileMaxSlots = window.innerWidth <= 420 ? 5 : 7;

    if (!paginationPagesWidth) {
      return mobileMaxSlots;
    }

    return Math.max(
      5,
      Math.min(mobileMaxSlots, Math.floor((paginationPagesWidth + 8) / 52))
    );
  }, [paginationPagesWidth]);

  const paginationItems = buildPaginationItems(
    pagination?.total_pages || 0,
    pagination?.page || 1,
    maxVisiblePaginationButtons
  );

  function renderPageJumpControl(extraClassName = "") {
    if (!pagination?.total_pages) {
      return null;
    }

    const className = ["library-pagination-copy", extraClassName]
      .filter(Boolean)
      .join(" ");

    return (
      <div className={className}>
        <span className="library-pagination-label">Страница</span>
        <div className="library-pagination-edit-row">
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={pageInput}
            onChange={handlePageInputChange}
            onBlur={(event) => syncPageInputWithBounds(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitPageInput(event.currentTarget.value);
              }
            }}
            className="library-page-input"
            aria-label="Номер страницы"
          />
          <span>из {pagination.total_pages}</span>
          <button
            type="button"
            className="secondary library-page-jump"
            onClick={() => commitPageInput(pageInput)}
            disabled={isSearching}
          >
            Перейти
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="library-page">
      <header className="library-header">
        <div className="library-header-copy">
          <p className="summary-kicker">Поиск публикаций</p>
          <h2 className="section-title">Научная библиотека</h2>
        </div>
      </header>

      <section className="library-command-card card">
        <form className="library-command-form" onSubmit={handleSubmit}>
          <div className="library-search-main">
            <label htmlFor="library-query">Поисковый запрос</label>
            <div className="library-search-row">
              <input
                id="library-query"
                value={queryInput}
                onChange={(event) => setQueryInput(event.target.value)}
                placeholder="Например: аллергия на злаки"
              />
              <label className="library-expand-toggle">
                <input
                  type="checkbox"
                  checked={expandSearch}
                  onChange={(event) => setExpandSearch(event.target.checked)}
                />
                <span>Расширить поиск</span>
              </label>
            </div>
            {visibleExpandedTerms.length && data?.filters?.expand_query ? (
              <div className="library-expansion-note library-expansion-inline">
                Дополнено следующими запросами: {visibleExpandedTerms.join(", ")}
              </div>
            ) : null}
          </div>
          {isSearching && showSearchFeedback ? (
            <div className="library-search-feedback" role="status" aria-live="polite">
              <span className="library-search-feedback-text">Ищем публикации...</span>
              <span className="library-search-progress" />
            </div>
          ) : null}

          <div className="library-command-actions">
            <button type="submit" disabled={isSearching && showSearchFeedback}>
              {isSearching && showSearchFeedback ? "Ищем..." : "Искать"}
            </button>
            <button
              type="button"
              className="secondary"
              aria-expanded={isFiltersOpen}
              aria-controls="library-filter-drawer"
              onClick={() => setIsFiltersOpen(true)}
            >
              Фильтры{activeFilterCount ? ` (${activeFilterCount})` : ""}
            </button>
          </div>
        </form>

      </section>

      <div
        className={`library-filter-backdrop ${isFiltersOpen ? "is-open" : ""}`}
        onClick={() => setIsFiltersOpen(false)}
      />

      <aside
        id="library-filter-drawer"
        className={`library-drawer card ${isFiltersOpen ? "is-open" : ""}`}
      >
        <div className="library-drawer-head">
          <div className="library-drawer-copy">
            <div className="library-drawer-title">Фильтры поиска</div>
          </div>

          <button
            type="button"
            className="secondary library-icon-button"
            onClick={() => setIsFiltersOpen(false)}
          >
            Закрыть
          </button>
        </div>

        <div className="library-drawer-body">
          <section className="library-filter-section">
            <div className="library-filter-section-title">Дата публикации</div>
            <div className="library-filter-grid">
              <div className="library-field">
                <label htmlFor="library-date-from">От</label>
                <input
                  id="library-date-from"
                  type="date"
                  value={dateFrom}
                  max={dateTo || undefined}
                  onChange={(event) => setDateFrom(event.target.value)}
                />
              </div>

              <div className="library-field">
                <label htmlFor="library-date-to">До</label>
                <input
                  id="library-date-to"
                  type="date"
                  value={dateTo}
                  min={dateFrom || undefined}
                  onChange={(event) => setDateTo(event.target.value)}
                />
              </div>
            </div>
          </section>

          <section className="library-filter-section">
            <div className="library-filter-section-title">Источники поиска</div>
            <div className="library-drawer-source-grid">
              {LIBRARY_SOURCES.map((source) => (
                <label
                  key={`drawer-${source.key}`}
                  className={`library-source-pill ${sourceState[source.key] ? "is-active" : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={!!sourceState[source.key]}
                    onChange={() => toggleSource(source.key)}
                  />
                  <span className="library-source-pill-copy">
                    <span className="library-source-pill-title">{source.label}</span>
                    <span className="library-source-pill-meta">{source.description}</span>
                    <span className="library-source-pill-hint">{source.searchHint}</span>
                  </span>
                </label>
              ))}
            </div>
          </section>

          <section className="library-filter-section">
            <div className="library-filter-section-title">Параметры выдачи</div>
            <div className="library-filter-grid">
              <div className="library-field">
                <label htmlFor="library-author">Автор</label>
                <input
                  id="library-author"
                  value={author}
                  onChange={(event) => setAuthor(event.target.value)}
                  placeholder="Например: Иванов"
                />
              </div>

              <div className="library-field">
                <label htmlFor="library-language">Язык</label>
                <select
                  id="library-language"
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                >
                  {LANGUAGE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="library-field">
                <label htmlFor="library-limit">Публикаций на странице</label>
                <select
                  id="library-limit"
                  value={limit}
                  onChange={(event) => setLimit(event.target.value)}
                >
                  {[8, 12, 16, 20].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="library-inline-checks">
              <label className="library-inline-check">
                <input
                  type="checkbox"
                  checked={onlyWithYear}
                  onChange={(event) => setOnlyWithYear(event.target.checked)}
                />
                <span>Только публикации с датой публикации</span>
              </label>
            </div>
          </section>

        </div>

        <div className="library-drawer-foot">
          <button type="button" className="secondary" onClick={resetFilters}>
            Сбросить
          </button>
          <button type="button" onClick={handleApplyFilters} disabled={isSearching}>
            {isSearching ? "Обновляем..." : "Применить"}
          </button>
        </div>
      </aside>

      <section className="library-results-panel" id="library-results">
        {err ? <div className="note">{err}</div> : null}

        {data ? (
          <section className="library-results-summary card-soft">
            <div className="library-results-summary-top">
              <div className="library-results-main">
                <div className="library-summary-copy">
                  <p className="summary-kicker library-results-kicker">Результаты поиска</p>
                  <div className="library-results-text">
                    <div className="library-results-title">
                      Найдено публикаций: {pagination?.total_results ?? data.results.length}
                    </div>
                  </div>
                </div>
                {pagination?.total_pages > 1
                  ? renderPageJumpControl("library-results-page-jump")
                  : null}
              </div>

              <div className="library-results-sort">
                <div className="library-sort-select-shell">
                  <select
                    className="library-sort-select"
                    value={sort}
                    onChange={(event) => setSort(event.target.value)}
                    aria-label="Сортировка результатов"
                  >
                    {SORT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <img
                    className="library-sort-icon"
                    src={filterIcon}
                    alt=""
                    aria-hidden="true"
                  />
                </div>
              </div>
            </div>

          </section>
        ) : null}

        {data?.results?.length ? (
          <section className="library-results">
            {data.results.map((result, index) => (
              <article className="library-result-card card" key={`${result.url}-${index}`}>
                <div className="library-result-top">
                  <div className="library-result-title">{result.title}</div>
                  <div className="library-result-badges">
                    <span className="badge">{sourceLabel(result.source)}</span>
                    {formatPublicationLabel(result) ? (
                      <span className="badge">{formatPublicationLabel(result)}</span>
                    ) : null}
                  </div>
                </div>

                <div className="library-result-meta">
                  {result.authors || "Авторы не указаны"}
                </div>

                {result.snippet ? (
                  <p className="library-result-snippet">{result.snippet}</p>
                ) : null}

                {result.url ? (
                  <a
                    className="library-result-link"
                    href={result.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Открыть публикацию
                  </a>
                ) : null}
              </article>
            ))}
          </section>
        ) : data ? (
          <div className="card">Ничего не найдено по выбранным фильтрам.</div>
        ) : (
          <div className="card-soft library-empty-state">
            Статьи после поиска будут находиться здесь.
          </div>
        )}

        {pagination?.total_pages > 1 ? (
          <section className="library-pagination card-soft">
            {renderPageJumpControl()}
            <div className="library-pagination-actions">
              <button
                type="button"
                className="secondary"
                disabled={!pagination.has_prev || isSearching}
                onClick={() =>
                  runSearch(pagination.page - 1, {
                    preserveScroll: true,
                  })
                }
              >
                Назад
              </button>
              <button
                type="button"
                disabled={!pagination.has_next || isSearching}
                onClick={() =>
                  runSearch(pagination.page + 1, {
                    preserveScroll: true,
                  })
                }
              >
                Вперёд
              </button>
            </div>

            <div className="library-pagination-pages" ref={paginationPagesRef}>
              {paginationItems.map((item) =>
                typeof item === "number" ? (
                  <button
                    key={item}
                    type="button"
                    className={`secondary library-page-number ${
                      item === pagination.page ? "is-active" : ""
                    }`}
                    disabled={item === pagination.page || isSearching}
                    onClick={() =>
                      runSearch(item, {
                        preserveScroll: true,
                      })
                    }
                  >
                    {item}
                  </button>
                ) : (
                  <span key={item} className="library-page-ellipsis">
                    ...
                  </span>
                )
              )}
            </div>
          </section>
        ) : null}
      </section>
    </div>
  );
}
