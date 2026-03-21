import { divIcon } from "leaflet";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  Marker,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { apiFetch, clearToken, getToken } from "../../shared/api/auth";
import { requestJson } from "../../shared/api/http";
import MapAttributionCleaner from "../../shared/components/MapAttributionCleaner";
import "./ScienceCabinet.css";

function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function parseCoordinate(value) {
  const normalized = String(value ?? "").replace(",", ".").trim();
  if (!normalized) return null;
  const numeric = Number(normalized);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatCoordinate(value) {
  return Number(value).toFixed(5);
}

function sortTrapLocations(items) {
  return [...items].sort((left, right) =>
    String(left?.name || "").localeCompare(String(right?.name || ""), "ru")
  );
}

function trapOptionLabel(item) {
  return `${item.name} • ${Number(item.lat).toFixed(4)}, ${Number(item.lon).toFixed(4)}`;
}

const NEW_TRAP_ICON = divIcon({
  className: "science-trap-marker",
  html: '<span class="science-trap-marker-pin"></span>',
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

function TrapMapViewport({ locations, locMode, selectedTrap, draftPosition }) {
  const map = useMap();
  const hasInitialFitRef = useRef(false);

  useEffect(() => {
    if (!map) return;

    const trapPoints = locations
      .map((loc) => [Number(loc.lat), Number(loc.lon)])
      .filter(([lat, lon]) => Number.isFinite(lat) && Number.isFinite(lon));

    if (!hasInitialFitRef.current) {
      const initialPoints = draftPosition
        ? [...trapPoints, [draftPosition.lat, draftPosition.lon]]
        : trapPoints;

      if (initialPoints.length > 1) {
        map.fitBounds(initialPoints, { padding: [36, 36] });
      } else if (initialPoints.length === 1) {
        map.setView(initialPoints[0], 11);
      } else {
        map.setView([58.0105, 56.2502], 6);
      }

      hasInitialFitRef.current = true;
      return;
    }

    if (locMode === "new" && draftPosition) {
      map.flyTo([draftPosition.lat, draftPosition.lon], Math.max(map.getZoom(), 8), {
        animate: true,
        duration: 0.35,
      });
      return;
    }

    if (locMode === "edit" && selectedTrap) {
      map.flyTo([Number(selectedTrap.lat), Number(selectedTrap.lon)], Math.max(map.getZoom(), 10), {
        animate: true,
        duration: 0.35,
      });
    }
  }, [draftPosition, locMode, locations, map, selectedTrap]);

  return null;
}

function TrapMapPicker({ enabled, onPickPosition }) {
  useMapEvents({
    click(event) {
      if (!enabled) return;
      onPickPosition(event.latlng.lat, event.latlng.lng);
    },
  });

  return null;
}

export default function ScienceCabinet() {
  const [taxa, setTaxa] = useState([]);
  const [me, setMe] = useState(null);
  const [meErr, setMeErr] = useState("");

  const [locations, setLocations] = useState([]);
  const [locMode, setLocMode] = useState("select"); // режим работы с ловушкой: select | edit | new
  const [locationId, setLocationId] = useState("");
  const [editTrapId, setEditTrapId] = useState("");
  const [deleteTrapId, setDeleteTrapId] = useState("");
  const [showDeleteTrapPanel, setShowDeleteTrapPanel] = useState(false);
  const [trapName, setTrapName] = useState("Ловушка ПГНИУ");
  const [trapLat, setTrapLat] = useState("58.0105");
  const [trapLon, setTrapLon] = useState("56.2502");
  const [trapStatus, setTrapStatus] = useState("");
  const [deleteTrapStatus, setDeleteTrapStatus] = useState("");

  const [day, setDay] = useState(todayISO());
  const [values, setValues] = useState({});
  const [circleStyles, setCircleStyles] = useState([]);
  const [timeseriesDistanceSettings, setTimeseriesDistanceSettings] = useState([]);
  const [styleStatus, setStyleStatus] = useState("");
  const [distanceStatus, setDistanceStatus] = useState("");

  const [status, setStatus] = useState("");
  const [history, setHistory] = useState([]);
  const [historyErr, setHistoryErr] = useState("");
  const [historyOnlySelected, setHistoryOnlySelected] = useState(false);
  const [historyTableHeight, setHistoryTableHeight] = useState(null);
  const allergenCardRef = useRef(null);

  const canEdit = useMemo(() => me?.role === "admin" || me?.role === "scientist", [me]);
  const selectedTrap = useMemo(
    () => locations.find((loc) => String(loc.id) === String(locationId)) || null,
    [locationId, locations]
  );
  const editTrap = useMemo(
    () => locations.find((loc) => String(loc.id) === String(editTrapId)) || null,
    [editTrapId, locations]
  );
  const deleteTrap = useMemo(
    () => locations.find((loc) => String(loc.id) === String(deleteTrapId)) || null,
    [deleteTrapId, locations]
  );
  const draftPosition = useMemo(() => {
    const lat = parseCoordinate(trapLat);
    const lon = parseCoordinate(trapLon);
    if (lat == null || lon == null) return null;
    return { lat, lon };
  }, [trapLat, trapLon]);
  const filledValuesCount = useMemo(
    () =>
      taxa.reduce((count, taxon) => {
        return String(values[taxon.key] ?? "").trim() ? count + 1 : count;
      }, 0),
    [taxa, values]
  );

  async function refreshTrapLocations(preferred = {}) {
    const locs = await requestJson("/api/v1/locations", {
      errorMessage: "Не удалось загрузить список ловушек",
    });
    const traps = sortTrapLocations((locs || []).filter((item) => item.kind === "trap"));
    setLocations(traps);

    const currentSelectedId = preferred.selectedId ?? locationId;
    if (currentSelectedId && traps.some((item) => String(item.id) === String(currentSelectedId))) {
      setLocationId(String(currentSelectedId));
    } else if (traps.length > 0) {
      setLocationId(String(traps[0].id));
    } else {
      setLocationId("");
    }

    const currentEditId = preferred.editId ?? editTrapId;
    if (currentEditId && traps.some((item) => String(item.id) === String(currentEditId))) {
      setEditTrapId(String(currentEditId));
    } else {
      setEditTrapId(traps.length > 0 ? String(traps[0].id) : "");
    }

    const currentDeleteId = preferred.deleteId ?? deleteTrapId;
    if (currentDeleteId && traps.some((item) => String(item.id) === String(currentDeleteId))) {
      setDeleteTrapId(String(currentDeleteId));
    } else {
      setDeleteTrapId(traps.length > 0 ? String(traps[0].id) : "");
    }

    return traps;
  }

  useEffect(() => {
    requestJson("/api/v1/taxa", {
      errorMessage: "Не удалось загрузить список аллергенов",
    })
      .then((items) => {
        const nextTaxa = Array.isArray(items) ? items : [];
        setTaxa(nextTaxa);
        setValues((prev) =>
          Object.fromEntries(nextTaxa.map((taxon) => [taxon.key, prev[taxon.key] ?? ""]))
        );
      })
      .catch(() => setTaxa([]));
  }, []);

  useEffect(() => {
    if (!getToken()) {
      setMeErr("Нужно войти (/login).");
      return;
    }
    apiFetch("/api/v1/auth/me")
      .then(setMe)
      .catch((e) => setMeErr(String(e)));
  }, []);

  useEffect(() => {
    refreshTrapLocations().catch(() => setLocations([]));
  }, []);

  useEffect(() => {
    if (locMode !== "edit" || !editTrap) return;
    setTrapName(editTrap.name || "");
    setTrapLat(formatCoordinate(editTrap.lat));
    setTrapLon(formatCoordinate(editTrap.lon));
  }, [editTrap, locMode]);

  useEffect(() => {
    const element = allergenCardRef.current;
    if (!element || typeof ResizeObserver === "undefined") return undefined;

    const updateHeight = () => {
      const nextHeight = Math.round(element.getBoundingClientRect().height);
      setHistoryTableHeight(nextHeight > 0 ? nextHeight : null);
    };

    updateHeight();

    const observer = new ResizeObserver(() => {
      updateHeight();
    });
    observer.observe(element);

    return () => observer.disconnect();
  }, [taxa.length, filledValuesCount, status]);

  async function loadHistory() {
    setHistoryErr("");
    try {
      const query = new URLSearchParams({
        day,
        limit: "200",
      });
      if (historyOnlySelected && selectedTrap) {
        query.set("location_id", String(selectedTrap.id));
      }
      const rows = await apiFetch(`/api/v1/science/measurements?${query.toString()}`);
      setHistory(rows || []);
    } catch (e) {
      setHistoryErr(String(e));
    }
  }

  useEffect(() => {
    if (canEdit) loadHistory();
  }, [canEdit, day, historyOnlySelected, selectedTrap]);

  useEffect(() => {
    async function loadCircleStyles() {
      if (!canEdit) return;
      try {
        const items = await apiFetch("/api/v1/science/map-circle-styles");
        setCircleStyles((Array.isArray(items) ? items : []).filter((item) => !item.is_fallback));
      } catch (e) {
        setStyleStatus(String(e));
      }
    }

    loadCircleStyles();
  }, [canEdit]);

  useEffect(() => {
    async function loadTimeseriesDistanceSettings() {
      if (!canEdit) return;
      try {
        const items = await apiFetch("/api/v1/science/timeseries-distance-settings");
        setTimeseriesDistanceSettings(Array.isArray(items) ? items : []);
      } catch (e) {
        setDistanceStatus(String(e));
      }
    }

    loadTimeseriesDistanceSettings();
  }, [canEdit]);

  function setVal(key, value) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function setDraftPosition(lat, lon) {
    setTrapLat(formatCoordinate(lat));
    setTrapLon(formatCoordinate(lon));
  }

  function setCircleStyleValue(sourceKey, field, value) {
    setCircleStyles((prev) =>
      prev.map((item) =>
        item.source_key === sourceKey
          ? { ...item, [field]: value }
          : item
      )
    );
  }

  function setTimeseriesDistanceValue(locationKind, value) {
    setTimeseriesDistanceSettings((prev) =>
      prev.map((item) =>
        item.location_kind === locationKind
          ? { ...item, max_distance_m: value }
          : item
      )
    );
  }

  async function onCreateTrap() {
    if (!canEdit) return;

    const lat = parseCoordinate(trapLat);
    const lon = parseCoordinate(trapLon);
    if (!trapName.trim() || lat == null || lon == null) {
      setTrapStatus("Укажи название и корректные координаты новой ловушки.");
      return;
    }

    setTrapStatus("Создаю ловушку...");
    try {
      const res = await apiFetch("/api/v1/science/traps", {
        method: "POST",
        body: JSON.stringify({
          name: trapName.trim(),
          lat,
          lon,
        }),
      });
      await refreshTrapLocations({
        selectedId: res.location?.id,
        editId: res.location?.id,
        deleteId: res.location?.id,
      });
      setLocMode("select");
      setTrapStatus(`Ловушка «${res.location?.name}» создана.`);
    } catch (e) {
      setTrapStatus(String(e));
    }
  }

  async function onUpdateTrap() {
    if (!canEdit || !editTrap) return;

    const lat = parseCoordinate(trapLat);
    const lon = parseCoordinate(trapLon);
    if (!trapName.trim() || lat == null || lon == null) {
      setTrapStatus("Укажи название и корректные координаты ловушки.");
      return;
    }

    setTrapStatus("Сохраняю ловушку...");
    try {
      const res = await apiFetch(`/api/v1/science/traps/${editTrap.id}`, {
        method: "PUT",
        body: JSON.stringify({
          name: trapName.trim(),
          lat,
          lon,
        }),
      });
      await refreshTrapLocations({
        selectedId: locationId,
        editId: res.location?.id,
        deleteId: deleteTrapId,
      });
      setTrapStatus(`Ловушка «${res.location?.name}» обновлена.`);
    } catch (e) {
      setTrapStatus(String(e));
    }
  }

  async function onDeleteTrap() {
    if (!canEdit || !deleteTrap) return;

    const confirmation = prompt(
      `Чтобы удалить ловушку «${deleteTrap.name}» и все связанные с ней замеры, введите ПОДТВЕРЖДАЮ`
    );
    if (confirmation == null) return;
    if (confirmation.trim() !== "ПОДТВЕРЖДАЮ") {
      setDeleteTrapStatus("Удаление отменено: кодовое слово введено неверно.");
      return;
    }

    setDeleteTrapStatus("Удаляю ловушку...");
    try {
      const res = await apiFetch(`/api/v1/science/traps/${deleteTrap.id}`, {
        method: "DELETE",
      });
      await refreshTrapLocations();
      await loadHistory();
      setDeleteTrapStatus(
        `Ловушка «${res.location?.name}» удалена. Удалено замеров: ${res.deleted_measurements ?? 0}.`
      );
    } catch (e) {
      setDeleteTrapStatus(String(e));
    }
  }

  async function onSaveMeasurements() {
    if (!canEdit) {
      setStatus("Нет прав. Нужна роль scientist или admin.");
      return;
    }

    if (filledValuesCount === 0) {
      setStatus("Добавь хотя бы одно значение замера.");
      return;
    }

    if (locMode !== "new" && !selectedTrap) {
      setStatus("Выбери ловушку для сохранения замеров.");
      return;
    }

    const lat = parseCoordinate(trapLat);
    const lon = parseCoordinate(trapLon);
    if (locMode === "new" && (!trapName.trim() || lat == null || lon == null)) {
      setStatus("Для новой ловушки нужно указать название и координаты.");
      return;
    }

    setStatus("Сохраняю замеры...");
    try {
      const payload = {
        ts: day,
        location:
          locMode !== "new"
            ? { id: Number(locationId) }
            : {
                name: trapName.trim(),
                lat,
                lon,
                kind: "trap",
              },
        default_unit: "grains/m3",
        values: {},
      };

      for (const taxon of taxa) {
        const raw = String(values[taxon.key]).trim();
        if (raw === "") continue;
        const numeric = Number(raw);
        if (Number.isNaN(numeric)) continue;
        payload.values[taxon.key] = { value: numeric };
      }

      const res = await apiFetch("/api/v1/science/measurements", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setStatus(`Готово: сохранено ${res.saved?.length || 0} значений для «${res.location?.name}».`);

      if (locMode === "new") {
        await refreshTrapLocations({
          selectedId: res.location?.id,
          editId: res.location?.id,
          deleteId: res.location?.id,
        });
        setLocMode("select");
      }

      await loadHistory();
    } catch (e) {
      setStatus(String(e));
    }
  }

  async function onDelete(id) {
    if (!canEdit) return;
    if (!confirm("Удалить запись?")) return;
    try {
      await apiFetch(`/api/v1/science/measurements/${id}`, { method: "DELETE" });
      await loadHistory();
    } catch (e) {
      alert(String(e));
    }
  }

  async function onSaveCircleStyles() {
    if (!canEdit) return;

    setStyleStatus("Сохраняю настройки карты...");
    try {
      const payload = {
        items: circleStyles.map((item) => ({
          source_key: item.source_key,
          base_radius_m: Number(item.base_radius_m),
          step_radius_m: Number(item.step_radius_m),
        })),
      };

      const res = await apiFetch("/api/v1/science/map-circle-styles", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      const nextItems = Array.isArray(res?.items)
        ? res.items.filter((item) => !item.is_fallback)
        : [];
      setCircleStyles(nextItems);
      setStyleStatus("Настройки радиусов карты сохранены.");
    } catch (e) {
      setStyleStatus(String(e));
    }
  }

  async function onSaveTimeseriesDistanceSettings() {
    if (!canEdit) return;

    setDistanceStatus("Сохраняю пороги близости...");
    try {
      const payload = {
        items: timeseriesDistanceSettings.map((item) => ({
          location_kind: item.location_kind,
          max_distance_m: Number(item.max_distance_m),
        })),
      };

      const res = await apiFetch("/api/v1/science/timeseries-distance-settings", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setTimeseriesDistanceSettings(Array.isArray(res?.items) ? res.items : []);
      setDistanceStatus("Пороги близости источников сохранены.");
    } catch (e) {
      setDistanceStatus(String(e));
    }
  }

  function onLogout() {
    clearToken();
    location.href = "/login";
  }

  return (
    <div className="grid science-cabinet-page" style={{ gap: 14 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Кабинет исследователя</h2>
        <button onClick={onLogout}>Выйти</button>
      </div>

      {meErr && <div className="note">{meErr}</div>}

      {me && (
        <div className="card">
          <div className="science-user-meta">
            <span>
              Вы вошли как: <b>{me.email}</b>
            </span>
            <span>
              • роль: <b>{me.role}</b>
            </span>
          </div>
          {!canEdit && (
            <div className="note" style={{ marginTop: 10 }}>
              В этой роли нельзя вносить замеры. Нужна роль scientist или admin.
            </div>
          )}
        </div>
      )}

      <div className="science-cabinet-layout">
        <div className="card science-cabinet-form">
          <div className="science-cabinet-section-head">
            <h3 className="science-cabinet-section-title">Ловушки и ввод замеров</h3>
          </div>

          <div className="grid" style={{ gap: 12 }}>
            <label className="science-field">
              <span>Дата замера</span>
              <input
                type="date"
                value={day}
                onChange={(e) => setDay(e.target.value)}
                style={{ width: "100%" }}
              />
            </label>

            <div className="row science-mode-row">
              <label>
                <input
                  type="radio"
                  checked={locMode === "select"}
                  onChange={() => {
                    setLocMode("select");
                    setTrapStatus("");
                  }}
                />{" "}
                Выбрать ловушку
              </label>
              <label>
                <input
                  type="radio"
                  checked={locMode === "edit"}
                  onChange={() => {
                    setLocMode("edit");
                    setTrapStatus("");
                    if (editTrap) {
                      setTrapLat(formatCoordinate(editTrap.lat));
                      setTrapLon(formatCoordinate(editTrap.lon));
                    }
                  }}
                />{" "}
                Изменить ловушку
              </label>
              <label>
                <input
                  type="radio"
                  checked={locMode === "new"}
                  onChange={() => {
                    setLocMode("new");
                    setTrapStatus("");
                    if (selectedTrap) {
                      setTrapLat(formatCoordinate(selectedTrap.lat));
                      setTrapLon(formatCoordinate(selectedTrap.lon));
                    }
                  }}
                />{" "}
                Создать новую
              </label>
            </div>

            {locMode === "select" ? (
              <div className="science-subcard">
                <div className="science-subcard-head">
                  <b>Выбор ловушки для замеров</b>
                </div>

                <label className="science-field">
                  <span>Ловушка</span>
                  <select
                    value={locationId}
                    onChange={(e) => setLocationId(e.target.value)}
                    style={{ width: "100%" }}
                  >
                    {locations.map((trap) => (
                      <option key={trap.id} value={trap.id}>
                        {trapOptionLabel(trap)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            ) : null}

            {locMode === "edit" ? (
              <div className="science-subcard">
                <div className="science-subcard-head">
                  <b>Изменение ловушки</b>
                </div>

                <label className="science-field">
                  <span>Ловушка</span>
                  <select
                    value={editTrapId}
                    onChange={(e) => setEditTrapId(e.target.value)}
                    style={{ width: "100%" }}
                  >
                    {locations.map((trap) => (
                      <option key={trap.id} value={trap.id}>
                        {trapOptionLabel(trap)}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="science-field">
                  <span>Изменить название ловушки</span>
                  <input
                    value={trapName}
                    onChange={(e) => setTrapName(e.target.value)}
                    style={{ width: "100%" }}
                  />
                </label>

                <div className="row science-coordinates-row">
                  <label className="science-field" style={{ flex: 1 }}>
                    <span>Широта</span>
                    <input
                      value={trapLat}
                      onChange={(e) => setTrapLat(e.target.value)}
                      style={{ width: "100%" }}
                    />
                  </label>
                  <label className="science-field" style={{ flex: 1 }}>
                    <span>Долгота</span>
                    <input
                      value={trapLon}
                      onChange={(e) => setTrapLon(e.target.value)}
                      style={{ width: "100%" }}
                    />
                  </label>
                </div>

                <button type="button" onClick={onUpdateTrap} disabled={!canEdit || !editTrap}>
                  Сохранить изменения ловушки
                </button>
              </div>
            ) : null}

            {locMode === "new" ? (
              <div className="science-subcard">
                <div className="science-subcard-head">
                  <b>Новая ловушка</b>
                  <span className="science-subcard-copy">
                    Поставьте точку на карте или введите координаты вручную.
                  </span>
                </div>

                <label className="science-field">
                  <span>Название ловушки</span>
                  <input
                    value={trapName}
                    onChange={(e) => setTrapName(e.target.value)}
                    style={{ width: "100%" }}
                  />
                </label>

                <div className="row science-coordinates-row">
                  <label className="science-field" style={{ flex: 1 }}>
                    <span>Широта</span>
                    <input
                      value={trapLat}
                      onChange={(e) => setTrapLat(e.target.value)}
                      style={{ width: "100%" }}
                    />
                  </label>
                  <label className="science-field" style={{ flex: 1 }}>
                    <span>Долгота</span>
                    <input
                      value={trapLon}
                      onChange={(e) => setTrapLon(e.target.value)}
                      style={{ width: "100%" }}
                    />
                  </label>
                </div>

                <button type="button" onClick={onCreateTrap} disabled={!canEdit}>
                  Создать ловушку
                </button>
              </div>
            ) : null}

            {trapStatus ? <div className="note note-muted">{trapStatus}</div> : null}

            {locMode !== "select" ? (
            <div className="science-trap-map-shell">
              <div className="science-trap-map-copy">
                <b>Карта ловушек</b>
                <div className="science-trap-map-help">
                  {locMode === "new"
                    ? "Кликните по карте, чтобы поставить новую ловушку. Маркер можно перетаскивать мышью, а координаты синхронизируются автоматически."
                    : "Выберите существующую ловушку из списка или кликните по зелёной точке на карте, чтобы перейти к ней."}
                </div>
              </div>

              <div className="science-trap-map-frame">
                <MapContainer
                  center={[58.0105, 56.2502]}
                  zoom={6}
                  scrollWheelZoom
                  attributionControl
                >
                  <MapAttributionCleaner />
                  <TileLayer
                    attribution="&copy; OpenStreetMap contributors"
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />

                  <TrapMapViewport
                    locations={locations}
                    locMode={locMode}
                    selectedTrap={editTrap}
                    draftPosition={draftPosition}
                  />
                  <TrapMapPicker
                    enabled={locMode === "new" && canEdit}
                    onPickPosition={setDraftPosition}
                  />

                  {locations.map((loc) => {
                    const selectedId = locMode === "edit" ? editTrapId : locationId;
                    const isSelected = String(loc.id) === String(selectedId);

                    return (
                      <CircleMarker
                        key={loc.id}
                        center={[Number(loc.lat), Number(loc.lon)]}
                        radius={isSelected ? 9 : 7}
                        eventHandlers={{
                          click: () => {
                            if (locMode === "edit") {
                              setEditTrapId(String(loc.id));
                            } else if (locMode === "select") {
                              setLocationId(String(loc.id));
                            }
                            setTrapStatus("");
                          },
                        }}
                        pathOptions={{
                          color: isSelected ? "#1d4ed8" : "#256747",
                          fillColor: isSelected ? "#60a5fa" : "#6ee7b7",
                          fillOpacity: isSelected ? 0.95 : 0.88,
                          weight: isSelected ? 3 : 2,
                        }}
                      />
                    );
                  })}

                  {locMode === "new" && draftPosition && (
                    <Marker
                      position={[draftPosition.lat, draftPosition.lon]}
                      draggable={canEdit}
                      icon={NEW_TRAP_ICON}
                      eventHandlers={{
                        dragend: (event) => {
                          const latlng = event.target.getLatLng();
                          setDraftPosition(latlng.lat, latlng.lng);
                        },
                      }}
                    />
                  )}
                </MapContainer>

                <div className="science-trap-map-toolbar">
                  <span className="badge">Ловушек: {locations.length}</span>
                  <span className="badge">
                    {locMode === "new"
                      ? draftPosition
                        ? `${draftPosition.lat.toFixed(4)}, ${draftPosition.lon.toFixed(4)}`
                        : "Выберите точку"
                      : editTrap
                        ? `${Number(editTrap.lat).toFixed(4)}, ${Number(editTrap.lon).toFixed(4)}`
                        : "Ловушка не выбрана"}
                  </span>
                </div>
              </div>
            </div>
            ) : null}

            <div ref={allergenCardRef} className="science-subcard">
              <div className="science-subcard-head">
                <b>Аллергены</b>
              </div>

              <div className="science-taxa-grid">
                {taxa.map((taxon) => (
                  <label key={taxon.key} className="science-taxa-row">
                    <span className="science-taxa-name">
                      {taxon.emoji} {taxon.name_ru}
                    </span>
                    <input
                      value={values[taxon.key]}
                      onChange={(e) => setVal(taxon.key, e.target.value)}
                      placeholder="grains/m3"
                    />
                  </label>
                ))}
              </div>

              <button onClick={onSaveMeasurements} disabled={!canEdit || filledValuesCount === 0}>
                Сохранить замеры
              </button>

              {status ? <div className="note note-muted">{status}</div> : null}
            </div>

            <div className="science-subcard">
              <div className="science-style-card-head">
                <b>Радиусы слоёв карты</b>
                <div className="science-style-card-copy">
                  Базовый радиус и шаг роста круга по уровню опасности. Формула: радиус = base +
                  danger_level * step, где danger_level принимает значения от 0 до 3. Значения
                  задаются в метрах.
                </div>
              </div>

              <div className="science-style-grid">
                {circleStyles.map((item) => (
                  <div key={item.source_key} className="science-style-row">
                    <div className="science-style-source">
                      <div className="science-style-source-title">{item.source_name}</div>
                      <div className="science-style-source-key">{item.source_key}</div>
                    </div>

                    <label className="science-style-field">
                      <span>Base</span>
                      <input
                        type="number"
                        min="0"
                        step="1"
                        value={item.base_radius_m}
                        onChange={(e) =>
                          setCircleStyleValue(item.source_key, "base_radius_m", e.target.value)
                        }
                      />
                    </label>

                    <label className="science-style-field">
                      <span>Step</span>
                      <input
                        type="number"
                        min="0"
                        step="1"
                        value={item.step_radius_m}
                        onChange={(e) =>
                          setCircleStyleValue(item.source_key, "step_radius_m", e.target.value)
                        }
                      />
                    </label>
                  </div>
                ))}
              </div>

              <div className="science-style-actions">
                <button
                  type="button"
                  onClick={onSaveCircleStyles}
                  disabled={!canEdit || circleStyles.length === 0}
                >
                  Сохранить радиусы карты
                </button>
              </div>

              {styleStatus ? <div className="note note-muted">{styleStatus}</div> : null}
            </div>

            <div className="science-subcard">
              <div className="science-style-card-head">
                <b>Пороги близости источников для графика</b>
                <div className="science-style-card-copy">
                  Определяют, какие источники считаются достаточно близкими к выбранной точке и
                  попадают в график. Расстояние считается в метрах.
                </div>
              </div>

              <div className="science-distance-grid">
                {timeseriesDistanceSettings.map((item) => (
                  <div key={item.location_kind} className="science-distance-row">
                    <div className="science-style-source">
                      <div className="science-style-source-title">{item.label}</div>
                      <div className="science-style-source-key">{item.location_kind}</div>
                    </div>

                    <label className="science-style-field">
                      <span>Макс. расстояние, м</span>
                      <input
                        type="number"
                        min="0"
                        max="5000000"
                        step="100"
                        value={item.max_distance_m}
                        onChange={(e) =>
                          setTimeseriesDistanceValue(item.location_kind, e.target.value)
                        }
                      />
                    </label>
                  </div>
                ))}
              </div>

              <div className="science-style-actions">
                <button
                  type="button"
                  onClick={onSaveTimeseriesDistanceSettings}
                  disabled={!canEdit || timeseriesDistanceSettings.length === 0}
                >
                  Сохранить пороги близости
                </button>
              </div>

              {distanceStatus ? <div className="note note-muted">{distanceStatus}</div> : null}
            </div>

          </div>
        </div>

        <div
          className="card science-history-card"
          style={historyTableHeight ? { height: `${historyTableHeight}px` } : undefined}
        >
          <div className="science-cabinet-section-head">
            <h3 className="science-cabinet-section-title">История замеров</h3>
            <p className="science-cabinet-section-copy">
              Показывает записи за выбранную дату.
            </p>
          </div>
          {historyErr && <div className="note">{historyErr}</div>}

          <div className="science-history-toolbar">
            <button onClick={loadHistory} disabled={!canEdit}>Обновить</button>
            <label className="science-history-filter">
              <input
                type="checkbox"
                checked={historyOnlySelected}
                onChange={(e) => setHistoryOnlySelected(e.target.checked)}
                disabled={!selectedTrap}
              />
              Только выбранная ловушка
            </label>
          </div>

          <div className="science-history-table-shell">
            {!history?.length ? (
              <div style={{ opacity: 0.7 }}>
                {historyOnlySelected && selectedTrap
                  ? "Для выбранной ловушки на эту дату записей нет."
                  : "Нет записей за выбранную дату."}
              </div>
            ) : (
              <table className="science-history-table">
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Локация</th>
                    <th>Аллерген</th>
                    <th>Значение</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((row) => (
                    <tr key={row.id}>
                      <td>{String(row.ts).slice(0, 16)}</td>
                      <td>{row.location?.name}</td>
                      <td>{row.taxon?.name_ru}</td>
                      <td>
                        {row.value} {row.unit}
                      </td>
                      <td>
                        <button onClick={() => onDelete(row.id)} disabled={!canEdit}>
                          Удалить
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      <div className="card science-delete-card">
        <label className="science-delete-toggle">
          <input
            type="checkbox"
            checked={showDeleteTrapPanel}
            onChange={(e) => setShowDeleteTrapPanel(e.target.checked)}
          />
          Показать удаление ловушки
        </label>

        {showDeleteTrapPanel ? (
          <>
            <div className="science-cabinet-section-head">
              <h3 className="science-cabinet-section-title">Удалить ловушку</h3>
              <p className="science-cabinet-section-copy">
                Удаление безвозвратно удалит ловушку и все связанные с ней замеры.
              </p>
            </div>

            <div className="science-delete-controls">
              <label className="science-field">
                <span>Ловушка для удаления</span>
                <select
                  value={deleteTrapId}
                  onChange={(e) => setDeleteTrapId(e.target.value)}
                  style={{ width: "100%" }}
                >
                  {locations.map((trap) => (
                    <option key={trap.id} value={trap.id}>
                      {trapOptionLabel(trap)}
                    </option>
                  ))}
                </select>
              </label>

              <button
                type="button"
                className="danger-button"
                onClick={onDeleteTrap}
                disabled={!canEdit || !deleteTrap}
              >
                Удалить ловушку
              </button>
            </div>

            {deleteTrapStatus ? <div className="note note-muted">{deleteTrapStatus}</div> : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
