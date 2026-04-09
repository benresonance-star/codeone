import { describe, expect, it } from "vitest";

import { renderedClausePageChipLabel } from "./candidate-review-workspace-logic";

describe("candidate review workspace page chips", () => {
  it("shows a chip for the first rendered block page", () => {
    expect(renderedClausePageChipLabel({ page: 3 })).toBe("Page 3");
  });

  it("suppresses duplicate chips for consecutive blocks on the same page", () => {
    expect(renderedClausePageChipLabel({ page: 3 }, { page: 3 })).toBeNull();
  });

  it("shows a new chip when the rendered clause crosses to another page", () => {
    expect(renderedClausePageChipLabel({ page: 4 }, { page: 3 })).toBe("Continues on page 4");
  });
});
