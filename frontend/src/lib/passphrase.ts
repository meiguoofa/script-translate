const KEY = "accessPassphrase";

export function getPassphrase(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(KEY) ?? "";
}

export function setPassphrase(value: string): void {
  if (typeof window === "undefined") return;
  if (value) {
    window.localStorage.setItem(KEY, value);
  } else {
    window.localStorage.removeItem(KEY);
  }
}

export function clearPassphrase(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}
