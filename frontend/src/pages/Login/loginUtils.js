export function redirectByRole(role) {
  if (role === "admin") return "/admin";
  if (role === "scientist") return "/science";
  return "/map";
}

export function resolveRequestedPath(role, requestedPath) {
  if (!requestedPath) return redirectByRole(role);
  if (requestedPath === "/admin") return role === "admin" ? requestedPath : redirectByRole(role);
  if (requestedPath === "/science") {
    return role === "admin" || role === "scientist" ? requestedPath : redirectByRole(role);
  }
  if (requestedPath === "/library") return requestedPath;
  return requestedPath;
}
