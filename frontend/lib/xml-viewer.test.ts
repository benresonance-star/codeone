import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildXmlViewerDocument,
  collectCollapsibleNodeIds,
  flattenXmlSourceRows,
  flattenVisibleXmlNodes,
  getXmlViewerElementPathIdsForTextId,
  getXmlViewerMathNode,
  getNextXmlViewerSourceTextSelection,
  getXmlViewerParsedSegments,
  getDefaultCollapsedNodeIds,
  isXmlViewerEquationNode,
  parseXmlViewerDocument,
  toggleCollapsedNode,
  type XmlAttributeLike,
  type XmlElementLike,
} from "./xml-viewer";

function text(value: string) {
  return { nodeType: 3, textContent: value };
}

function element(
  tagName: string,
  {
    attributes = [],
    children = [],
  }: {
    attributes?: XmlAttributeLike[];
    children?: Array<XmlElementLike | ReturnType<typeof text>>;
  } = {}
): XmlElementLike {
  return {
    tagName,
    attributes,
    childNodes: children,
  };
}

const sampleTree = element("page", {
  attributes: [{ name: "id", value: "page-1" }],
  children: [
    element("title", { children: [text("Main title")] }),
    element("section", {
      attributes: [{ name: "outputclass", value: "body" }],
      children: [
        text("Leading copy"),
        element("p", { children: [text("Alpha"), text(" beta")] }),
        element("p", { children: [text("Gamma")] }),
      ],
    }),
  ],
});

const equationTree = element("p", {
  children: [
    text("The calculated reliability index"),
    element("equation-inline", {
      children: [
        element("mathML", {
          children: [
            element("math", {
              children: [
                element("semantics", {
                  children: [
                    element("mrow", {
                      children: [
                        element("mi", { children: [text("β")] }),
                        element("mo", { children: [text("=")] }),
                        element("mn", { children: [text("3")] }),
                      ],
                    }),
                    element("annotation", {
                      attributes: [{ name: "encoding", value: "MathType-MTEF" }],
                      children: [text("MathType@MTEF@5@5@+=encoded payload")],
                    }),
                  ],
                }),
              ],
            }),
          ],
        }),
      ],
    }),
    text("must be used."),
    element("image", {
      children: [text("BASE64-IMAGE-DATA")],
    }),
  ],
});

