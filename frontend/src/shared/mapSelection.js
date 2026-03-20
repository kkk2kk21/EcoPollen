const MAP_PLACE_STORAGE_KEY = "ecopollen_map_place";

export function savePreferredMapPlace(place) {
  if (!place?.id) {
    localStorage.removeItem(MAP_PLACE_STORAGE_KEY);
    return;
  }

  localStorage.setItem(
    MAP_PLACE_STORAGE_KEY,
    JSON.stringify({
      id: String(place.id),
      label: place.label || place.name || "",
    })
  );
}

export function readPreferredMapPlaceId() {
  try {
    const raw = localStorage.getItem(MAP_PLACE_STORAGE_KEY);
    if (!raw) return "";
    const parsed = JSON.parse(raw);
    return parsed?.id ? String(parsed.id) : "";
  } catch {
    return "";
  }
}

export function clearPreferredMapPlace() {
  localStorage.removeItem(MAP_PLACE_STORAGE_KEY);
}
