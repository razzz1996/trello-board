import { afterEach, describe, expect, it, vi } from "vitest";

import { createIdempotencyKey } from "./idempotency";

describe("createIdempotencyKey", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses randomUUID when the secure-context API is available", () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "11111111-2222-4333-8444-555555555555",
    });

    expect(createIdempotencyKey()).toBe(
      "11111111-2222-4333-8444-555555555555",
    );
  });

  it("builds a UUID with getRandomValues on an HTTP LAN origin", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0);
        return bytes;
      },
    });

    expect(createIdempotencyKey()).toBe(
      "00000000-0000-4000-8000-000000000000",
    );
  });

  it("still creates unique request keys when Web Crypto is unavailable", () => {
    vi.stubGlobal("crypto", undefined);

    const first = createIdempotencyKey();
    const second = createIdempotencyKey();

    expect(first).toMatch(/^request-/);
    expect(second).toMatch(/^request-/);
    expect(second).not.toBe(first);
  });
});
