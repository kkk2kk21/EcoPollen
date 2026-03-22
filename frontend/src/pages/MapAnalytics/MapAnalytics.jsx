import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { canvas as leafletCanvas } from "leaflet";
import { useSearchParams } from "react-router-dom";
import {
  Circle,
  MapContainer,
  Pane,
  Rectangle,
  TileLayer,
  useMap,
} from "react-leaflet";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { requestJson } from "../../shared/api/http";
import MapAttributionCleaner from "../../shared/components/MapAttributionCleaner";
import { fetchMapPlaces } from "../../shared/api/mapPlaces";
import {
  clearPreferredMapPlace,
  readPreferredMapPlaceId,
  savePreferredMapPlace,
} from "../../shared/mapSelection";
import "./MapAnalytics.css";

const SOURCE_COLORS = {
  best: "#2f7d57",
  pgniu_manual: "#0ea5e9",
  meteoswiss: "#2563eb",
  norkko: "#0f766e",
  dwd: "#b45309",
  open_meteo: "#f97316",
};
const SOURCE_DISPLAY_NAMES = {
  pgniu_manual: "Замеры ПГНИУ",
  meteoswiss: "MeteoSwiss",
  norkko: "Norkko",
  dwd: "DWD",
  open_meteo: "Open-Meteo / CAMS",
  best: "Сводный индекс",
};

const DEFAULT_CONCENTRATION_THRESHOLDS = [1, 10, 25, 50, 100];
const MEASUREMENT_LEVEL_LABELS = [
  "Опасности нет",
  "Очень низкий",
  "Низкий",
  "Ощутимый",
  "Умеренный",
  "Значительный",
  "Высокий",
];
const MEASUREMENT_LEVEL_COLORS = [
  "#cbd5e1",
  "#86efac",
  "#4ade80",
  "#facc15",
  "#fb923c",
  "#ef4444",
  "#8b1e3f",
];
const INDEX_LEGEND_ITEMS = [
  { label: "Опасности нет", range: "0" },
  { label: "Очень низкий", range: "0-1" },
  { label: "Низкий", range: "1" },
  { label: "Ощутимый", range: "1-2" },
  { label: "Умеренный", range: "2" },
  { label: "Значительный", range: "2-3" },
  { label: "Высокий", range: "3" },
];
const DEFAULT_SOURCE_RADIUS_RULES = {
  pgniu_manual: { base: 5000, step: 3300 },
  norkko: { base: 5200, step: 2735 },
  meteoswiss: { base: 4800, step: 2535 },
  dwd: { base: 9000, step: 4335 },
  default: { base: 1200, step: 1065 },
};
const LAYER_CACHE_TTL_MS = 10 * 60 * 1000;
const TIMESERIES_CACHE_TTL_MS = 10 * 60 * 1000;
const LAYER_CACHE_MAX_ENTRIES = 96;
const TIMESERIES_CACHE_MAX_ENTRIES = 36;
const layerResponseCache = new Map();
const layerInflightRequests = new Map();
const timeseriesResponseCache = new Map();
const timeseriesInflightRequests = new Map();

const SOURCE_COVERAGE = {
  pgniu_manual: {
    label: "Все точки ПГНИУ",
    bbox: { min_lat: -90, max_lat: 90, min_lon: -180, max_lon: 180 },
    center: [58.0105, 56.2502],
    zoom: 6,
  },
  norkko: {
    label: "Финляндия",
    bbox: { min_lat: 59.5, max_lat: 70.5, min_lon: 20.0, max_lon: 31.5 },
    center: [64.5, 26.0],
    zoom: 5,
  },
  meteoswiss: {
    label: "Швейцария",
    bbox: { min_lat: 45.6, max_lat: 47.9, min_lon: 5.8, max_lon: 10.7 },
    center: [46.8, 8.2],
    zoom: 7,
  },
  dwd: {
    label: "Германия",
    bbox: { min_lat: 47.0, max_lat: 55.5, min_lon: 5.0, max_lon: 15.5 },
    center: [51.1, 10.2],
    zoom: 6,
  },
  open_meteo: {
    label: "Зона CAMS: Европейская часть СНГ",
    bbox: { min_lat: 38.0, max_lat: 72.0, min_lon: 19.0, max_lon: 45.0 },
    center: [54.5, 33.0],
    zoom: 4,
  },
};
const CITY_GROUP_LABEL = "Open-Meteo / CAMS";
const PGNIU_GROUP_LABEL = "Замеры ПГНИУ";

function todayISO() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isoDay(value) {
  if (!value) return null;
  const text = String(value).trim();
  if (!text) return null;
  return text.slice(0, 10);
}

function normalizeUnit(unit) {
  return String(unit || "").toLowerCase().trim();
}

function isConcentrationUnit(unit) {
  const normalized = normalizeUnit(unit);
  return normalized === "grains/m3" ||
    normalized === "grains/m³" ||
    normalized === "pollen/m3" ||
    normalized === "pollen/m³";
}

function isIndexUnit(unit) {
  const normalized = normalizeUnit(unit);
  return normalized === "index_0_3" ||
    normalized === "level_0_3" ||
    normalized === "score_0_3" ||
    normalized === "danger_0_3";
}

function valueCaptionForPoint(point) {
  if (isConcentrationUnit(point?.unit)) {
    return "Зёрна пыльцы/м³";
  }
  if (isIndexUnit(point?.unit)) {
    return "Значение индекса";
  }
  return "Значение";
}

function chartValueUnitLabel(unit) {
  if (isConcentrationUnit(unit)) {
    return "зёрен пыльцы/м³";
  }
  if (isIndexUnit(unit)) {
    return "значение индекса";
  }
  return "значение";
}

function formatChartNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  if (Number.isInteger(numeric)) return String(numeric);
  return numeric.toFixed(1).replace(".", ",");
}

function formatChartAxisDate(value) {
  if (!value) return "—";
  if (typeof value === "string") {
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) {
      return `${match[3]}.${match[2]}`;
    }
  }
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const day = String(date.getDate()).padStart(2, "0");
    const month = String(date.getMonth() + 1).padStart(2, "0");
    return `${day}.${month}`;
  } catch {
    return value;
  }
}

function chartLevelPhrase(point) {
  const label = point?.value_label || point?.danger_label || "";
  if (!label) return "";
  if (label === "Опасности нет") return label;
  return `${label} уровень`;
}

function seriesUnit(points) {
  const pointWithUnit = (points || []).find((item) => item?.unit);
  return pointWithUnit?.unit || null;
}

