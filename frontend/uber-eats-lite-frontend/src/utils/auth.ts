// src/utils/auth.ts
export function getDriverIdFromToken(): string | null {
  const token = localStorage.getItem("token");
  if (!token) return null;

  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.sub; // UUID 
  } catch {
    return null;
  }
}
