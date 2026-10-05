let fallbackCounter = 0;

function formatUuid(bytes: Uint8Array): string {
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}

export function createIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }

  if (cryptoApi && typeof cryptoApi.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    return formatUuid(bytes);
  }

  fallbackCounter = (fallbackCounter + 1) % Number.MAX_SAFE_INTEGER;
  const highResolutionTime =
    typeof globalThis.performance?.now === "function"
      ? Math.floor(globalThis.performance.now() * 1000).toString(36)
      : "0";
  const randomPart = () =>
    Math.floor(Math.random() * Number.MAX_SAFE_INTEGER).toString(36);

  return [
    "request",
    Date.now().toString(36),
    highResolutionTime,
    fallbackCounter.toString(36),
    randomPart(),
    randomPart(),
  ].join("-");
}