function sourceAxisId(unit) {
  return isIndexUnit(unit) ? "index" : "concentration";
}

function ChartTooltipContent({ active, label, payload, pointsByDate = {} }) {
  if (!active || !label) return null;

  const datePoints = pointsByDate[label] || [];
  if (datePoints.length === 0) return null;

  return (
    <div className="map-chart-tooltip">
      <div className="map-chart-tooltip-date">{label}</div>
      <div className="map-chart-tooltip-list">
        {datePoints.map((point) => {
          const unitLabel = chartValueUnitLabel(point.unit);
          const levelPhrase = chartLevelPhrase(point);
          const valueText = isIndexUnit(point.unit)
            ? `${unitLabel} ${formatChartNumber(point.raw_value)}`
            : `${formatChartNumber(point.raw_value)} ${unitLabel}`;

          return (
            <div key={`${label}-${point.source}`} className="map-chart-tooltip-row">
              <span
                className="map-chart-tooltip-dot"
                style={{ backgroundColor: lineColor(point.source) }}
                aria-hidden="true"
              />
              <span className="map-chart-tooltip-text">
                <b>{prettySourceName(point.source)}</b>: {valueText}
                {levelPhrase ? `, ${levelPhrase}` : ""}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function concentrationThresholdsForTaxon(taxon) {
  const thresholds = taxon?.legend?.concentration_thresholds;
  if (!Array.isArray(thresholds) || thresholds.length !== 5) {
    return DEFAULT_CONCENTRATION_THRESHOLDS;
  }
  const normalized = thresholds.map((value) => Number(value)).filter(Number.isFinite);
  return normalized.length === 5 ? normalized : DEFAULT_CONCENTRATION_THRESHOLDS;
}

function concentrationLevelIndex(value, thresholds) {
  if (value == null) return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  if (numeric <= 0) return 0;
  for (let index = 0; index < thresholds.length; index += 1) {
    if (numeric < thresholds[index]) return index + 1;
  }
  return MEASUREMENT_LEVEL_LABELS.length - 1;
}

function indexLevelIndex(value) {
  if (value == null) return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  if (numeric <= 0) return 0;
  if (numeric < 1) return 1;
  if (numeric === 1) return 2;
  if (numeric < 2) return 3;
  if (numeric === 2) return 4;
  if (numeric < 3) return 5;
  return 6;
}

function fallbackLevelIndex(dangerLevel) {
  const numeric = Number(dangerLevel);
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  if (numeric <= 1) return 2;
  if (numeric <= 2) return 4;
  return 6;
}

function measurementLevelIndex(value, unit, thresholds, dangerLevel = null) {
  if (isConcentrationUnit(unit)) {
    return concentrationLevelIndex(value, thresholds);
  }
  if (isIndexUnit(unit)) {
    return indexLevelIndex(value);
  }
  return fallbackLevelIndex(dangerLevel);
}

function levelColor(levelIndex) {
  const safeIndex = Math.max(
    0,
    Math.min(MEASUREMENT_LEVEL_COLORS.length - 1, Number(levelIndex || 0) || 0)
  );
  return MEASUREMENT_LEVEL_COLORS[safeIndex];
}

function formatLegendValue(value) {
  if (Number.isInteger(value)) return String(value);
  return String(value).replace(".", ",");
}

function buildConcentrationLegendItems(thresholds) {
  return [
    {
      label: MEASUREMENT_LEVEL_LABELS[0],
      range: "0",
      color: levelColor(0),
    },
    {
      label: MEASUREMENT_LEVEL_LABELS[1],
      range: `<${formatLegendValue(thresholds[0])}`,
      color: levelColor(1),
    },
    {
      label: MEASUREMENT_LEVEL_LABELS[2],
      range: `${formatLegendValue(thresholds[0])}-${formatLegendValue(thresholds[1] - 1)}`,
      color: levelColor(2),
    },
    {
      label: MEASUREMENT_LEVEL_LABELS[3],
      range: `${formatLegendValue(thresholds[1])}-${formatLegendValue(thresholds[2] - 1)}`,
      color: levelColor(3),
    },
    {
      label: MEASUREMENT_LEVEL_LABELS[4],
      range: `${formatLegendValue(thresholds[2])}-${formatLegendValue(thresholds[3] - 1)}`,
      color: levelColor(4),
    },
    {
      label: MEASUREMENT_LEVEL_LABELS[5],
      range: `${formatLegendValue(thresholds[3])}-${formatLegendValue(thresholds[4] - 1)}`,
      color: levelColor(5),
    },
    {
      label: MEASUREMENT_LEVEL_LABELS[6],
      range: `${formatLegendValue(thresholds[4])}+`,
      color: levelColor(6),
    },
  ];
}

function buildIndexLegendItems() {
  return INDEX_LEGEND_ITEMS.map((item, index) => ({
    ...item,
    color: levelColor(index),
  }));
}

function circleRadiusMeters(point, dangerLevel, sourceRadiusRules = DEFAULT_SOURCE_RADIUS_RULES) {
  const source = point?.source;
  const rule = sourceRadiusRules[source] || sourceRadiusRules.default || DEFAULT_SOURCE_RADIUS_RULES.default;
  const safeLevel = Math.max(0, Math.min(3, Number(dangerLevel || 0) || 0));
  return rule.base + safeLevel * rule.step;
}

function featureInfoFromItem(item) {
  const observedDay = isoDay(item.point.observed_at);
  return {
    key: item.key,
    title: item.point.location?.name || prettySourceName(item.source),
    sourceName: prettySourceName(item.source),
    effectiveDay: item.effectiveDay || "—",
    observedDay: observedDay || item.effectiveDay || "—",
    valueCaption: valueCaptionForPoint(item.point),
    value: item.point.raw_value ?? "—",
    levelLabel: item.point.value_label || item.point.danger_label || "",
    lat: Number(item.point.lat),
    lon: Number(item.point.lon),
    color: item.color,
  };
}

function estimateGridStep(points) {
  const lats = [...new Set(points.map((point) => Number(point.lat)).filter(Number.isFinite))].sort(
    (a, b) => a - b
  );
  const lons = [...new Set(points.map((point) => Number(point.lon)).filter(Number.isFinite))].sort(
    (a, b) => a - b
  );

  const minPositiveDelta = (values) => {
    let best = null;
    for (let index = 1; index < values.length; index += 1) {
      const delta = values[index] - values[index - 1];
      if (delta > 0 && (best == null || delta < best)) {
        best = delta;
      }
    }
    return best;
  };

  return {
    latStep: minPositiveDelta(lats) || 0,
    lonStep: minPositiveDelta(lons) || 0,
  };
}

function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/\s+/g, " ")
    .trim();
}

function isPgniuPlace(item) {
  return item?.source_key === "pgniu_manual";
}

function placeKindRank(item) {
  if (isPgniuPlace(item)) return 0;
  if (item?.kind === "city") return 1;
  if (item?.kind === "station") return 2;
  if (item?.kind === "region") return 3;
  return 4;
}

function placeBaseName(item) {
  return String(item?.name || item?.label || "");
}

function comparePlaceNames(left, right) {
  return placeBaseName(left).localeCompare(placeBaseName(right), "ru");
}

function groupLabelForPlace(item) {
  if (isPgniuPlace(item)) {
    return PGNIU_GROUP_LABEL;
  }
  if (item?.kind === "city") {
    return CITY_GROUP_LABEL;
  }
  return prettySourceName(item?.source_key) || String(item?.source_name || "Другой источник");
}

function comparePlacesForMenu(left, right, { keepPopulation = false } = {}) {
  const leftKindRank = placeKindRank(left);
  const rightKindRank = placeKindRank(right);
  if (leftKindRank !== rightKindRank) return leftKindRank - rightKindRank;

  if (leftKindRank > 1 && rightKindRank > 1) {
    const sourceCompare = groupLabelForPlace(left).localeCompare(groupLabelForPlace(right), "ru");
    if (sourceCompare !== 0) return sourceCompare;
  }

  if (keepPopulation) {
    const leftPopulation = Number(left?.population || 0);
    const rightPopulation = Number(right?.population || 0);
    if (leftPopulation !== rightPopulation) return rightPopulation - leftPopulation;
  }

  return comparePlaceNames(left, right);
}

function groupPlacesForMenu(places) {
  const groups = [];
  const seenGroups = new Map();

  for (const place of places || []) {
    const groupKind = place?.kind === "city" ? "country" : "source";
    const groupLabel = groupLabelForPlace(place);
    const groupKey = `${groupKind}:${normalizeSearchText(groupLabel) || "other"}`;
    let group = seenGroups.get(groupKey);

    if (!group) {
      group = {
        key: groupKey,
        label: groupLabel,
        items: [],
      };
      seenGroups.set(groupKey, group);
      groups.push(group);
    }

    group.items.push(place);
  }

  return groups;
}

function shouldUseGenericCityLookup(place) {
  return place?.kind === "city";
}

function filterLocalPlaces(places, query) {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) {
    return [...(places || [])].sort((left, right) =>
      comparePlacesForMenu(left, right)
    );
  }

  const splitIntoWords = (value) =>
    value.split(/[\s,().\-–—/]+/).filter(Boolean);

  const scorePlaceMatch = (item) => {
    const name = normalizeSearchText(item.name);
    const label = normalizeSearchText(item.label);
    const searchText = normalizeSearchText(item.search_text);
    const nameWords = splitIntoWords(name);
    const labelWords = splitIntoWords(label);
    const searchWords = splitIntoWords(searchText);

    if (name === normalizedQuery || label === normalizedQuery) return 0;
    if (name.startsWith(normalizedQuery)) return 1;
    if (label.startsWith(normalizedQuery)) return 2;
    if (nameWords.some((word) => word === normalizedQuery)) return 3;
    if (labelWords.some((word) => word === normalizedQuery)) return 4;
    if (nameWords.some((word) => word.startsWith(normalizedQuery))) return 5;
    if (labelWords.some((word) => word.startsWith(normalizedQuery))) return 6;
    if (name.includes(normalizedQuery)) return 7;
    if (label.includes(normalizedQuery)) return 8;
    if (searchWords.some((word) => word === normalizedQuery)) return 9;
    if (searchWords.some((word) => word.startsWith(normalizedQuery))) return 10;
    if (searchText.includes(normalizedQuery)) return 11;
    return null;
  };

  return (places || [])
    .map((item) => ({ item, score: scorePlaceMatch(item) }))
    .filter((item) => item.score != null)
    .sort((left, right) => {
      if (left.score !== right.score) return left.score - right.score;
      return comparePlacesForMenu(left.item, right.item, { keepPopulation: true });
    })
    .map((entry) => entry.item);
}

function layerBbox(layer) {
  if (layer.id === "open_meteo") {
    return SOURCE_COVERAGE.open_meteo?.bbox || null;
  }
  return null;
}

function layerCoverageLabel(layerId) {
  return SOURCE_COVERAGE[layerId]?.label || null;
}

function prettySourceName(key) {
  return SOURCE_DISPLAY_NAMES[key] || key;
}

function layerSubtitle(layerId, effectiveDay) {
  const parts = [];

  if (layerId === "pgniu_manual") {
    parts.push("Пермь");
  } else if (layerId === "open_meteo") {
    parts.push("Европейская часть СНГ");
  } else if (layerCoverageLabel(layerId)) {
    parts.push(layerCoverageLabel(layerId));
  }

  if (effectiveDay) {
    parts.push(effectiveDay);
  }

  return parts.join(" • ");
}

function cacheNumberPart(value, digits = 4) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "na";
  return numeric.toFixed(digits);
}

function readCachedValue(cache, key) {
  const entry = cache.get(key);
  if (!entry) return null;
  if (entry.expiresAt <= Date.now()) {
    cache.delete(key);
    return null;
  }
  cache.delete(key);
  cache.set(key, entry);
  return entry.data;
}

function trimCache(cache, maxEntries) {
  while (cache.size > maxEntries) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey == null) break;
    cache.delete(oldestKey);
  }
}

