export type XmlViewerAttribute = {
  name: string;
  value: string;
};

export type XmlViewerTextContent = {
  kind: "text";
  id: string;
  text: string;
};

export type XmlViewerElementContent = {
  kind: "element";
  nodeId: string;
};

export type XmlViewerContentEntry = XmlViewerTextContent | XmlViewerElementContent;

export type XmlViewerNode = {
  id: string;
  tagName: string;
  path: string;
  depth: number;
  attributes: XmlViewerAttribute[];
  directText: string;
  descendantText: string;
  children: XmlViewerNode[];
  content: XmlViewerContentEntry[];
  listMarker: string | null;
};

export type XmlViewerDocument = {
  root: XmlViewerNode;
  nodeCount: number;
  maxDepth: number;
};

export type XmlViewerParseResult = { root: XmlViewerNode; nodeCount: number; maxDepth: number } | { error: string };

export type XmlAttributeLike = {
  name: string;
  value: string;
};

export type XmlTextNodeLike = {
  nodeType: number;
  textContent: string | null;
};

export type XmlElementLike = {
  nodeType?: number;
  tagName: string;
  attributes?: ArrayLike<XmlAttributeLike> | null;
  childNodes?: ArrayLike<XmlElementLike | XmlTextNodeLike> | null;
};

export type XmlViewerSourceRow =
  | {
      kind: "element";
      id: string;
      depth: number;
      node: XmlViewerNode;
    }
  | {
      kind: "text";
      id: string;
      depth: number;
      parentId: string;
      text: string;
      /** True when this text is direct content of an element with `type` glossary markup (e.g. xref). */
      isGlossaryEntry: boolean;
    };

export type XmlViewerParsedSegment = {
  id: string;
  text: string;
  kind: "text" | "child";
  sourceNodeId: string;
  isGlossaryEntry: boolean;
  isStructuralHighlight: boolean;
};

const TEXT_NODE = 3;
const CDATA_SECTION_NODE = 4;
const EQUATION_CONTAINER_TAGS = new Set(["equation-inline", "equation-block"]);

function normalizeWhitespace(value: string | null | undefined): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function arrayFromLike<T>(value: ArrayLike<T> | null | undefined): T[] {
  return value ? Array.from(value) : [];
}

function joinTextSegments(segments: string[]): string {
  return segments
    .map((segment) => normalizeWhitespace(segment))
    .filter(Boolean)
    .join(" ");
}

function indexedPathSegment(tagName: string, siblingIndex: number): string {
  return `${tagName}[${siblingIndex}]`;
}

function hasAttributeValue(attributes: XmlViewerAttribute[], name: string, expectedValue: string): boolean {
  return attributes.some((attribute) => attribute.name === name && attribute.value === expectedValue);
}

const GLOSSARY_TYPE_ATTRIBUTE_VALUES = new Set(["abcb-glossentry", "glossterm"]);
const STRUCTURAL_HIGHLIGHT_TYPE_ATTRIBUTE_VALUES = new Set(["ncc-clause", "part"]);

/** True when `type` is a glossary link (same highlighting as abcb-glossentry for xref-style terms). */
export function isXmlViewerGlossaryType(node: XmlViewerNode): boolean {
  return node.attributes.some(
    (attribute) => attribute.name === "type" && GLOSSARY_TYPE_ATTRIBUTE_VALUES.has(attribute.value)
  );
}

export function isXmlViewerStructuralHighlightType(node: XmlViewerNode): boolean {
  return node.attributes.some(
    (attribute) => attribute.name === "type" && STRUCTURAL_HIGHLIGHT_TYPE_ATTRIBUTE_VALUES.has(attribute.value)
  );
}

function normalizedTagName(tagName: string): string {
  return tagName.toLowerCase();
}

function shouldSuppressXmlViewerText(tagName: string, attributes: XmlViewerAttribute[]): boolean {
  const normalized = normalizedTagName(tagName);
  if (normalized === "image") {
    return true;
  }
  return normalized === "annotation" && attributes.some((attribute) => {
    return attribute.name === "encoding" && attribute.value.toLowerCase() === "mathtype-mtef";
  });
}

function toRomanNumeral(value: number): string {
  const numerals: Array<[number, string]> = [
    [1000, "m"],
    [900, "cm"],
    [500, "d"],
    [400, "cd"],
    [100, "c"],
    [90, "xc"],
    [50, "l"],
    [40, "xl"],
    [10, "x"],
    [9, "ix"],
    [5, "v"],
    [4, "iv"],
    [1, "i"],
  ];
  let remainder = Math.max(1, value);
  let result = "";

  numerals.forEach(([amount, numeral]) => {
    while (remainder >= amount) {
      result += numeral;
      remainder -= amount;
    }
  });

  return result;
}

function toAlphabeticIndex(value: number): string {
  let remainder = Math.max(1, value);
  let result = "";

  while (remainder > 0) {
    remainder -= 1;
    result = String.fromCharCode(97 + (remainder % 26)) + result;
    remainder = Math.floor(remainder / 26);
  }

  return result;
}

