import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { hasSeenIntro, INTRO_SEEN_KEY, markIntroSeen } from "./intro";

describe("intro storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("reports unseen when flag is missing", () => {
    expect(hasSeenIntro()).toBe(false);
  });

  it("persists dismissal", () => {
    markIntroSeen();
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
    expect(hasSeenIntro()).toBe(true);
  });

  it("survives blocked storage writes", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => markIntroSeen()).not.toThrow();
    spy.mockRestore();
  });
});