function writeCachedValue(cache, key, data, ttlMs, maxEntries) {
  cache.delete(key);
  cache.set(key, {
    data,
    expiresAt: Date.now() + ttlMs,
  });
  trimCache(cache, maxEntries);
  return data;
}

async function getCachedOrFetch({
  key,
  cache,
  inflight,
  ttlMs,
  maxEntries,
  fetcher,
}) {
  const cached = readCachedValue(cache, key);
  if (cached) return cached;

  if (inflight.has(key)) {
    return inflight.get(key);
  }

  const request = (async () => {
    const fresh = await fetcher();
    return writeCachedValue(cache, key, fresh, ttlMs, maxEntries);
  })();

  inflight.set(key, request);

  try {
    return await request;
  } finally {
    inflight.delete(key);
  }
}

function buildLayerCacheKey(layerId, taxonKey, day, queryBbox) {
  return JSON.stringify({
    version: 2,
    layerId,
    taxonKey,
    day,
    min_lat: cacheNumberPart(queryBbox?.min_lat),
    max_lat: cacheNumberPart(queryBbox?.max_lat),
    min_lon: cacheNumberPart(queryBbox?.min_lon),
    max_lon: cacheNumberPart(queryBbox?.max_lon),
  });
}

function buildTimeseriesCacheKey(selectedPlace, taxonKey) {
  return JSON.stringify({
    version: 1,
    taxonKey,
    days: 7,
    location_id: selectedPlace?.location_id ?? null,
    external_location_id: selectedPlace?.external_location_id ?? null,
    lat: cacheNumberPart(selectedPlace?.lat),
    lon: cacheNumberPart(selectedPlace?.lon),
    place_name: selectedPlace?.name || "",
  });
}

