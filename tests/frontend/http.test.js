import {
  DEFAULT_REQUEST_TIMEOUT_MS,
  fetchWithTimeout,
  requestJson,
} from "../../frontend/src/shared/api/http.js";

describe("http api helpers", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("uses the default timeout when no custom timeout is passed", async () => {
    fetch.mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ ok: true }),
    });

    await requestJson("/api/test");

    const [, options] = fetch.mock.calls[0];
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(DEFAULT_REQUEST_TIMEOUT_MS).toBe(60 * 1000);
  });

  it("aborts a hanging request with a readable timeout message", async () => {
    vi.useFakeTimers();

    fetch.mockImplementation((_, options = {}) =>
      new Promise((resolve, reject) => {
        options.signal.addEventListener(
          "abort",
          () => reject(options.signal.reason ?? new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      }),
    );

    const request = fetchWithTimeout("/api/test", { timeoutMs: 1500 });
    const assertion = expect(request).rejects.toThrow(
      "Запрос выполнялся дольше 2 сек. Попробуйте ещё раз",
    );

    await vi.advanceTimersByTimeAsync(1500);

    await assertion;
  });

  it("propagates parent aborts without turning them into timeout errors", async () => {
    const parentController = new AbortController();
    const reason = new Error("cancelled by parent");

    fetch.mockImplementation((_, options = {}) =>
      new Promise((resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
      }),
    );

    const request = fetchWithTimeout("/api/test", {
      timeoutMs: 5000,
      signal: parentController.signal,
    });

    parentController.abort(reason);

    await expect(request).rejects.toBe(reason);
  });

  it("returns parsed json for successful responses", async () => {
    fetch.mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ ok: true, items: [1, 2, 3] }),
    });

    await expect(requestJson("/api/test")).resolves.toEqual({ ok: true, items: [1, 2, 3] });
  });

  it("returns plain text when the response body is not json", async () => {
    fetch.mockResolvedValue({
      ok: true,
      text: async () => "plain text",
    });

    await expect(requestJson("/api/test")).resolves.toBe("plain text");
  });

  it("returns null when the response body is empty", async () => {
    fetch.mockResolvedValue({
      ok: true,
      text: async () => "",
    });

    await expect(requestJson("/api/test")).resolves.toBeNull();
  });

  it("uses backend detail text for http errors", async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => JSON.stringify({ detail: "bad request" }),
    });

    await expect(requestJson("/api/test")).rejects.toThrow("HTTP 400: bad request");
  });

  it("uses a plain-text backend error body when no json detail exists", async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 502,
      text: async () => "Bad Gateway",
    });

    await expect(requestJson("/api/test")).rejects.toThrow("HTTP 502: Bad Gateway");
  });

  it("falls back to the provided error message when the backend returns no detail", async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => "",
    });

    await expect(
      requestJson("/api/test", { errorMessage: "Не удалось получить сводку" }),
    ).rejects.toThrow("HTTP 500: Не удалось получить сводку");
  });
});
