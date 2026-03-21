import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Circle, MapContainer, TileLayer } from "react-leaflet";
import { requestJson } from "../../shared/api/http";
import { fetchMapPlaces } from "../../shared/api/mapPlaces";
import MapAttributionCleaner from "../../shared/components/MapAttributionCleaner";
import { readPreferredMapPlaceId, savePreferredMapPlace } from "../../shared/mapSelection";
import "./Home.css";

function formatDate(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString("ru-RU", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return value;
  }
}

function prettySourceName(key) {
  const map = {
    pgniu_manual: "ПГНИУ",
    meteoswiss: "MeteoSwiss",
    norkko: "Norkko",
    dwd: "DWD",
    open_meteo: "Open-Meteo / CAMS",
  };
  return map[key] || key || "нет";
}

function riskCardClass(color) {
  if (color === "green") return "home-risk-card risk-green";
  if (color === "yellowgreen") return "home-risk-card risk-yellowgreen";
  if (color === "yellow") return "home-risk-card risk-yellow";
  if (color === "orange") return "home-risk-card risk-orange";
  if (color === "red") return "home-risk-card risk-red";
  if (color === "darkred") return "home-risk-card risk-darkred";
  return "home-risk-card risk-purple";
}

function sourceBadgeClass(source) {
  if (source === "pgniu_manual") return "badge badge-success";
  if (source === "open_meteo") return "badge badge-warning";
  return "badge badge-neutral";
}

function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/ё/g, "е")
    .trim();
}

function comparePlaceNames(left, right) {
  return String(left?.label || left?.name || "").localeCompare(
    String(right?.label || right?.name || ""),
    "ru"
  );
}

function formatCoords(lat, lon) {
  if (!Number.isFinite(Number(lat)) || !Number.isFinite(Number(lon))) return "—";
  return `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}`;
}

function homeMapZoom(place) {
  if (!place) return 6;
  if (place.kind === "region") return 7;
  if (place.kind === "station") return 9;
  return 10;
}

