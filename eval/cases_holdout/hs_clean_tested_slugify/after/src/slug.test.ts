import { describe, expect, it } from "vitest";

import { slugify } from "./slug";

describe("slugify", () => {
  it("lowercases and joins words with dashes", () => {
    expect(slugify("Hello World")).toBe("hello-world");
  });

  it("strips accents and punctuation", () => {
    expect(slugify("Crème brûlée, s'il vous plaît!")).toBe("creme-brulee-s-il-vous-plait");
  });

  it("returns an empty string for symbols only", () => {
    expect(slugify("!!!")).toBe("");
  });

  it("cuts at maxLength without a trailing dash", () => {
    expect(slugify(`${"a".repeat(30)} ${"b".repeat(40)}`, 31)).toBe("a".repeat(30));
  });

  it("handles an empty title", () => {
    expect(slugify("")).toBe("");
  });
});
