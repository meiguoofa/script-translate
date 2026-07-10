// crypto.randomUUID 仅在安全上下文（HTTPS / localhost）可用。
// http://45.78.235.74:8900 是非安全上下文，crypto.randomUUID 为 undefined。
// 用 crypto.getRandomValues（HTTP 下仍可用）兜底构造 UUID v4。
export function uuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // variant 10
  const h = (n: number) => n.toString(16).padStart(2, "0");
  return (
    h(b[0]) + h(b[1]) + h(b[2]) + h(b[3]) +
    "-" + h(b[4]) + h(b[5]) +
    "-" + h(b[6]) + h(b[7]) +
    "-" + h(b[8]) + h(b[9]) +
    "-" + h(b[10]) + h(b[11]) + h(b[12]) + h(b[13]) + h(b[14]) + h(b[15])
  );
}