export default function Home() {
  const [places, setPlaces] = useState([]);
  const [selectedPlaceId, setSelectedPlaceId] = useState("");
  const [placeQuery, setPlaceQuery] = useState("");
  const [isPlaceMenuOpen, setIsPlaceMenuOpen] = useState(false);
  const [summary, setSummary] = useState(null);
  const [loadingPlaces, setLoadingPlaces] = useState(true);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [hasLoadedSummary, setHasLoadedSummary] = useState(false);
  const [resolvedSummaryPlaceId, setResolvedSummaryPlaceId] = useState("");
  const [error, setError] = useState("");
  const placePickerRef = useRef(null);
  const riskDisplayRef = useRef(null);
  const riskNumberRef = useRef(null);
  const [riskFontSize, setRiskFontSize] = useState(null);

  useEffect(() => {
    function handleOutsideClick(event) {
      if (!placePickerRef.current?.contains(event.target)) {
        setIsPlaceMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  useEffect(() => {
    async function loadPlaces() {
      try {
        setLoadingPlaces(true);
        setError("");

        const data = await fetchMapPlaces();
        const items = (Array.isArray(data) ? data : []).sort(comparePlaceNames);
        setPlaces(items);

        const preferredId = readPreferredMapPlaceId();
        const preferredPlace =
          items.find((item) => String(item.id) === String(preferredId)) ||
          items.find((item) => item.label === "Пермь") ||
          items[0] ||
          null;

        if (preferredPlace) {
          setSummary(null);
          setHasLoadedSummary(false);
          setResolvedSummaryPlaceId("");
          setLoadingSummary(true);
          setSelectedPlaceId(String(preferredPlace.id));
          setPlaceQuery(preferredPlace.label || preferredPlace.name || "");
          savePreferredMapPlace(preferredPlace);
        }
      } catch (e) {
        setError(e.message || "Ошибка загрузки городов");
        setLoadingSummary(false);
      } finally {
        setLoadingPlaces(false);
      }
    }

    loadPlaces();
  }, []);

  const selectedPlace = useMemo(
    () => places.find((item) => String(item.id) === String(selectedPlaceId)) || null,
    [places, selectedPlaceId]
  );

  const effectivePlaceQuery = useMemo(() => {
    const currentLabel = selectedPlace?.label || selectedPlace?.name || "";
    if (
      isPlaceMenuOpen &&
      currentLabel &&
      normalizeSearchText(placeQuery) === normalizeSearchText(currentLabel)
    ) {
      return "";
    }
    return placeQuery;
  }, [isPlaceMenuOpen, placeQuery, selectedPlace]);

  const filteredPlaces = useMemo(() => {
    const normalizedQuery = normalizeSearchText(effectivePlaceQuery);
    if (!normalizedQuery) {
      if (!selectedPlace) return places;
      return [
        selectedPlace,
        ...places.filter((place) => String(place.id) !== String(selectedPlace.id)),
      ];
    }

    const exact = [];
    const startsWith = [];
    const searchStartsWith = [];
    const contains = [];

    for (const place of places) {
      const label = normalizeSearchText(place.label || place.name);
      const searchText = normalizeSearchText(
        `${place.search_text || ""} ${place.label || place.name || ""}`
      );

      if (label === normalizedQuery) {
        exact.push(place);
      } else if (label.startsWith(normalizedQuery)) {
        startsWith.push(place);
      } else if (searchText.startsWith(normalizedQuery)) {
        searchStartsWith.push(place);
      } else if (searchText.includes(normalizedQuery)) {
        contains.push(place);
      }
    }

    exact.sort(comparePlaceNames);
    startsWith.sort(comparePlaceNames);
    searchStartsWith.sort(comparePlaceNames);
    contains.sort(comparePlaceNames);

    return [...exact, ...startsWith, ...searchStartsWith, ...contains];
  }, [effectivePlaceQuery, places, selectedPlace]);

  useEffect(() => {
    async function loadSummary() {
      if (!selectedPlace) {
        setSummary(null);
        setHasLoadedSummary(false);
        setResolvedSummaryPlaceId("");
        setLoadingSummary(false);
        return;
      }

      const currentPlaceId = String(selectedPlace.id);

      try {
        setLoadingSummary(true);
        setHasLoadedSummary(false);
        setResolvedSummaryPlaceId("");
        setError("");

        const query = new URLSearchParams();
        if (selectedPlace.location_id) {
          query.set("location_id", String(selectedPlace.location_id));
        } else if (selectedPlace.external_location_id) {
          query.set("external_location_id", String(selectedPlace.external_location_id));
        } else {
          query.set("lat", String(selectedPlace.lat));
          query.set("lon", String(selectedPlace.lon));
        }
        if (selectedPlace.source_key) {
          query.set("preferred_source_key", String(selectedPlace.source_key));
        }

        const data = await requestJson(`/api/v1/summary?${query.toString()}`, {
          errorMessage: "Не удалось загрузить сводку",
        });
        setSummary(data);
        setHasLoadedSummary(true);
        setResolvedSummaryPlaceId(currentPlaceId);
      } catch (e) {
        setError(e.message || "Ошибка загрузки сводки");
        setSummary(null);
        setHasLoadedSummary(true);
        setResolvedSummaryPlaceId(currentPlaceId);
      } finally {
        setLoadingSummary(false);
      }
    }

    loadSummary();
  }, [selectedPlace]);

  function applyPlaceSelection(place) {
    if (!place) return;
    setSummary(null);
    setHasLoadedSummary(false);
    setResolvedSummaryPlaceId("");
    setLoadingSummary(true);
    setSelectedPlaceId(String(place.id));
    setPlaceQuery(place.label || place.name || "");
    setIsPlaceMenuOpen(false);
    savePreferredMapPlace(place);
  }

  const mapCenter = useMemo(() => {
    const lat = selectedPlace?.lat ?? 58.0105;
    const lon = selectedPlace?.lon ?? 56.2502;
    return [Number(lat), Number(lon)];
  }, [selectedPlace]);

  const mapKey = useMemo(() => mapCenter.join("-"), [mapCenter]);
  const mapLink = selectedPlace ? `/map?placeId=${encodeURIComponent(selectedPlace.id)}` : "/map";

  const locationName = selectedPlace?.label || selectedPlace?.name || "Локация";
  const locationCoords = selectedPlace
    ? formatCoords(selectedPlace.lat, selectedPlace.lon)
    : formatCoords(summary?.location?.lat, summary?.location?.lon);

  const usedSources = summary?.used_sources || [];
  const recommendations = summary?.recommendations || [];
  const taxa = summary?.taxa || [];
  const riskLabel = summary?.overall?.display_label || summary?.overall?.label || "—";
  const showSummaryLoader = loadingPlaces || loadingSummary || (!!selectedPlace && !hasLoadedSummary);
  const showEmptySummaryState =
    !showSummaryLoader &&
    !summary &&
    !error &&
    !!selectedPlace &&
    hasLoadedSummary &&
    resolvedSummaryPlaceId === String(selectedPlace.id);
  const orderedTaxa = useMemo(() => {
    return [...taxa]
      .filter((item) => item?.raw_value != null)
      .sort((left, right) => {
        const leftDanger = Number(left?.danger_level ?? -1);
        const rightDanger = Number(right?.danger_level ?? -1);
        if (leftDanger !== rightDanger) {
          return rightDanger - leftDanger;
        }
        return String(left?.name_ru || "").localeCompare(String(right?.name_ru || ""), "ru");
      });
  }, [taxa]);

  useEffect(() => {
    const container = riskDisplayRef.current;
    const element = riskNumberRef.current;
    if (!container || !element || !riskLabel) return undefined;

    const rootFontSize = parseFloat(
      window.getComputedStyle(document.documentElement).fontSize || "16"
    );
    const computed = window.getComputedStyle(element);
    const fontFamily = computed.fontFamily || "sans-serif";
    const fontWeight = computed.fontWeight || "900";
    const fontStyle = computed.fontStyle || "normal";
    const letterSpacing = parseFloat(computed.letterSpacing || "0") || 0;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (!context) return undefined;

    const minFont = rootFontSize * 1.8;
    const maxFont = rootFontSize * 3.35;

    const measure = (fontSize) => {
      context.font = `${fontStyle} ${fontWeight} ${fontSize}px ${fontFamily}`;
      const textWidth = context.measureText(riskLabel).width;
      return textWidth + Math.max(0, riskLabel.length - 1) * letterSpacing;
    };

    const updateRiskFont = () => {
      const availableWidth = container.clientWidth;
      if (!availableWidth) return;

      let low = minFont;
      let high = maxFont;
      let best = minFont;

      for (let index = 0; index < 16; index += 1) {
        const mid = (low + high) / 2;
        if (measure(mid) <= availableWidth) {
          best = mid;
          low = mid;
        } else {
          high = mid;
        }
      }

      setRiskFontSize(Number(best.toFixed(2)));
    };

    updateRiskFont();

    const resizeObserver = new ResizeObserver(() => updateRiskFont());
    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, [riskLabel]);

  return (
    <div className="page-section home-page">
      {error && <div className="note">{error}</div>}

      {showSummaryLoader ? (
        <section className="card auth-loader-card" aria-live="polite">
          <div className="auth-loader-spinner" aria-hidden="true" />
          <div className="auth-loader-text">Загружаем сводку...</div>
        </section>
      ) : summary ? (
        <section className="home-hero">
          <div className="home-panel card">
            <div className="home-intro">
              <div className="home-heading-row">
                <h1 className="home-title">Текущая ситуация по пыльце</h1>

                <div className="home-heading-side">
                  <div
                    className="home-field home-place-picker home-heading-picker"
                    ref={placePickerRef}
                  >
                    <label htmlFor="home-location-select">Локация</label>
                    <input
                      id="home-location-select"
                      value={placeQuery}
                      onChange={(event) => {
                        setPlaceQuery(event.target.value);
                        setIsPlaceMenuOpen(true);
                      }}
                      onFocus={() => setIsPlaceMenuOpen(true)}
                      onClick={() => setIsPlaceMenuOpen(true)}
                      placeholder="Начните вводить название города, станции или региона"
                      disabled={loadingPlaces || places.length === 0}
                    />

                    {isPlaceMenuOpen ? (
                      <div className="home-place-menu">
                        {filteredPlaces.length > 0 ? (
                          filteredPlaces.map((place) => (
                            <button
                              key={place.id}
                              type="button"
                              className={`home-place-option${
                                String(place.id) === String(selectedPlaceId) ? " is-active" : ""
                              }`}
                              onMouseDown={(event) => event.preventDefault()}
                              onClick={() => applyPlaceSelection(place)}
                            >
                              {place.label || place.name}
                            </button>
                          ))
                        ) : (
                          <div className="home-place-empty">
                            По вашему запросу локации не найдены.
                          </div>
                        )}
                      </div>
                    ) : null}
                  </div>

                  <div className="home-field home-date-field">
                    <label>Дата данных</label>
                    <div className="home-date-pill">
                      <b>{formatDate(summary.time)}</b>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="home-snapshot">
              <article className="home-summary-card">
                <div className="home-summary-header">
                  <p className="summary-kicker">Сводка по локации</p>
                  <h2 className="home-summary-title">{locationName}</h2>
                </div>

                <div className="home-summary-meta">
                  <div>
                    Координаты: <strong>{locationCoords}</strong>
                  </div>
                </div>

                {usedSources.length > 0 && (
                  <div className="home-source-list">
                    {usedSources.map((source) => (
                      <span key={source} className={sourceBadgeClass(source)}>
                        {prettySourceName(source)}
                      </span>
                    ))}
                  </div>
                )}
              </article>

              <article className={riskCardClass(summary.overall?.color)}>
                <div className="home-risk-top">
                  <p className="home-risk-eyebrow">Уровень опасности</p>
                </div>

                <div ref={riskDisplayRef} className="home-risk-display">
                  <span
                    ref={riskNumberRef}
                    className="home-risk-number"
                    style={riskFontSize ? { fontSize: `${riskFontSize}px` } : undefined}
                  >
                    {riskLabel}
                  </span>
                </div>
              </article>
            </div>

            <div className="home-support-grid">
              <section className="home-subcard">
                <div className="home-subcard-header">
                  <h3 className="home-subcard-title">Основные аллергены</h3>
                </div>

                {orderedTaxa.length > 0 ? (
                  <div className="home-allergen-grid">
                    {orderedTaxa.map((taxon) => (
                      <article key={taxon.key} className="home-allergen-card">
                        <div className="home-allergen-head">
                          <div className="home-allergen-name">{taxon.name_ru}</div>
                          <div className="taxon-emoji">{taxon.emoji}</div>
                        </div>

                        <div className="home-allergen-value">
                          {taxon.raw_value == null ? "—" : taxon.raw_value}
                        </div>

                        <div className="home-allergen-meta">
                          Уровень опасности: {taxon.value_label || taxon.danger_label || "—"}
                        </div>
                        <div className="home-allergen-meta">{prettySourceName(taxon.source)}</div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="note note-muted">
                    Для выбранного города пока нет данных по аллергенам.
                  </div>
                )}
              </section>

              <section className="home-subcard">
                <div className="home-subcard-header">
                  <h3 className="home-subcard-title">Рекомендации</h3>
                  <p className="home-subcard-copy">
                    Короткие советы по текущему уровню риска.
                  </p>
                </div>

                {recommendations.length > 0 ? (
                  <ul className="home-recommend-list">
                    {recommendations.map((item, index) => (
                      <li key={index} className="home-recommend-item">
                        <span className="home-recommend-bullet">{index + 1}</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="note note-muted">
                    Рекомендации для этой сводки пока недоступны.
                  </div>
                )}
              </section>
            </div>
          </div>

          <Link to={mapLink} className="home-map-link" aria-label="Открыть карту и аналитику">
            <div className="home-map-card card">
              <div className="home-map-frame">
                <MapContainer
                  key={mapKey}
                  center={mapCenter}
                  zoom={homeMapZoom(selectedPlace)}
                  scrollWheelZoom={false}
                  dragging={false}
                  zoomControl={false}
                  doubleClickZoom={false}
                  touchZoom={false}
                  boxZoom={false}
                  keyboard={false}
                  attributionControl
                >
                  <MapAttributionCleaner />
                  <TileLayer
                    attribution="&copy; OpenStreetMap contributors"
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />
                  <Circle
                    center={mapCenter}
                    radius={4200}
                    pathOptions={{
                      color: "#2f7d57",
                      fillColor: "#2f7d57",
                      fillOpacity: 0.12,
                      weight: 2,
                    }}
                  />
                </MapContainer>

                <div className="home-map-caption">
                  <p className="home-map-caption-title">Открыть карту и аналитику</p>
                  <p className="home-map-caption-sub">
                    Карта слоев пыльцы, быстрые фильтры по локации и аллергену, плюс график
                    уровня опасности за 7 дней.
                  </p>
                </div>
              </div>
            </div>
          </Link>
        </section>
      ) : showEmptySummaryState ? (
        <section className="card">
          <div className="note">Нет данных для отображения сводки.</div>
        </section>
      ) : null}
    </div>
  );
}
