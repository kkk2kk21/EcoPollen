import { requestJson } from "./http";

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
    const data = await requestJson("/api/v1/map-locations", {
      errorMessage: "Не удалось загрузить точки карты",
    });
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