function initialSelectedLines(seriesList = []) {
  const initial = {};
  for (const series of seriesList) {
    initial[series.source] = true;
  }
  return initial;
}

function lineColor(source) {
  return SOURCE_COLORS[source] || "#475467";
}

function latestObservedDay(points = []) {
  let latest = null;
  for (const point of points) {
    const observedDay = isoDay(point?.observed_at);
    if (observedDay && (!latest || observedDay > latest)) {
      latest = observedDay;
    }
  }
  return latest;
}

function placeFocusZoom(place) {
  if (!place) return 6;
  if (place.kind === "region") return 7;
  if (place.kind === "station") return 10;
  return 11;
}

function emptyTimeseriesState() {
  return {
    days: [],
    series: [],
    best: [],
    note: "Выберите город, станцию или регион, чтобы построить график.",
  };
}

function MapViewportController({ points, fallbackView, focusPlace, focusToken }) {
  const map = useMap();
  const lastFocusTokenRef = useRef("");

  useEffect(() => {
    if (!map) return;

    if (focusPlace && focusToken) {
      if (lastFocusTokenRef.current !== focusToken) {
        lastFocusTokenRef.current = focusToken;
        map.flyTo(
          [Number(focusPlace.lat), Number(focusPlace.lon)],
          placeFocusZoom(focusPlace),
          { duration: 0.65 }
        );
      }
      return;
    }

    if (Array.isArray(points) && points.length > 1) {
      const bounds = points.map((item) => [
        Number(item.point.lat),
        Number(item.point.lon),
      ]);
      map.fitBounds(bounds, { padding: [36, 36] });
      return;
    }

    if (Array.isArray(points) && points.length === 1) {
      map.setView(
        [Number(points[0].point.lat), Number(points[0].point.lon)],
        Math.max(map.getZoom(), 7)
      );
      return;
    }

    map.setView(fallbackView.center, fallbackView.zoom);
  }, [fallbackView, focusPlace, focusToken, map, points]);

  return null;
}

function MapSizeInvalidator({ signal }) {
  const map = useMap();

  useEffect(() => {
    if (!map) return undefined;

    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 40);

    return () => clearTimeout(timer);
  }, [map, signal]);

  return null;
}

