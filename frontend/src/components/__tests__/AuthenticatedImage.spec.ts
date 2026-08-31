import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { loadObjectUrl } from "../../api";
import AuthenticatedImage from "../AuthenticatedImage.vue";

vi.mock("../../api", () => ({
  loadObjectUrl: vi.fn(),
}));

describe("AuthenticatedImage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("cancels the previous resource request when the path changes", async () => {
    const signals: AbortSignal[] = [];
    vi.mocked(loadObjectUrl).mockImplementation((_path, signal) => {
      if (signal) signals.push(signal);
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), {
          once: true,
        });
      });
    });
    const wrapper = mount(AuthenticatedImage, {
      props: { path: "/screenshots/first", alt: "first" },
    });

    await wrapper.setProps({ path: "/screenshots/second", alt: "second" });

    expect(signals).toHaveLength(2);
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
    wrapper.unmount();
    await flushPromises();
    expect(signals[1].aborted).toBe(true);
  });

  it("keeps a shared request alive while another consumer is waiting", async () => {
    let sharedSignal: AbortSignal | undefined;
    vi.mocked(loadObjectUrl).mockImplementation((_path, signal) => {
      sharedSignal = signal;
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), {
          once: true,
        });
      });
    });
    const props = { path: "/screenshots/shared", alt: "shared" };
    const first = mount(AuthenticatedImage, { props });
    const second = mount(AuthenticatedImage, { props });

    expect(loadObjectUrl).toHaveBeenCalledOnce();
    first.unmount();
    expect(sharedSignal?.aborted).toBe(false);
    second.unmount();
    await flushPromises();
    expect(sharedSignal?.aborted).toBe(true);
  });
});
