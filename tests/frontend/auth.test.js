import { apiFetch, clearToken, getToken, setToken } from "../../frontend/src/shared/api/auth.js";

describe("auth api helpers", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stores and clears token", () => {
    setToken("abc");
    expect(getToken()).toBe("abc");

    clearToken();
    expect(getToken()).toBeNull();
  });

  it("adds auth header when token exists", async () => {
    setToken("secret");
    fetch.mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ ok: true }),
    });

    await apiFetch("/api/test", { method: "GET" });

    const [, options] = fetch.mock.calls[0];
    expect(options.headers.get("Authorization")).toBe("Bearer secret");
  });

  it("adds content type for json body", async () => {
    fetch.mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ ok: true }),
    });

    await apiFetch("/api/test", {
      method: "POST",
      body: JSON.stringify({ hello: "world" }),
    });

    const [, options] = fetch.mock.calls[0];
    expect(options.headers.get("Content-Type")).toBe("application/json");
  });

  it("throws readable backend error", async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => JSON.stringify({ detail: "bad request" }),
    });

    await expect(apiFetch("/api/test")).rejects.toThrow("HTTP 400: bad request");
  });
});