export default function MapAnalytics() {
  const [searchParams] = useSearchParams();
  const [taxa, setTaxa] = useState([]);
  const [places, setPlaces] = useState([]);
  const [selectedPlaceId, setSelectedPlaceId] = useState("");
  const [placeQuery, setPlaceQuery] = useState("");
  const [isPlaceMenuOpen, setIsPlaceMenuOpen] = useState(false);
  const [taxonKey, setTaxonKey] = useState("alder");
  const [day, setDay] = useState(todayISO);
  const [layers, setLayers] = useState([]);
  const [sourceRadiusRules, setSourceRadiusRules] = useState(DEFAULT_SOURCE_RADIUS_RULES);
  const [layerData, setLayerData] = useState({});
  const [layerDataSignature, setLayerDataSignature] = useState("");
  const [ts, setTs] = useState(() => emptyTimeseriesState());
  const [selectedLines, setSelectedLines] = useState({ best: true });
  const [error, setError] = useState("");
  const [selectedFeature, setSelectedFeature] = useState(null);
  const [mapFocusToken, setMapFocusToken] = useState("");
  const placePickerRef = useRef(null);
  const mapFrameRef = useRef(null);
  const layerRenderEpoch = useMemo(
    () =>
      `${taxonKey}|${day}|${selectedPlaceId || "no-place"}|${layers
        .filter((layer) => layer.enabled)
        .map((layer) => layer.id)
        .join(",")}`,
    [day, layers, selectedPlaceId, taxonKey]
  );
  const vectorRenderer = useMemo(
    () => leafletCanvas({ padding: 0 }),
    [layerRenderEpoch]
  );
  const [isMapFullscreen, setIsMapFullscreen] = useState(false);
  const [mapResizeToken, setMapResizeToken] = useState(0);
  const requestedPlaceId = searchParams.get("placeId") || "";

  const handleFeatureSelect = useCallback((item) => {
    setSelectedFeature(featureInfoFromItem(item));
  }, []);

  useEffect(() => {
    async function loadTaxa() {
      try {
        setError("");
        const data = await requestJson("/api/v1/taxa", {
          errorMessage: "Не удалось загрузить аллергены",
        });
        const items = Array.isArray(data) ? data : [];
        setTaxa(items);
      } catch (e) {
        setError(e.message || "Ошибка загрузки аллергенов");
      }
    }

    loadTaxa();
  }, []);

  useEffect(() => {
    if (taxa.length > 0 && !taxa.some((item) => item.key === taxonKey)) {
      setTaxonKey(taxa[0].key);
    }
  }, [taxa, taxonKey]);

  useEffect(() => {
    async function loadPlaces() {
      try {
        setError("");
        const items = await fetchMapPlaces();
        setPlaces(items);

        const preferredId = requestedPlaceId || readPreferredMapPlaceId();
        if (!preferredId) return;

        const preferredPlace = items.find((item) => String(item.id) === String(preferredId));
        if (!preferredPlace) return;

        setSelectedPlaceId(String(preferredPlace.id));
        setPlaceQuery(preferredPlace.label || preferredPlace.name || "");
        setMapFocusToken(`${preferredPlace.id}-${Date.now()}`);
        savePreferredMapPlace(preferredPlace);
      } catch (e) {
        setError(e.message || "Ошибка загрузки точек карты");
      }
    }

    loadPlaces();
  }, [requestedPlaceId]);

  useEffect(() => {
    async function loadCircleStyles() {
      try {
        const data = await requestJson("/api/v1/map-circle-styles", {
          errorMessage: "Не удалось загрузить стили карты",
        });
        const nextRules = { ...DEFAULT_SOURCE_RADIUS_RULES };

        for (const item of Array.isArray(data) ? data : []) {
          if (!item?.source_key || item.is_fallback) continue;
          nextRules[item.source_key] = {
            base: Number(item.base_radius_m) || DEFAULT_SOURCE_RADIUS_RULES[item.source_key]?.base || DEFAULT_SOURCE_RADIUS_RULES.default.base,
            step: Number(item.step_radius_m) || DEFAULT_SOURCE_RADIUS_RULES[item.source_key]?.step || DEFAULT_SOURCE_RADIUS_RULES.default.step,
          };
        }

        setSourceRadiusRules(nextRules);
      } catch (e) {
        setError((prev) => prev || e.message || "Ошибка загрузки стилей карты");
      }
    }

    loadCircleStyles();
  }, []);

  useEffect(() => {
    async function loadSources() {
      try {
        setError("");
        const data = await requestJson("/api/v1/sources", {
          errorMessage: "Не удалось загрузить источники",
        });
        const mapped = (Array.isArray(data) ? data : []).map((source) => {
          return {
            id: source.key,
            title: source.name,
            kind: "db",
            enabled: true,
          };
        });

        setLayers(mapped);
      } catch (e) {
        setError(e.message || "Ошибка загрузки источников");
      }
    }

    loadSources();
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
  const localPlaceOptions = useMemo(
    () => filterLocalPlaces(places, effectivePlaceQuery),
    [effectivePlaceQuery, places]
  );
  const localPlaceGroups = useMemo(
    () => groupPlacesForMenu(localPlaceOptions),
    [localPlaceOptions]
  );

  const selectedTaxon = useMemo(
    () => taxa.find((item) => item.key === taxonKey),
    [taxa, taxonKey]
  );
  const concentrationThresholds = useMemo(
    () => concentrationThresholdsForTaxon(selectedTaxon),
    [selectedTaxon]
  );

  const currentLayerSignature = useMemo(
    () =>
      JSON.stringify({
        taxonKey,
        day,
        layers: layers.map((layer) => ({
          id: layer.id,
          enabled: Boolean(layer.enabled),
        })),
      }),
    [day, layers, taxonKey]
  );
  const visibleLayerData = useMemo(
    () => (layerDataSignature === currentLayerSignature ? layerData : {}),
    [currentLayerSignature, layerData, layerDataSignature]
  );

  const singleExternalCoverage = useMemo(() => {
    const enabledNonLocal = layers.filter(
      (layer) =>
        layer.enabled &&
        layer.id !== "pgniu_manual" &&
        SOURCE_COVERAGE[layer.id]
    );

    if (enabledNonLocal.length !== 1) return null;
    return SOURCE_COVERAGE[enabledNonLocal[0].id];
  }, [layers]);

  const mapView = useMemo(() => {
    if (singleExternalCoverage) {
      return {
        center: singleExternalCoverage.center,
        zoom: singleExternalCoverage.zoom,
      };
    }
    return {
      center: SOURCE_COVERAGE.open_meteo.center,
      zoom: SOURCE_COVERAGE.open_meteo.zoom,
    };
  }, [singleExternalCoverage]);

  const mapViewKey = useMemo(
    () => `${mapView.center.join("-")}-${mapView.zoom}`,
    [mapView]
  );

  function handlePlaceInputChange(event) {
    setPlaceQuery(event.target.value);
    setIsPlaceMenuOpen(true);
  }

  function applyPlaceSelection(place) {
    if (!place) {
      setSelectedPlaceId("");
      setPlaceQuery("");
      setMapFocusToken("");
      setIsPlaceMenuOpen(false);
      clearPreferredMapPlace();
      return;
    }

    setSelectedPlaceId(String(place.id));
    setPlaceQuery(place.label || place.name || "");
    setMapFocusToken(`${place.id}-${Date.now()}`);
    setIsPlaceMenuOpen(false);
    savePreferredMapPlace(place);
  }

  useEffect(() => {
    function handlePointerDown(event) {
      if (!placePickerRef.current?.contains(event.target)) {
        setIsPlaceMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  useEffect(() => {
    function handleFullscreenChange() {
      const isActive = document.fullscreenElement === mapFrameRef.current;
      setIsMapFullscreen(isActive);
      setMapResizeToken((value) => value + 1);
    }

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const requestSignature = currentLayerSignature;

    async function loadLayerPoints() {
      if (layers.length === 0) return;

      try {
        setError("");
        const enabledLayers = layers.filter((layer) => layer.enabled);

        if (enabledLayers.length === 0) {
          if (!cancelled) {
            setLayerData({});
            setLayerDataSignature(requestSignature);
          }
          return;
        }

        const results = await Promise.all(
          enabledLayers.map(async (layer) => {
            let query;
            let url;
            const queryBbox = layerBbox(layer);

            const cacheKey = buildLayerCacheKey(layer.id, taxonKey, day, queryBbox);
            const cachedData = await getCachedOrFetch({
              key: cacheKey,
              cache: layerResponseCache,
              inflight: layerInflightRequests,
              ttlMs: LAYER_CACHE_TTL_MS,
              maxEntries: LAYER_CACHE_MAX_ENTRIES,
              fetcher: async () => {
                query = new URLSearchParams({
                  source_key: layer.id,
                  taxon_key: taxonKey,
                  day,
                });
                if (queryBbox) {
                  query.set("min_lat", String(queryBbox.min_lat));
                  query.set("max_lat", String(queryBbox.max_lat));
                  query.set("min_lon", String(queryBbox.min_lon));
                  query.set("max_lon", String(queryBbox.max_lon));
                }
                url = `/api/v1/heatmap/db?${query.toString()}`;

                const data = await requestJson(url, {
                  errorMessage: `Не удалось загрузить слой ${layer.id}`,
                });
                let points = Array.isArray(data.points) ? data.points : [];

                if (layer.id === "pgniu_manual") {
                  points = points.filter((point) => point.location?.kind === "trap");
                }

                return {
                  points,
                  effectiveDay: data.effective_day || latestObservedDay(points) || data.day || day,
                  note: data.note || "",
                };
              },
            });

            return [layer.id, cachedData];
          }),
        );

        if (cancelled) return;

        const nextLayerData = {};
        for (const [id, data] of results) {
          nextLayerData[id] = data;
        }

        setLayerData(nextLayerData);
        setLayerDataSignature(requestSignature);
      } catch (e) {
        if (!cancelled) {
          setError(e.message || "Ошибка загрузки слоев");
        }
      }
    }

    loadLayerPoints();

    return () => {
      cancelled = true;
    };
  }, [currentLayerSignature, day, layers, taxonKey]);

  useEffect(() => {
    let cancelled = false;

    async function loadTimeseries() {
      if (!selectedPlace) {
        if (!cancelled) {
          setTs(emptyTimeseriesState());
          setSelectedLines({});
        }
        return;
      }

      try {
        setError("");
        const cacheKey = buildTimeseriesCacheKey(selectedPlace, taxonKey);
        const data = await getCachedOrFetch({
          key: cacheKey,
          cache: timeseriesResponseCache,
          inflight: timeseriesInflightRequests,
          ttlMs: TIMESERIES_CACHE_TTL_MS,
          maxEntries: TIMESERIES_CACHE_MAX_ENTRIES,
          fetcher: async () => {
            const query = new URLSearchParams({
              taxon_key: taxonKey,
              days: "7",
              end_day: day,
            });
            if (selectedPlace.location_id && !shouldUseGenericCityLookup(selectedPlace)) {
              query.set("location_id", String(selectedPlace.location_id));
            }
            if (selectedPlace.external_location_id) {
              query.set("external_location_id", String(selectedPlace.external_location_id));
            }
            if (
              !selectedPlace.location_id ||
              selectedPlace.external_location_id ||
              shouldUseGenericCityLookup(selectedPlace)
            ) {
              query.set("lat", String(selectedPlace.lat));
              query.set("lon", String(selectedPlace.lon));
              query.set("place_name", selectedPlace.name);
            }
            return requestJson(`/api/v1/timeseries?${query.toString()}`, {
              errorMessage: "Не удалось загрузить график",
            });
          },
        });

        if (cancelled) return;

        setTs(data);
        setSelectedLines(initialSelectedLines(data.series || []));
      } catch (e) {
        if (!cancelled) {
          setError(e.message || "Ошибка загрузки графика");
        }
      }
    }

    loadTimeseries();

    return () => {
      cancelled = true;
    };
  }, [selectedPlace, taxonKey]);

  const activeLayers = useMemo(
    () => layers.filter((layer) => layer.enabled),
    [layers]
  );
  const legendKinds = useMemo(() => {
    const units = new Set();
    for (const layer of activeLayers) {
      for (const point of visibleLayerData[layer.id]?.points || []) {
        units.add(normalizeUnit(point.unit));
      }
    }

    return {
      hasConcentration: [...units].some((unit) => isConcentrationUnit(unit)),
      hasIndex: [...units].some((unit) => isIndexUnit(unit)),
    };
  }, [activeLayers, visibleLayerData]);
  const concentrationLegendItems = useMemo(
    () => buildConcentrationLegendItems(concentrationThresholds),
    [concentrationThresholds]
  );
  const indexLegendItems = useMemo(() => buildIndexLegendItems(), []);

  const layerGroups = useMemo(() => {
      return activeLayers.map((layer, layerIndex) => {
        const groupData = visibleLayerData[layer.id] || {
          points: [],
          effectiveDay: day,
          note: "",
        };
        const sourcePoints = groupData.points || [];
        const useGridCells = layer.id === "open_meteo";
        const { latStep, lonStep } = useGridCells
          ? estimateGridStep(sourcePoints)
          : { latStep: 0, lonStep: 0 };

        const visiblePoints = sourcePoints
          .map((point, index) => {
            const rawValue = point.raw_value;
            const numericValue = Number(rawValue);
            if (rawValue == null || !Number.isFinite(numericValue)) return null;
            const isZeroValue = numericValue === 0;

            const levelIndex = measurementLevelIndex(
              rawValue,
              point.unit,
              concentrationThresholds,
              point.danger_level
            );
            if (levelIndex == null) return null;

            const sizeLevel = Math.max(
              0,
              Math.min(3, Number(point.danger_level || 0) || 0)
            );

            return {
              key: `${layerRenderEpoch}-${layer.id}-${index}-${point.lat}-${point.lon}`,
              source: layer.id,
              effectiveDay: groupData.effectiveDay,
              point,
              levelIndex,
              sizeLevel,
              isZeroValue,
              useGridCell: useGridCells && latStep > 0 && lonStep > 0,
              cellBounds:
                useGridCells && latStep > 0 && lonStep > 0
                  ? [
                      [
                        Number(point.lat) - latStep * 0.5,
                        Number(point.lon) - lonStep * 0.5,
                      ],
                      [
                        Number(point.lat) + latStep * 0.5,
                        Number(point.lon) + lonStep * 0.5,
                      ],
                    ]
                  : null,
              color: levelColor(levelIndex),
              radius: circleRadiusMeters({ ...point, source: layer.id }, sizeLevel, sourceRadiusRules),
            };
          })
          .filter(Boolean);

        return {
          id: layer.id,
          title: layer.title,
          paneName: `source-pane-${layer.id}`,
          paneZIndex: 420 + layerIndex,
          effectiveDay: groupData.effectiveDay,
          note: groupData.note,
          rawCount: sourcePoints.length,
          visibleCount: visiblePoints.length,
          points: visiblePoints,
          renderEpoch: layerRenderEpoch,
        };
      });
  }, [activeLayers, concentrationThresholds, day, layerRenderEpoch, sourceRadiusRules, visibleLayerData]);

  const renderedPoints = useMemo(
    () => layerGroups.flatMap((group) => group.points),
    [layerGroups]
  );

  useEffect(() => {
    setSelectedFeature(null);
  }, [day, selectedPlaceId, taxonKey]);

  useEffect(() => {
    if (!selectedFeature?.key) return;
    const featureExists = renderedPoints.some((item) => item.key === selectedFeature.key);
    if (!featureExists) {
      setSelectedFeature(null);
    }
  }, [renderedPoints, selectedFeature]);

  const chartData = useMemo(() => {
    if (!ts) return [];

    return (ts.days || []).map((date, index) => {
      const row = { date };
      for (const series of ts.series || []) {
        row[`src_${series.source}`] = series.points?.[index]?.raw_value ?? null;
      }
      return row;
    });
  }, [ts]);

  const chartPointLookup = useMemo(() => {
    const byDate = {};
    for (const series of ts?.series || []) {
      for (const point of series.points || []) {
        if (point?.date == null) continue;
        byDate[point.date] = byDate[point.date] || [];
        if (point.raw_value == null) continue;
        byDate[point.date].push({ ...point, source: series.source });
      }
    }
    return byDate;
  }, [ts]);

  const chartHasConcentration = useMemo(
    () =>
      (ts?.series || []).some(
        (series) =>
          selectedLines[series.source] &&
          isConcentrationUnit(seriesUnit(series.points))
      ),
    [selectedLines, ts]
  );

  const chartHasIndex = useMemo(
    () =>
      (ts?.series || []).some(
        (series) =>
          selectedLines[series.source] &&
          isIndexUnit(seriesUnit(series.points))
      ),
    [selectedLines, ts]
  );

  function toggleLayer(id) {
    setLayers((prev) =>
      prev.map((layer) =>
        layer.id === id ? { ...layer, enabled: !layer.enabled } : layer
      )
    );
  }

  function toggleLine(key) {
    setSelectedLines((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function toggleMapFullscreen() {
    const frame = mapFrameRef.current;
    if (!frame) return;

    try {
      if (document.fullscreenElement === frame) {
        await document.exitFullscreen();
      } else {
        await frame.requestFullscreen();
      }
    } catch (e) {
      setError((prev) => prev || e.message || "Не удалось переключить полноэкранный режим карты");
    }
  }

  return (
    <div className="map-page">
      <header className="map-page-header">
        <div className="map-page-copy">
          <h2 className="section-title map-page-title">Карта и аналитика</h2>
          <p className="section-subtitle">
            Карта слоев пыльцы, фильтры по локации и аллергену, плюс
            график уровня опасности за 7 дней.
          </p>
        </div>
      </header>

      {error && <div className="note">{error}</div>}

      <section className="map-layout">
        <section className="map-chart map-chart-panel card">
          <div className="map-chart-head">
            <h3 className="section-title map-chart-title">График за 7 дней</h3>
            <p className="section-subtitle">
              {selectedPlace
                ? `История уровня опасности для ${selectedPlace.label || selectedPlace.name}.`
                : "История уровня опасности для выбранной локации."}
            </p>
          </div>

          {ts ? (
            <>
              {ts.note ? <div className="note note-muted">{ts.note}</div> : null}

              <div className="map-chart-toggles">
                {(ts.series || []).map((series) => (
                  <label
                    key={series.source}
                    className={`map-chart-toggle${
                      selectedLines[series.source] ? " active" : ""
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={!!selectedLines[series.source]}
                      onChange={() => toggleLine(series.source)}
                    />
                    {prettySourceName(series.source)}
                  </label>
                ))}
              </div>

              {chartData.length > 0 ? (
                <div className="map-chart-shell">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={chartData}
                      margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid stroke="#e2e8f0" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tickLine={false}
                        axisLine={false}
                        stroke="#6b7280"
                        tickFormatter={formatChartAxisDate}
                      />
                      {chartHasConcentration ? (
                        <YAxis
                          yAxisId="concentration"
                          tickLine={false}
                          axisLine={false}
                          stroke="#6b7280"
                          width={48}
                        />
                      ) : null}
                      {chartHasIndex ? (
                        <YAxis
                          yAxisId="index"
                          orientation="right"
                          tickLine={false}
                          axisLine={false}
                          stroke="#6b7280"
                          domain={[0, 3]}
                          width={38}
                          ticks={[0, 1, 2, 3]}
                        />
                      ) : null}
                      <ReTooltip
                        content={
                          <ChartTooltipContent pointsByDate={chartPointLookup} />
                        }
                      />

                      {(ts.series || []).map((series) => {
                        const key = `src_${series.source}`;
                        if (!selectedLines[series.source]) return null;
                        const unit = seriesUnit(series.points);

                        return (
                          <Line
                            key={series.source}
                            type="monotone"
                            dataKey={key}
                            name={prettySourceName(series.source)}
                            stroke={lineColor(series.source)}
                            strokeWidth={2}
                            dot={false}
                            connectNulls={false}
                            yAxisId={sourceAxisId(unit)}
                          />
                        );
                      })}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="map-empty">
                  Для выбранных параметров пока нет данных графика.
                </div>
              )}
            </>
          ) : (
            <div className="map-empty">График загружается...</div>
          )}
        </section>

        <div className="map-canvas card">
          <div className="map-canvas-frame" ref={mapFrameRef}>
            <MapContainer
              key={mapViewKey}
              center={mapView.center}
              zoom={mapView.zoom}
              scrollWheelZoom
              attributionControl
              preferCanvas
              zoomControl={false}
            >
              <MapAttributionCleaner />
              <MapSizeInvalidator signal={mapResizeToken} />
              <TileLayer
                attribution="&copy; OpenStreetMap contributors"
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              <MapViewportController
                points={renderedPoints}
                fallbackView={mapView}
                focusPlace={selectedPlace}
                focusToken={mapFocusToken}
              />
              {layerGroups.map((group) => (
                <Pane
                  key={`${group.paneName}-${group.renderEpoch}`}
                  name={group.paneName}
                  style={{ zIndex: group.paneZIndex }}
                >
                  {group.points.map((item) => {
                    if (item.useGridCell) {
                      const isSelected = item.key === selectedFeature?.key;
                      return (
                        <Rectangle
                          key={item.key}
                          bounds={item.cellBounds}
                          renderer={vectorRenderer}
                          eventHandlers={{
                            click: () => handleFeatureSelect(item),
                          }}
                          pathOptions={{
                            color: isSelected ? "#18212f" : item.color,
                            fillColor: item.color,
                            fillOpacity: item.isZeroValue ? 0.14 : 0.28,
                            weight: isSelected ? 2 : 0,
                          }}
                        />
                      );
                    }

                    const isSelected = item.key === selectedFeature?.key;
                    return (
                      <Circle
                        key={item.key}
                        center={[Number(item.point.lat), Number(item.point.lon)]}
                        radius={item.radius}
                        renderer={vectorRenderer}
                        eventHandlers={{
                          click: () => handleFeatureSelect(item),
                        }}
                        pathOptions={{
                          color: isSelected ? "#18212f" : item.color,
                          fillColor: item.color,
                          fillOpacity: item.isZeroValue ? 0.1 : 0.16,
                          weight: isSelected ? 2.5 : item.isZeroValue ? 1 : 1.5,
                        }}
                      />
                    );
                  })}
                </Pane>
              ))}
            </MapContainer>

            <div className="map-canvas-toolbar">
              <div className="map-toolbar-group">
                <span className="badge">
                  {selectedTaxon?.name_ru || "Аллерген"} • {day}
                </span>
                <span className="badge">Точек на карте: {renderedPoints.length}</span>
              </div>

              <div className="map-toolbar-group">
                <button
                  type="button"
                  className="secondary map-toolbar-button"
                  onClick={toggleMapFullscreen}
                >
                  {isMapFullscreen ? "Свернуть карту" : "Развернуть карту"}
                </button>
              </div>
            </div>

            <div className="map-hover-info" aria-live="polite">
              {selectedFeature ? (
                <>
                  <div className="map-hover-head">
                    <span
                      className="map-hover-color"
                      style={{ backgroundColor: selectedFeature.color }}
                    />
                    <b>{selectedFeature.title}</b>
                  </div>
                  <div>Источник: {selectedFeature.sourceName}</div>
                  <div>Дата наблюдения: {selectedFeature.observedDay}</div>
                  <div>{selectedFeature.valueCaption}: {selectedFeature.value}</div>
                  {selectedFeature.levelLabel ? (
                    <div>Уровень опасности: {selectedFeature.levelLabel}</div>
                  ) : null}
                  <div className="map-hover-coords">
                    {Number.isFinite(selectedFeature.lat) && Number.isFinite(selectedFeature.lon)
                      ? `${selectedFeature.lat.toFixed(3)}, ${selectedFeature.lon.toFixed(3)}`
                      : ""}
                  </div>
                </>
              ) : (
                <div className="map-hover-empty">
                  Нажмите на ячейку или точку слоя для получения подробностей
                </div>
              )}
            </div>
          </div>
        </div>

        <aside className="map-sidebar card">
          <div className="map-sidebar-header">
            <h3 className="map-sidebar-title">Фильтры карты</h3>
            <p className="map-sidebar-copy">
              Управляйте локацией, аллергеном, датой и видимыми источниками.
            </p>
          </div>

          <div className="map-fields">
            <div className="map-field">
              <label htmlFor="map-location-search">Город или точка</label>
              <div className="map-place-picker" ref={placePickerRef}>
                <input
                  id="map-location-search"
                  aria-label="Поиск по списку городов, станций и регионов"
                  value={placeQuery}
                  onChange={handlePlaceInputChange}
                  onFocus={() => setIsPlaceMenuOpen(true)}
                  onClick={() => setIsPlaceMenuOpen(true)}
                  placeholder="Поиск по городам, станциям и регионам"
                  autoComplete="off"
                />
                {isPlaceMenuOpen ? (
                  <div className="map-place-menu" role="listbox">
                    <button
                      type="button"
                      className={`map-place-option map-place-option-clear${
                        !selectedPlaceId ? " is-active" : ""
                      }`}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => applyPlaceSelection(null)}
                    >
                      Все доступные точки на карте
                    </button>
                    {localPlaceGroups.length === 0 ? (
                      <div className="map-place-menu-empty">Ничего не найдено</div>
                    ) : (
                      <div className="map-place-list">
                        {localPlaceGroups.map((group) => (
                          <div key={group.key} className="map-place-group">
                            <div className="map-place-group-label">{group.label}</div>
                            {group.items.map((place) => (
                              <button
                                key={place.id}
                                type="button"
                                className={`map-place-option${
                                  String(place.id) === String(selectedPlaceId) ? " is-active" : ""
                                }`}
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={() => applyPlaceSelection(place)}
                              >
                                {place.label}
                              </button>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="map-field">
              <label htmlFor="map-taxon-select">Аллерген</label>
              <select
                id="map-taxon-select"
                value={taxonKey}
                onChange={(e) => setTaxonKey(e.target.value)}
              >
                {taxa.map((taxon) => (
                  <option key={taxon.key} value={taxon.key}>
                    {taxon.name_ru}
                  </option>
                ))}
              </select>
            </div>

            <div className="map-field">
              <label htmlFor="map-day-input">Дата</label>
              <input
                id="map-day-input"
                type="date"
                value={day}
                onChange={(e) => setDay(e.target.value)}
              />
            </div>
          </div>

          {legendKinds.hasConcentration ? (
            <div className="legend-block">
              <p className="legend-title">
                Концентрация {selectedTaxon?.name_ru || "аллергена"} (пыльца/м³)
              </p>
              <p className="legend-copy">
                Пороговые диапазоны для выбранного аллергена.
              </p>
              <div className="legend-list">
                {concentrationLegendItems.map((item) => (
                  <div key={`conc-${item.label}`} className="legend-row">
                    <span
                      className="legend-swatch"
                      style={{ backgroundColor: item.color }}
                      aria-hidden="true"
                    />
                    <div className="legend-row-main">
                      <span className="legend-row-label">{item.label}</span>
                      <span className="legend-row-range">{item.range}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {legendKinds.hasIndex ? (
            <div className="legend-block">
              <p className="legend-title">Индексные источники</p>
              <p className="legend-copy">
                Для DWD и Norkko шкала задаётся индексом, а не числом пыльцы на м³.
              </p>
              <div className="legend-list">
                {indexLegendItems.map((item) => (
                  <div key={`idx-${item.range}`} className="legend-row">
                    <span
                      className="legend-swatch"
                      style={{ backgroundColor: item.color }}
                      aria-hidden="true"
                    />
                    <div className="legend-row-main">
                      <span className="legend-row-label">{item.label}</span>
                      <span className="legend-row-range">{item.range}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="stack">
            <p className="legend-title">Источники и слои</p>
            <div className="layer-list">
              {layers.map((layer) => {
                const group = layerGroups.find((item) => item.id === layer.id);
                const pointCount = group?.visibleCount ?? 0;
                const effectiveDay = group?.effectiveDay;
                return (
                <div key={layer.id} className="layer-item">
                  <input
                    type="checkbox"
                    checked={layer.enabled}
                    onChange={() => toggleLayer(layer.id)}
                    aria-label={`Переключить слой ${layer.title}`}
                  />

                  <div className="layer-item-main">
                    <div className="layer-item-title">{layer.title}</div>
                    {layerSubtitle(layer.id, effectiveDay) ? (
                      <div className="layer-item-sub">
                        {layerSubtitle(layer.id, effectiveDay)}
                      </div>
                    ) : null}
                  </div>

                  <span className="badge">
                    {pointCount}
                  </span>
                </div>
                );
              })}
            </div>
          </div>
        </aside>
      </section>
    </div>
  );
}
