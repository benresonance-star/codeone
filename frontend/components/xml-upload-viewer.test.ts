import { describe, expect, it } from "vitest";

import { buildXmlViewerDocument, type XmlAttributeLike, type XmlElementLike } from "../lib/xml-viewer";
import { extractXmlViewerTableModel, shouldRenderParsedInlineFlowChild } from "./xml-upload-viewer";

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

describe("xml upload viewer table extraction", () => {
  it("extracts heading, headers, key column, and body rows from a CALS-style table reference", () => {
    const tree = element("table-reference", {
      attributes: [{ name: "graph", value: "None" }],
      children: [
        element("num", { children: [text("1")] }),
        element("title", { children: [text("Alpine areas where snow loads are significant")] }),
        element("table", {
          attributes: [{ name: "keycol", value: "1" }],
          children: [
            element("tgroup", {
              attributes: [{ name: "cols", value: "2" }],
              children: [
                element("thead", {
                  children: [
                    element("row", {
                      children: [element("entry", { children: [text("Location")] }), element("entry", { children: [text("Map identifier")] })],
                    }),
                  ],
                }),
                element("tbody", {
                  children: [
                    element("row", {
                      children: [element("entry", { children: [text("Kiandra (NSW)")] }), element("entry", { children: [text("1")] })],
                    }),
                    element("row", {
                      children: [
                        element("entry", {
                          children: [
                            text("Falls Creek (Vic.), including "),
                            element("xref", {
                              attributes: [{ name: "type", value: "abcb-glossentry" }],
                              children: [text("Summit Area")],
                            }),
                            text(", Sun Valley and Village Bowl"),
                          ],
                        }),
                        element("entry", { children: [text("17")] }),
                      ],
                    }),
                  ],
                }),
              ],
            }),
          ],
        }),
      ],
    });

    const document = buildXmlViewerDocument(tree);
    const model = extractXmlViewerTableModel(document.root);

    expect(model).not.toBeNull();
    expect(model?.headingNumberNode?.descendantText).toBe("1");
    expect(model?.headingTitleNode?.descendantText).toBe("Alpine areas where snow loads are significant");
    expect(model?.colCount).toBe(2);
    expect(model?.keyColumnIndex).toBe(0);
    expect(model?.headerRows.map((row) => row.map((cell) => cell.descendantText))).toEqual([["Location", "Map identifier"]]);
    expect(model?.bodyRows.map((row) => row.map((cell) => cell.descendantText))).toEqual([
      ["Kiandra (NSW)", "1"],
      ["Falls Creek (Vic.), including Summit Area, Sun Valley and Village Bowl", "17"],
    ]);
    expect(model?.bodyRows[1]?.[0]?.children[0]?.tagName).toBe("xref");
  });

  it("extracts a bare table node even when there is no table-reference wrapper", () => {
    const tree = element("table", {
      children: [
        element("tgroup", {
          children: [
            element("tbody", {
              children: [
                element("row", {
                  children: [element("entry", { children: [text("Alpha")] }), element("entry", { children: [text("Beta")] })],
                }),
              ],
            }),
          ],
        }),
      ],
    });

    const document = buildXmlViewerDocument(tree);
    const model = extractXmlViewerTableModel(document.root);

    expect(model?.headingNumberNode).toBeNull();
    expect(model?.headingTitleNode).toBeNull();
    expect(model?.bodyRows.map((row) => row.map((cell) => cell.descendantText))).toEqual([["Alpha", "Beta"]]);
  });
});

describe("parsed inline-flow child detection", () => {
  it("keeps lightweight phrasing wrappers inline inside prose", () => {
    const tree = element("p", {
      children: [
        text("protect occupant health and"),
        element("ph", { children: [text("amenity")] }),
        text("by ensuring the building envelope assists"),
      ],
    });

    const document = buildXmlViewerDocument(tree);

    expect(shouldRenderParsedInlineFlowChild(document.root.children[0]!)).toBe(true);
  });

  it("keeps track-change wrappers inline when they carry visible text", () => {
    const tree = element("p", {
      children: [
        text("A building must"),
        element("xt:insText", { children: [text("reduce")] }),
        text("the energy consumption."),
      ],
    });

    const document = buildXmlViewerDocument(tree);

    expect(shouldRenderParsedInlineFlowChild(document.root.children[0]!)).toBe(true);
  });

  it("does not inline block-shaped descendants like lists", () => {
    const tree = element("p", {
      children: [
        text("Conditions include"),
        element("note", {
          children: [
            element("ol", {
              children: [element("li", { children: [text("Alpha")] })],
            }),
          ],
        }),
      ],
    });

    const document = buildXmlViewerDocument(tree);

    expect(shouldRenderParsedInlineFlowChild(document.root.children[0]!)).toBe(false);
  });
});
