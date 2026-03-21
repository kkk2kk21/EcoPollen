describe("mapPlaces cache", () => {
  async function loadApi() {
    vi.resetModules();
    return import("../src/shared/api/mapPlaces.js");
  }

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("caches successful response", async () => {
    const { fetchMapPlaces } = await loadApi();

    fetch.mockResolvedValue({
      ok: true,
      json: async () => [{ id: "1", name: "Пермь" }],
    });

    const first = await fetchMapPlaces();
    const second = await fetchMapPlaces();

    expect(first).toEqual([{ id: "1", name: "Пермь" }]);
    expect(second).toEqual(first);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("deduplicates inflight request", async () => {
    const { fetchMapPlaces } = await loadApi();
    let resolveFetch;
    fetch.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      })
    );

    const firstPromise = fetchMapPlaces();
    const secondPromise = fetchMapPlaces();

    expect(fetch).toHaveBeenCalledTimes(1);

    resolveFetch({
      ok: true,
      json: async () => [{ id: "2", name: "Москва" }],
    });

    const [first, second] = await Promise.all([firstPromise, secondPromise]);
    expect(first).toEqual(second);
  });

  it("bypasses cache when force enabled", async () => {
    const { fetchMapPlaces } = await loadApi();

    fetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [{ id: "1", name: "Пермь" }],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [{ id: "2", name: "Москва" }],
      });

    await fetchMapPlaces();
    const forced = await fetchMapPlaces({ force: true });

    expect(forced).toEqual([{ id: "2", name: "Москва" }]);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("throws readable error on non-ok response", async () => {
    const { fetchMapPlaces } = await loadApi();

    fetch.mockResolvedValue({
      ok: false,
      json: async () => [],
    });

    await expect(fetchMapPlaces()).rejects.toThrow("Не удалось загрузить точки карты");
  });
});
