const MAP_PLACES_CACHE_TTL_MS = 15 * 60 * 1000;

let mapPlacesCache = null;
let mapPlacesExpiresAt = 0;
let mapPlacesInflightRequest = null;

export async function fetchMapPlaces({ force = false } = {}) {
  if (!force && mapPlacesCache && mapPlacesExpiresAt > Date.now()) {
    return mapPlacesCache;
  }

  if (!force && mapPlacesInflightRequest) {
    return mapPlacesInflightRequest;
  }

  mapPlacesInflightRequest = (async () => {
    const res = await fetch("/api/v1/map-locations");
    if (!res.ok) {
      throw new Error("Не удалось загрузить точки карты");
    }

    const data = await res.json();
    const items = Array.isArray(data) ? data : [];

    mapPlacesCache = items;
    mapPlacesExpiresAt = Date.now() + MAP_PLACES_CACHE_TTL_MS;
    return items;
  })();

  try {
    return await mapPlacesInflightRequest;
  } finally {
    mapPlacesInflightRequest = null;
  }
}
