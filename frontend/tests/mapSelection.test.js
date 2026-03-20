import {
  clearPreferredMapPlace,
  readPreferredMapPlaceId,
  savePreferredMapPlace,
} from "../src/shared/mapSelection.js";

describe("mapSelection", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("saves and reads preferred map place id", () => {
    savePreferredMapPlace({ id: "catalog:city:1", label: "Пермь" });

    expect(readPreferredMapPlaceId()).toBe("catalog:city:1");
  });

  it("returns empty string for broken storage payload", () => {
    localStorage.setItem("ecopollen_map_place", "{broken");

    expect(readPreferredMapPlaceId()).toBe("");
  });

  it("clears stored place when empty value provided", () => {
    savePreferredMapPlace({ id: "catalog:city:1", label: "Пермь" });
    savePreferredMapPlace(null);

    expect(readPreferredMapPlaceId()).toBe("");
    expect(localStorage.getItem("ecopollen_map_place")).toBeNull();
  });

  it("removes storage on explicit clear", () => {
    savePreferredMapPlace({ id: "catalog:city:1", label: "Пермь" });
    clearPreferredMapPlace();

    expect(localStorage.getItem("ecopollen_map_place")).toBeNull();
  });
});