function formatListMarker(itemIndex: number, orderedListDepth: number): string {
  return orderedListDepth <= 1 ? `(${toAlphabeticIndex(itemIndex)})` : `(${toRomanNumeral(itemIndex)})`;
}

function buildXmlViewerNode(
  element: XmlElementLike,
  depth: number,
  id: string,
  path: string,
  orderedListDepth = 0,
  parentTagName: string | null = null,
  listItemIndex: number | null = null
): { node: XmlViewerNode; nodeCount: number; maxDepth: number } {
  const attributes = arrayFromLike(element.attributes).map((attribute) => ({
    name: attribute.name,
    value: attribute.value,
  }));
  const elementTagName = normalizedTagName(element.tagName);
  const suppressOwnText = shouldSuppressXmlViewerText(element.tagName, attributes);
  const childNodes = arrayFromLike(element.childNodes);
  const directTextSegments: string[] = [];
  const siblingCounts = new Map<string, number>();
  const children: XmlViewerNode[] = [];
  const content: XmlViewerContentEntry[] = [];
  let nodeCount = 1;
  let maxDepth = depth;
  let textIndex = 0;
  let orderedListItemIndex = 0;

  childNodes.forEach((child) => {
    if (!child || typeof child !== "object") {
      return;
    }
    if ((child as XmlTextNodeLike).nodeType === TEXT_NODE || (child as XmlTextNodeLike).nodeType === CDATA_SECTION_NODE) {
      const text = normalizeWhitespace((child as XmlTextNodeLike).textContent);
      if (text && !suppressOwnText) {
        directTextSegments.push(text);
        const lastEntry = content.at(-1);
        if (lastEntry?.kind === "text") {
          lastEntry.text = joinTextSegments([lastEntry.text, text]);
        } else {
          content.push({
            kind: "text",
            id: `${id}.t${textIndex}`,
            text,
          });
          textIndex += 1;
        }
      }
      return;
    }
    if ((child as XmlElementLike).tagName === undefined) {
      return;
    }
    const childElement = child as XmlElementLike;
    const nextIndex = (siblingCounts.get(childElement.tagName) ?? 0) + 1;
    siblingCounts.set(childElement.tagName, nextIndex);
    const childPath = `${path}/${indexedPathSegment(childElement.tagName, nextIndex)}`;
    const childOrderedListDepth = elementTagName === "ol" ? orderedListDepth + 1 : orderedListDepth;
    const childListItemIndex = elementTagName === "ol" && normalizedTagName(childElement.tagName) === "li" ? ++orderedListItemIndex : null;
    const childBuild = buildXmlViewerNode(
      childElement,
      depth + 1,
      `${id}.${children.length}`,
      childPath,
      childOrderedListDepth,
      element.tagName,
      childListItemIndex
    );
    children.push(childBuild.node);
    content.push({
      kind: "element",
      nodeId: childBuild.node.id,
    });
    nodeCount += childBuild.nodeCount;
    maxDepth = Math.max(maxDepth, childBuild.maxDepth);
  });

  const directText = joinTextSegments(directTextSegments);
  const childById = new Map(children.map((child) => [child.id, child] as const));
  const descendantText = joinTextSegments(
    content.map((entry) => (entry.kind === "text" ? entry.text : childById.get(entry.nodeId)?.descendantText ?? ""))
  );

  return {
    node: {
      id,
      tagName: element.tagName,
      path,
      depth,
      attributes,
      directText,
      descendantText,
      children,
      content,
      listMarker:
        parentTagName === "ol" && elementTagName === "li" && listItemIndex !== null
          ? formatListMarker(listItemIndex, orderedListDepth)
          : null,
    },
    nodeCount,
    maxDepth,
  };
}

export function buildXmlViewerDocument(rootElement: XmlElementLike): XmlViewerDocument {
  const rootPath = `/${indexedPathSegment(rootElement.tagName, 1)}`;
  const built = buildXmlViewerNode(rootElement, 0, "0", rootPath);
  return {
    root: built.node,
    nodeCount: built.nodeCount,
    maxDepth: built.maxDepth,
  };
}

export function parseXmlViewerDocument(xmlSource: string): XmlViewerParseResult {
  if (typeof DOMParser === "undefined") {
    return { error: "XML parsing is unavailable in this runtime." };
  }
  const parser = new DOMParser();
  const document = parser.parseFromString(xmlSource, "application/xml");
  if (document.getElementsByTagName("parsererror").length) {
    const parserError = normalizeWhitespace(document.getElementsByTagName("parsererror")[0]?.textContent);
    return { error: parserError || "The selected XML file could not be parsed." };
  }
  const rootElement = document.documentElement;
  if (!rootElement) {
    return { error: "The selected XML file did not include a root element." };
  }
  return buildXmlViewerDocument(rootElement);
}

