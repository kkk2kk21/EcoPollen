import { redirectByRole, resolveRequestedPath } from "../../frontend/src/pages/Login/loginUtils.js";

describe("loginUtils", () => {
  it("redirects by role", () => {
    expect(redirectByRole("admin")).toBe("/admin");
    expect(redirectByRole("scientist")).toBe("/science");
    expect(redirectByRole("student")).toBe("/map");
  });

  it("keeps allowed target for role and falls back for forbidden one", () => {
    expect(resolveRequestedPath("admin", "/admin")).toBe("/admin");
    expect(resolveRequestedPath("scientist", "/science")).toBe("/science");
    expect(resolveRequestedPath("student", "/science")).toBe("/map");
    expect(resolveRequestedPath("student", "/library")).toBe("/library");
  });
});