describe("xml-viewer helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds a normalized recursive node model", () => {
    const document = buildXmlViewerDocument(sampleTree);

    expect(document.nodeCount).toBe(5);
    expect(document.maxDepth).toBe(2);
    expect(document.root.path).toBe("/page[1]");
    expect(document.root.descendantText).toBe("Main title Leading copy Alpha beta Gamma");
    expect(document.root.children[1]?.path).toBe("/page[1]/section[1]");
    expect(document.root.children[1]?.children[0]?.path).toBe("/page[1]/section[1]/p[1]");
    expect(document.root.children[1]?.children[0]?.directText).toBe("Alpha beta");
    expect(document.root.children[1]?.content).toEqual([
      { kind: "text", id: "0.1.t0", text: "Leading copy" },
      { kind: "element", nodeId: "0.1.0" },
      { kind: "element", nodeId: "0.1.1" },
    ]);
    expect(document.root.children[1]?.listMarker).toBeNull();
  });

  it("derives default collapsed state and aligned visible rows", () => {
    const document = buildXmlViewerDocument(sampleTree);

    expect(getDefaultCollapsedNodeIds(document.root)).toEqual(["0.1"]);
    expect(flattenVisibleXmlNodes(document.root, ["0.1"]).map((node) => node.tagName)).toEqual([
      "page",
      "title",
      "section",
    ]);
    expect(flattenVisibleXmlNodes(document.root, toggleCollapsedNode(["0.1"], "0.1")).map((node) => node.tagName)).toEqual([
      "page",
      "title",
      "section",
      "p",
      "p",
    ]);
  });

  it("preserves source-row order for mixed text and child elements", () => {
    const document = buildXmlViewerDocument(sampleTree);

    expect(
      flattenXmlSourceRows(document.root, toggleCollapsedNode(["0.1"], "0.1")).map((row) =>
        row.kind === "element" ? `<${row.node.tagName}>` : `"${row.text}"`
      )
    ).toEqual(["<page>", "<title>", "\"Main title\"", "<section>", "\"Leading copy\"", "<p>", "\"Alpha beta\"", "<p>", "\"Gamma\""]);
  });

  it("hides nested text rows when a branch is collapsed while keeping parsed-node visibility", () => {
    const document = buildXmlViewerDocument(sampleTree);

    expect(flattenXmlSourceRows(document.root, ["0.1"]).map((row) => row.id)).toEqual(["0", "0.0", "0.0.t0", "0.1"]);
    expect(flattenVisibleXmlNodes(document.root, ["0.1"]).map((node) => node.tagName)).toEqual(["page", "title", "section"]);
  });

  it("builds parsed segments that preserve direct text ids for cross-pane linking", () => {
    const document = buildXmlViewerDocument(sampleTree);

    expect(getXmlViewerParsedSegments(document.root.children[1]!)).toEqual([
      {
        id: "0.1.t0",
        kind: "text",
        sourceNodeId: "0.1",
        text: "Leading copy",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
      {
        id: "0.1.0::descendant",
        kind: "child",
        sourceNodeId: "0.1.0",
        text: "Alpha beta",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
      {
        id: "0.1.1::descendant",
        kind: "child",
        sourceNodeId: "0.1.1",
        text: "Gamma",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
    ]);
  });

  it("marks parsed segments sourced from abcb-glossentry nodes", () => {
    const glossaryTree = element("p", {
      children: [
        text("A doorway in a"),
        element("xref", {
          attributes: [{ name: "type", value: "abcb-glossentry" }],
          children: [text("resident use area")],
        }),
        text("must comply."),
      ],
    });

    const document = buildXmlViewerDocument(glossaryTree);

    expect(getXmlViewerParsedSegments(document.root)).toEqual([
      {
        id: "0.t0",
        kind: "text",
        sourceNodeId: "0",
        text: "A doorway in a",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
      {
        id: "0.0::descendant",
        kind: "child",
        sourceNodeId: "0.0",
        text: "resident use area",
        isGlossaryEntry: true,
        isStructuralHighlight: false,
      },
      {
        id: "0.t1",
        kind: "text",
        sourceNodeId: "0",
        text: "must comply.",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
    ]);
  });

  it("marks parsed segments sourced from glossterm xrefs like abcb-glossentry", () => {
    const glossaryTree = element("p", {
      children: [
        text("See"),
        element("xref", {
          attributes: [{ name: "type", value: "glossterm" }],
          children: [text("sole-occupancy unit")],
        }),
        text("for details."),
      ],
    });

    const document = buildXmlViewerDocument(glossaryTree);

    expect(getXmlViewerParsedSegments(document.root)).toEqual([
      {
        id: "0.t0",
        kind: "text",
        sourceNodeId: "0",
        text: "See",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
      {
        id: "0.0::descendant",
        kind: "child",
        sourceNodeId: "0.0",
        text: "sole-occupancy unit",
        isGlossaryEntry: true,
        isStructuralHighlight: false,
      },
      {
        id: "0.t1",
        kind: "text",
        sourceNodeId: "0",
        text: "for details.",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
    ]);
  });

  it("marks parsed segments sourced from ncc-clause and part type wrappers for structural highlighting", () => {
    const structuralTree = element("p", {
      children: [
        text("See"),
        element("xref", {
          attributes: [{ name: "type", value: "ncc-clause" }],
          children: [text("J2D3")],
        }),
        text("and"),
        element("xref", {
          attributes: [{ name: "type", value: "part" }],
          children: [text("Part H8")],
        }),
        text("for more."),
      ],
    });

    const document = buildXmlViewerDocument(structuralTree);

    expect(getXmlViewerParsedSegments(document.root)).toEqual([
      {
        id: "0.t0",
        kind: "text",
        sourceNodeId: "0",
        text: "See",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
      {
        id: "0.0::descendant",
        kind: "child",
        sourceNodeId: "0.0",
        text: "J2D3",
        isGlossaryEntry: false,
        isStructuralHighlight: true,
      },
      {
        id: "0.t1",
        kind: "text",
        sourceNodeId: "0",
        text: "and",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
      {
        id: "0.1::descendant",
        kind: "child",
        sourceNodeId: "0.1",
        text: "Part H8",
        isGlossaryEntry: false,
        isStructuralHighlight: true,
      },
      {
        id: "0.t2",
        kind: "text",
        sourceNodeId: "0",
        text: "for more.",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
    ]);
  });

  it("derives expandable element path ids from a text node id", () => {
    expect(getXmlViewerElementPathIdsForTextId("0.3.0.t0")).toEqual(["0", "0.3", "0.3.0"]);
    expect(getXmlViewerElementPathIdsForTextId("0.1.t0")).toEqual(["0", "0.1"]);
  });

  it("assigns alpha and roman list markers based on ordered-list nesting", () => {
    const listTree = element("ol", {
      children: [
        element("li", { children: [text("First item")] }),
        element("li", {
          children: [
            text("Second item"),
            element("ol", {
              children: [
                element("li", { children: [text("Nested one")] }),
                element("li", { children: [text("Nested two")] }),
              ],
            }),
          ],
        }),
      ],
    });

    const document = buildXmlViewerDocument(listTree);
    const firstItem = document.root.children[0];
    const secondItem = document.root.children[1];
    const nestedList = secondItem?.children[0];

    expect(firstItem?.listMarker).toBe("(a)");
    expect(secondItem?.listMarker).toBe("(b)");
    expect(nestedList?.children[0]?.listMarker).toBe("(i)");
    expect(nestedList?.children[1]?.listMarker).toBe("(ii)");
  });

  it("only toggles selection for direct parsed text segments", () => {
    const document = buildXmlViewerDocument(sampleTree);
    const segments = getXmlViewerParsedSegments(document.root.children[1]!);

    expect(getNextXmlViewerSourceTextSelection(null, segments[0]!)).toBe("0.1.t0");
    expect(getNextXmlViewerSourceTextSelection("0.1.t0", segments[0]!)).toBeNull();
    expect(getNextXmlViewerSourceTextSelection("0.1.t0", segments[1]!)).toBe("0.1.t0");
  });

  it("suppresses MathType annotations from parsed text while retaining renderable math content", () => {
    const document = buildXmlViewerDocument(equationTree);
    const equationNode = document.root.children[0];

    expect(document.root.descendantText).toBe("The calculated reliability index β = 3 must be used.");
    expect(isXmlViewerEquationNode(equationNode!)).toBe(true);
    expect(getXmlViewerMathNode(equationNode!)?.tagName).toBe("math");
    expect(getXmlViewerParsedSegments(document.root)).toEqual([
      {
        id: "0.t0",
        kind: "text",
        sourceNodeId: "0",
        text: "The calculated reliability index",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
      {
        id: "0.0::descendant",
        kind: "child",
        sourceNodeId: "0.0",
        text: "β = 3",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
      {
        id: "0.t1",
        kind: "text",
        sourceNodeId: "0",
        text: "must be used.",
        isGlossaryEntry: false,
        isStructuralHighlight: false,
      },
    ]);
  });

  it("keeps source rows free of MathType annotation and image payload text", () => {
    const document = buildXmlViewerDocument(equationTree);

    expect(
      flattenXmlSourceRows(document.root, []).some((row) => row.kind === "text" && /MathType@MTEF|BASE64-IMAGE-DATA/.test(row.text))
    ).toBe(false);
  });

  it("treats equation containers as terminal viewer nodes", () => {
    const document = buildXmlViewerDocument(equationTree);

    expect(flattenVisibleXmlNodes(document.root, []).map((node) => node.tagName)).toEqual(["p", "equation-inline", "image"]);
    expect(flattenXmlSourceRows(document.root, []).map((row) => (row.kind === "element" ? row.node.tagName : row.text))).toEqual([
      "p",
      "The calculated reliability index",
      "equation-inline",
      "must be used.",
      "image",
    ]);
  });

  it("collects collapsible branches for aggressive collapsing", () => {
    const document = buildXmlViewerDocument(sampleTree);

    expect(collectCollapsibleNodeIds(document.root)).toEqual(["0", "0.1"]);
  });

  it("parses browser XML through DOMParser when available", () => {
    const documentElement = sampleTree as unknown as Element;
    class MockDOMParser {
      parseFromString() {
        return {
          documentElement,
          getElementsByTagName: () => [],
        };
      }
    }
    vi.stubGlobal("DOMParser", MockDOMParser);

    const parsed = parseXmlViewerDocument("<page />");

    expect("root" in parsed ? parsed.root.tagName : parsed.error).toBe("page");
  });

  it("returns a friendly parse error when DOMParser reports invalid XML", () => {
    class MockDOMParser {
      parseFromString() {
        return {
          documentElement: null,
          getElementsByTagName: () => [{ textContent: "mismatched tag" }],
        };
      }
    }
    vi.stubGlobal("DOMParser", MockDOMParser);

    const parsed = parseXmlViewerDocument("<page>");

    expect("error" in parsed ? parsed.error : "").toContain("mismatched tag");
  });
});