export function flattenVisibleXmlNodes(root: XmlViewerNode, collapsedIds: Iterable<string> = []): XmlViewerNode[] {
  const collapsed = new Set(collapsedIds);
  const visible: XmlViewerNode[] = [];

  function visit(node: XmlViewerNode): void {
    visible.push(node);
    if (collapsed.has(node.id) || isXmlViewerEquationNode(node)) {
      return;
    }
    node.children.forEach(visit);
  }

  visit(root);
  return visible;
}

export function flattenXmlSourceRows(root: XmlViewerNode, collapsedIds: Iterable<string> = []): XmlViewerSourceRow[] {
  const collapsed = new Set(collapsedIds);
  const rows: XmlViewerSourceRow[] = [];
  const byId = new Map<string, XmlViewerNode>();

  function index(node: XmlViewerNode): void {
    byId.set(node.id, node);
    node.children.forEach(index);
  }

  function visit(node: XmlViewerNode): void {
    rows.push({
      kind: "element",
      id: node.id,
      depth: node.depth,
      node,
    });
    if (collapsed.has(node.id) || isXmlViewerEquationNode(node)) {
      return;
    }
    node.content.forEach((entry) => {
      if (entry.kind === "text") {
        rows.push({
          kind: "text",
          id: entry.id,
          depth: node.depth + 1,
          parentId: node.id,
          text: entry.text,
          isGlossaryEntry: isXmlViewerGlossaryType(node),
        });
        return;
      }
      const childNode = byId.get(entry.nodeId);
      if (childNode) {
        visit(childNode);
      }
    });
  }

  index(root);
  visit(root);
  return rows;
}

export function getXmlViewerParsedSegments(node: XmlViewerNode): XmlViewerParsedSegment[] {
  const childById = new Map(node.children.map((child) => [child.id, child] as const));

  return node.content
    .map((entry) => {
      if (entry.kind === "text") {
        return {
          id: entry.id,
          text: entry.text,
          kind: "text" as const,
          sourceNodeId: node.id,
          isGlossaryEntry: isXmlViewerGlossaryType(node),
          isStructuralHighlight: isXmlViewerStructuralHighlightType(node),
        };
      }
      const childNode = childById.get(entry.nodeId);
      if (!childNode || !childNode.descendantText) {
        return null;
      }
      return {
        id: `${entry.nodeId}::descendant`,
        text: childNode.descendantText,
        kind: "child" as const,
        sourceNodeId: childNode.id,
        isGlossaryEntry: isXmlViewerGlossaryType(childNode),
        isStructuralHighlight: isXmlViewerStructuralHighlightType(childNode),
      };
    })
    .filter((segment): segment is XmlViewerParsedSegment => Boolean(segment));
}

export function isXmlViewerEquationNode(node: XmlViewerNode): boolean {
  return EQUATION_CONTAINER_TAGS.has(normalizedTagName(node.tagName));
}

export function getXmlViewerMathNode(node: XmlViewerNode): XmlViewerNode | null {
  if (normalizedTagName(node.tagName) === "math") {
    return node;
  }

  for (const child of node.children) {
    const mathNode = getXmlViewerMathNode(child);
    if (mathNode) {
      return mathNode;
    }
  }

  return null;
}

export function getNextXmlViewerSourceTextSelection(
  currentSelectedId: string | null,
  segment: XmlViewerParsedSegment
): string | null {
  if (segment.kind !== "text") {
    return currentSelectedId;
  }
  return currentSelectedId === segment.id ? null : segment.id;
}

export function getXmlViewerElementPathIdsForTextId(textId: string): string[] {
  const elementId = textId.replace(/\.t\d+$/, "");
  const segments = elementId.split(".");
  const pathIds: string[] = [];

  segments.forEach((_, index) => {
    pathIds.push(segments.slice(0, index + 1).join("."));
  });

  return pathIds;
}

export function collectCollapsibleNodeIds(root: XmlViewerNode): string[] {
  const ids: string[] = [];

  function visit(node: XmlViewerNode): void {
    if (node.children.length) {
      ids.push(node.id);
      node.children.forEach(visit);
    }
  }

  visit(root);
  return ids;
}

export function getDefaultCollapsedNodeIds(root: XmlViewerNode, expandedDepth = 1): string[] {
  const collapsedIds: string[] = [];

  function visit(node: XmlViewerNode): void {
    if (!node.children.length) {
      return;
    }
    if (node.depth >= expandedDepth) {
      collapsedIds.push(node.id);
      return;
    }
    node.children.forEach(visit);
  }

  visit(root);
  return collapsedIds;
}

export function toggleCollapsedNode(collapsedIds: Iterable<string>, nodeId: string): string[] {
  const next = new Set(collapsedIds);
  if (next.has(nodeId)) {
    next.delete(nodeId);
  } else {
    next.add(nodeId);
  }
  return Array.from(next).sort();
}
