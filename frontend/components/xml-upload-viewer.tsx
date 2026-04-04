"use client";

import { createElement, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
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
  type XmlViewerNode,
  type XmlViewerParseResult,
} from "../lib/xml-viewer";

const INLINE_FLOW_TAGS = new Set(["p", "li", "entry", "title", "sptc", "num"]);
const XML_TABLE_SECTION_TAGS = new Set(["thead", "tbody"]);

export type XmlViewerTableModel = {
  headingNumberNode: XmlViewerNode | null;
  headingTitleNode: XmlViewerNode | null;
  headerRows: XmlViewerNode[][];
  bodyRows: XmlViewerNode[][];
  colCount: number;
  keyColumnIndex: number | null;
};

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function renderTagOpen(tagName: string, attributes: Array<{ name: string; value: string }>): string {
  const attributeText = attributes.map((attribute) => `${attribute.name}="${attribute.value}"`).join(" ");
  return attributeText ? `<${tagName} ${attributeText}>` : `<${tagName}>`;
}

function summarizeDescendantPreview(value: string, maxLength = 180): string {
  const normalized = value.trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trimEnd()}...`;
}

function isGlossaryNode(node: XmlViewerNode): boolean {
  return node.attributes.some((attribute) => attribute.name === "type" && attribute.value === "abcb-glossentry");
}

function previewHeadlineTags(tagName: string): string[] {
  if (tagName === "clause") {
    return ["sptc", "title"];
  }
  if (tagName === "subclause") {
    return ["title", "num"];
  }
  return [];
}

function normalizedTagName(tagName: string): string {
  return tagName.toLowerCase();
}

function isInlineFlowTag(tagName: string): boolean {
  return INLINE_FLOW_TAGS.has(normalizedTagName(tagName));
}

function isInlineEquationNode(node: XmlViewerNode): boolean {
  return normalizedTagName(node.tagName) === "equation-inline";
}

function isXmlViewerTableReferenceNode(node: XmlViewerNode): boolean {
  return normalizedTagName(node.tagName) === "table-reference";
}

function isXmlViewerTableNode(node: XmlViewerNode): boolean {
  return normalizedTagName(node.tagName) === "table";
}

function isXmlViewerTableRowNode(node: XmlViewerNode): boolean {
  return normalizedTagName(node.tagName) === "row";
}

function isXmlViewerTableCellNode(node: XmlViewerNode): boolean {
  return normalizedTagName(node.tagName) === "entry";
}

function getFirstDirectChildByTagName(node: XmlViewerNode, tagName: string): XmlViewerNode | null {
  const normalized = normalizedTagName(tagName);
  return node.children.find((child) => normalizedTagName(child.tagName) === normalized) ?? null;
}

function getDirectChildrenByTagNames(node: XmlViewerNode, tagNames: Set<string>): XmlViewerNode[] {
  return node.children.filter((child) => tagNames.has(normalizedTagName(child.tagName)));
}

function getTableRowsFromSection(node: XmlViewerNode): XmlViewerNode[][] {
  return node.children
    .filter(isXmlViewerTableRowNode)
    .map((rowNode) => rowNode.children.filter(isXmlViewerTableCellNode));
}

export function extractXmlViewerTableModel(node: XmlViewerNode): XmlViewerTableModel | null {
  const tableNode = isXmlViewerTableReferenceNode(node) ? getFirstDirectChildByTagName(node, "table") : isXmlViewerTableNode(node) ? node : null;
  if (!tableNode) {
    return null;
  }

  const tgroupNode = getFirstDirectChildByTagName(tableNode, "tgroup");
  const gridRoot = tgroupNode ?? tableNode;
  const sectionNodes = getDirectChildrenByTagNames(gridRoot, XML_TABLE_SECTION_TAGS);
  const theadNode = sectionNodes.find((child) => normalizedTagName(child.tagName) === "thead") ?? null;
  const tbodyNode = sectionNodes.find((child) => normalizedTagName(child.tagName) === "tbody") ?? null;
  const headerRows = theadNode ? getTableRowsFromSection(theadNode) : [];
  const bodyRows = tbodyNode
    ? getTableRowsFromSection(tbodyNode)
    : gridRoot.children.filter(isXmlViewerTableRowNode).map((rowNode) => rowNode.children.filter(isXmlViewerTableCellNode));
  const colCount = Math.max(0, ...headerRows.map((row) => row.length), ...bodyRows.map((row) => row.length));
  const keyColumnValue = tableNode.attributes.find((attribute) => attribute.name === "keycol")?.value;
  const keyColumnIndex = keyColumnValue ? Math.max(0, Number.parseInt(keyColumnValue, 10) - 1) : null;

  if (!colCount && !headerRows.length && !bodyRows.length) {
    return null;
  }

  return {
    headingNumberNode: isXmlViewerTableReferenceNode(node) ? getFirstDirectChildByTagName(node, "num") : null,
    headingTitleNode: isXmlViewerTableReferenceNode(node) ? getFirstDirectChildByTagName(node, "title") : null,
    headerRows,
    bodyRows,
    colCount,
    keyColumnIndex: Number.isFinite(keyColumnIndex) ? keyColumnIndex : null,
  };
}

function renderMathMlNode(node: XmlViewerNode, keyPrefix: string): ReactNode {
  const props: Record<string, string> = {
    key: keyPrefix,
  };
  if (normalizedTagName(node.tagName) === "math") {
    props.xmlns = "http://www.w3.org/1998/Math/MathML";
  }
  node.attributes.forEach((attribute) => {
    props[attribute.name === "class" ? "className" : attribute.name] = attribute.value;
  });
  const childById = new Map(node.children.map((child) => [child.id, child] as const));
  const children = node.content
    .map((entry, index) => {
      if (entry.kind === "text") {
        return entry.text;
      }
      const childNode = childById.get(entry.nodeId);
      return childNode ? renderMathMlNode(childNode, `${keyPrefix}-${index}-${childNode.id}`) : null;
    })
    .filter((child): child is ReactNode => child !== null);
  return createElement(node.tagName, props, ...children);
}

function renderEquationNode(node: XmlViewerNode, keyPrefix: string): ReactNode {
  const mathNode = getXmlViewerMathNode(node);
  if (!mathNode) {
    return <span className="xml-math-fallback">Equation</span>;
  }
  const equation = renderMathMlNode(mathNode, `${keyPrefix}-${mathNode.id}`);
  if (isInlineEquationNode(node)) {
    return <span className="xml-math-inline">{equation}</span>;
  }
  return (
    <div className="xml-math-block-shell">
      <div className="xml-math-block">{equation}</div>
    </div>
  );
}

function renderTableSectionRow(
  row: XmlViewerNode[],
  keyPrefix: string,
  colCount: number,
  keyColumnIndex: number | null,
  renderCell: (cell: XmlViewerNode, keyPrefix: string) => ReactNode,
  cellTagName: "th" | "td"
): ReactNode {
  const cells: ReactNode[] = row.map((cell, index) => {
    const TagName = cellTagName;
    const isKeyColumn = keyColumnIndex !== null && index === keyColumnIndex;
    return (
      <TagName
        key={`${keyPrefix}-${cell.id}`}
        className={`xml-parsed-table-cell ${isKeyColumn ? "xml-parsed-table-cell-key" : ""} ${cellTagName === "th" ? "xml-parsed-table-head-cell" : ""}`}
      >
        {renderCell(cell, `${keyPrefix}-${cell.id}`)}
      </TagName>
    );
  });

  for (let index = row.length; index < colCount; index += 1) {
    const TagName = cellTagName;
    const isKeyColumn = keyColumnIndex !== null && index === keyColumnIndex;
    cells.push(
      <TagName
        key={`${keyPrefix}-empty-${index}`}
        className={`xml-parsed-table-cell xml-parsed-table-cell-empty ${isKeyColumn ? "xml-parsed-table-cell-key" : ""} ${cellTagName === "th" ? "xml-parsed-table-head-cell" : ""}`}
      />
    );
  }

  return <tr key={keyPrefix}>{cells}</tr>;
}

function renderSourcePreviewBody(node: XmlViewerNode, keyPrefix: string): ReactNode {
  const headlineTags = new Set(previewHeadlineTags(node.tagName));
  const headlineChildren = node.children.filter((child) => headlineTags.has(child.tagName) && child.descendantText);
  const bodyChildren = node.children.filter((child) => !headlineTags.has(child.tagName) && child.descendantText);

  if (!headlineChildren.length && !bodyChildren.length) {
    return summarizeDescendantPreview(node.descendantText);
  }

  return (
    <>
      {headlineChildren.length ? (
        <div className="xml-tree-preview-headline">
          {headlineChildren.map((child) => (
            <span key={`${keyPrefix}-${child.id}`} className="xml-tree-preview-headline-part">
              {child.descendantText}
            </span>
          ))}
        </div>
      ) : null}
      {bodyChildren.map((child) =>
        child.tagName === "ol" ? (
          <div key={`${keyPrefix}-${child.id}-list`} className="xml-tree-preview-list">
            {child.children
              .filter((item) => item.tagName === "li" && item.descendantText)
              .map((item) => (
                <div key={`${keyPrefix}-${item.id}`} className="xml-tree-preview-list-item">
                  <span className="xml-tree-preview-prefix">{item.listMarker ?? "(-)"}</span>
                  <div className="xml-tree-preview-list-content">{summarizeDescendantPreview(item.descendantText, 220)}</div>
                </div>
              ))}
          </div>
        ) : (
          <div key={`${keyPrefix}-${child.id}-block`} className="xml-tree-preview-block">
            {summarizeDescendantPreview(child.descendantText, 220)}
          </div>
        )
      )}
    </>
  );
}

export function XmlUploadViewer({ files }: { files: File[] }) {
  const [preferredActiveFileKey, setPreferredActiveFileKey] = useState<string | null>(null);
  const [viewerCache, setViewerCache] = useState<Record<string, XmlViewerParseResult>>({});
  const [collapsedByFile, setCollapsedByFile] = useState<Record<string, string[]>>({});
  const [selectedSourceTextId, setSelectedSourceTextId] = useState<string | null>(null);
  const sourceTextButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const parsedSegmentButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const activeFileKey = useMemo(() => {
    if (!files.length) {
      return null;
    }
    if (preferredActiveFileKey && files.some((file) => fileKey(file) === preferredActiveFileKey)) {
      return preferredActiveFileKey;
    }
    return fileKey(files[0]);
  }, [files, preferredActiveFileKey]);
  const activeFile = useMemo(() => files.find((candidate) => fileKey(candidate) === activeFileKey) ?? null, [activeFileKey, files]);

  useEffect(() => {
    if (!activeFile) {
      return;
    }
    const key = fileKey(activeFile);
    if (viewerCache[key]) {
      return;
    }

    let cancelled = false;

    activeFile
      .text()
      .then((source) => {
        if (cancelled) {
          return;
        }
        const parsed = parseXmlViewerDocument(source);
        setViewerCache((current) => ({ ...current, [key]: parsed }));
        if ("root" in parsed) {
          setCollapsedByFile((current) =>
            current[key] ? current : { ...current, [key]: getDefaultCollapsedNodeIds(parsed.root) }
          );
        }
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setViewerCache((current) => ({
          ...current,
          [key]: { error: error instanceof Error ? error.message : "The selected XML file could not be read." },
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [activeFile, viewerCache]);

  const activeResult = activeFileKey ? viewerCache[activeFileKey] ?? null : null;
  const activeCollapsed = useMemo(
    () => (activeFileKey ? collapsedByFile[activeFileKey] ?? [] : []),
    [activeFileKey, collapsedByFile]
  );
  const sourceRows = useMemo(
    () => (activeResult && "root" in activeResult ? flattenXmlSourceRows(activeResult.root, activeCollapsed) : []),
    [activeCollapsed, activeResult]
  );
  const visibleNodes = useMemo(
    () => (activeResult && "root" in activeResult ? flattenVisibleXmlNodes(activeResult.root, activeCollapsed) : []),
    [activeCollapsed, activeResult]
  );
  const sourceTextRows = useMemo(() => sourceRows.filter((row) => row.kind === "text"), [sourceRows]);
  const activeSelectedSourceTextId = useMemo(() => {
    if (!selectedSourceTextId) {
      return null;
    }
    return sourceTextRows.some((row) => row.id === selectedSourceTextId) ? selectedSourceTextId : null;
  }, [selectedSourceTextId, sourceTextRows]);
  const selectedSourceTextRow = useMemo(
    () => sourceTextRows.find((row) => row.id === activeSelectedSourceTextId) ?? null,
    [activeSelectedSourceTextId, sourceTextRows]
  );
  const activeNodeCount = activeResult && "root" in activeResult ? activeResult.nodeCount : 0;
  const activeMaxDepth = activeResult && "root" in activeResult ? activeResult.maxDepth : 0;

  function activateSourceTextSelection(nextId: string | null): void {
    if (activeFileKey && nextId) {
      const elementPathIds = getXmlViewerElementPathIdsForTextId(nextId);
      setCollapsedByFile((current) => {
        const collapsed = new Set(current[activeFileKey] ?? []);
        let changed = false;

        elementPathIds.forEach((id) => {
          if (collapsed.delete(id)) {
            changed = true;
          }
        });

        if (!changed) {
          return current;
        }

        return {
          ...current,
          [activeFileKey]: Array.from(collapsed).sort(),
        };
      });
    }

    setSelectedSourceTextId(nextId);
  }

  useEffect(() => {
    if (!activeSelectedSourceTextId) {
      return;
    }

    const sourceButton = sourceTextButtonRefs.current[activeSelectedSourceTextId];
    const parsedButton = parsedSegmentButtonRefs.current[activeSelectedSourceTextId];
    const frame = requestAnimationFrame(() => {
      sourceButton?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
      parsedButton?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
        inline: "nearest",
      });
    });

    return () => cancelAnimationFrame(frame);
  }, [activeSelectedSourceTextId, sourceRows]);

  function toggleNode(nodeId: string): void {
    if (!activeFileKey) {
      return;
    }
    setCollapsedByFile((current) => ({
      ...current,
      [activeFileKey]: toggleCollapsedNode(current[activeFileKey] ?? [], nodeId),
    }));
  }

  function expandAll(): void {
    if (!activeFileKey) {
      return;
    }
    setCollapsedByFile((current) => ({ ...current, [activeFileKey]: [] }));
  }

  function collapseBranches(): void {
    if (!activeFileKey || !activeResult || !("root" in activeResult)) {
      return;
    }
    setCollapsedByFile((current) => ({
      ...current,
      [activeFileKey]: collectCollapsibleNodeIds(activeResult.root).filter((id) => id !== activeResult.root.id),
    }));
  }

  function renderParsedSegments(
    segments: ReturnType<typeof getXmlViewerParsedSegments>,
    keyPrefix: string
  ): ReactNode[] {
    return segments.map((segment, index) => {
      const isSelected = segment.kind === "text" && segment.id === activeSelectedSourceTextId;
      const className = `xml-parsed-segment ${segment.kind === "child" ? "xml-parsed-segment-child" : ""} ${segment.isGlossaryEntry ? "xml-parsed-segment-glossary" : ""} ${isSelected ? "xml-parsed-segment-selected" : ""}`;
      return segment.kind === "text" ? (
        <button
          key={`${keyPrefix}-${segment.id}`}
          type="button"
          className={`${className} xml-parsed-segment-button`}
          aria-pressed={isSelected}
          onClick={() => activateSourceTextSelection(getNextXmlViewerSourceTextSelection(activeSelectedSourceTextId, segment))}
          ref={(element) => {
            parsedSegmentButtonRefs.current[segment.id] = element;
          }}
        >
          {segment.text}
          {index < segments.length - 1 ? " " : ""}
        </button>
      ) : (
        <span key={`${keyPrefix}-${segment.id}`} className={className}>
          {segment.text}
          {index < segments.length - 1 ? " " : ""}
        </span>
      );
    });
  }

  function renderParsedNodeBody(node: XmlViewerNode, keyPrefix: string, includeOwnListMarker = true): ReactNode {
    if (isXmlViewerEquationNode(node)) {
      return renderEquationNode(node, keyPrefix);
    }

    const tableModel = extractXmlViewerTableModel(node);
    if (tableModel) {
      return (
        <div className="xml-parsed-table-panel">
          {tableModel.headingNumberNode || tableModel.headingTitleNode ? (
            <div className="xml-parsed-table-heading">
              {tableModel.headingNumberNode ? (
                <div className="xml-parsed-table-number">
                  {renderParsedNodeBody(tableModel.headingNumberNode, `${keyPrefix}-${tableModel.headingNumberNode.id}`, false)}
                </div>
              ) : null}
              {tableModel.headingTitleNode ? (
                <div className="xml-parsed-table-title">
                  {renderParsedNodeBody(tableModel.headingTitleNode, `${keyPrefix}-${tableModel.headingTitleNode.id}`, false)}
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="xml-parsed-table-shell">
            <table className="xml-parsed-table-grid">
              {tableModel.headerRows.length ? (
                <thead>
                  {tableModel.headerRows.map((row, index) =>
                    renderTableSectionRow(
                      row,
                      `${keyPrefix}-head-${index}`,
                      tableModel.colCount,
                      tableModel.keyColumnIndex,
                      (cell, cellKeyPrefix) => renderParsedNodeBody(cell, cellKeyPrefix, false),
                      "th"
                    )
                  )}
                </thead>
              ) : null}
              <tbody>
                {tableModel.bodyRows.map((row, index) =>
                  renderTableSectionRow(
                    row,
                    `${keyPrefix}-body-${index}`,
                    tableModel.colCount,
                    tableModel.keyColumnIndex,
                    (cell, cellKeyPrefix) => renderParsedNodeBody(cell, cellKeyPrefix, false),
                    "td"
                  )
                )}
              </tbody>
            </table>
          </div>
        </div>
      );
    }

    const childById = new Map(node.children.map((child) => [child.id, child] as const));
    const parts: ReactNode[] = [];
    const headlineTags = new Set(previewHeadlineTags(node.tagName));
    const keepsInlineFlow = isInlineFlowTag(node.tagName);
    const headlineChildren = node.content
      .map((entry) => (entry.kind === "element" ? childById.get(entry.nodeId) ?? null : null))
      .filter((child): child is XmlViewerNode => child !== null && headlineTags.has(child.tagName));
    const headlineChildIds = new Set(headlineChildren.map((child) => child.id));

    if (includeOwnListMarker && node.listMarker) {
      parts.push(
        <span key={`${keyPrefix}-prefix`} className="xml-parsed-prefix">
          {node.listMarker}{" "}
        </span>
      );
    }

    if (headlineChildren.length) {
      parts.push(
        <div key={`${keyPrefix}-headline`} className="xml-parsed-preview-headline">
          {headlineChildren.map((child) => (
            <span key={`${keyPrefix}-${child.id}`} className="xml-parsed-preview-headline-part">
              {renderParsedSegments(getXmlViewerParsedSegments(child), `${keyPrefix}-${child.id}`)}
            </span>
          ))}
        </div>
      );
    }

    node.content.forEach((entry, index) => {
      if (entry.kind === "text") {
        const content = renderParsedSegments(
          [
            {
              id: entry.id,
              text: entry.text,
              kind: "text",
              sourceNodeId: node.id,
              isGlossaryEntry: isGlossaryNode(node),
            },
          ],
          `${keyPrefix}-text-${index}`
        );
        parts.push(
          keepsInlineFlow ? (
            <span key={`${keyPrefix}-text-inline-${index}`} className="xml-parsed-inline-run">
              {content}
            </span>
          ) : (
            <div key={`${keyPrefix}-text-block-${index}`} className="xml-parsed-content-block">
              {content}
            </div>
          )
        );
        return;
      }

      const childNode = childById.get(entry.nodeId);
      if (!childNode || !childNode.descendantText) {
        return;
      }
      if (headlineChildIds.has(childNode.id)) {
        return;
      }

      if (isXmlViewerEquationNode(childNode)) {
        parts.push(
          isInlineEquationNode(childNode) ? (
            <span key={`${keyPrefix}-${childNode.id}-math-inline`} className="xml-parsed-inline-run">
              {renderEquationNode(childNode, `${keyPrefix}-${childNode.id}`)}
            </span>
          ) : (
            <div key={`${keyPrefix}-${childNode.id}-math-block`} className="xml-parsed-content-block xml-parsed-content-block-equation">
              {renderEquationNode(childNode, `${keyPrefix}-${childNode.id}`)}
            </div>
          )
        );
        return;
      }

      if (childNode.tagName === "ol") {
        const listItems = childNode.children.filter((child) => child.tagName === "li");
        parts.push(
          <div key={`${keyPrefix}-${childNode.id}-list`} className="xml-parsed-list">
            {listItems.map((item) => (
              <div key={`${keyPrefix}-${item.id}`} className="xml-parsed-list-item">
                <span className="xml-parsed-prefix">{item.listMarker ?? "(-)"}</span>
                <div className="xml-parsed-list-content">{renderParsedNodeBody(item, `${keyPrefix}-${item.id}`, false)}</div>
              </div>
            ))}
          </div>
        );
        return;
      }

      if (childNode.tagName === "clause" || childNode.tagName === "subclause") {
        parts.push(
          <div
            key={`${keyPrefix}-${childNode.id}-structured`}
            className={`xml-parsed-content-block ${childNode.tagName === "subclause" ? "xml-parsed-content-block-subclause" : ""}`}
          >
            {renderParsedNodeBody(childNode, `${keyPrefix}-${childNode.id}`, false)}
          </div>
        );
        return;
      }

      if (isGlossaryNode(childNode) || childNode.tagName === "xref" || childNode.tagName === "sup" || childNode.tagName === "sub") {
        parts.push(...renderParsedSegments(getXmlViewerParsedSegments(childNode), `${keyPrefix}-${childNode.id}`));
        return;
      }

      parts.push(
        <div key={`${keyPrefix}-${childNode.id}-block`} className="xml-parsed-content-block">
          {renderParsedSegments(getXmlViewerParsedSegments(childNode), `${keyPrefix}-${childNode.id}`)}
        </div>
      );
    });

    return parts.length ? parts : "Structural node only. Expand deeper branches to inspect child content.";
  }

  return (
    <section className="panel-muted xml-reader-panel">
      <div className="section-header compact">
        <div>
          <span className="eyebrow">Session-only viewer</span>
          <h3>XML Reader</h3>
          <p className="muted">
            Inspect the currently selected upload files before scanning. The left pane keeps the raw XML tree
            collapsible, while the right pane mirrors the same visible nodes with tags stripped down to text content.
          </p>
        </div>
        <div className="xml-reader-toolbar">
          <button type="button" className="button-secondary" onClick={expandAll} disabled={!visibleNodes.length}>
            Expand all
          </button>
          <button type="button" className="button-secondary" onClick={collapseBranches} disabled={!visibleNodes.length}>
            Collapse branches
          </button>
        </div>
      </div>

      {!files.length ? (
        <div className="empty-state">
          Select one or more XML files above to preview their tree structure and text content before running batch
          discovery.
        </div>
      ) : (
        <>
          <div className="xml-reader-filetabs" role="tablist" aria-label="Selected XML files">
            {files.map((file) => {
              const key = fileKey(file);
              const result = viewerCache[key];
              const status = result ? ("error" in result ? "invalid" : "ready") : activeFileKey === key ? "loading" : "queued";
              return (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  className={`xml-reader-filetab ${activeFileKey === key ? "active" : ""}`}
                  aria-selected={activeFileKey === key}
                  onClick={() => setPreferredActiveFileKey(key)}
                >
                  <span>{file.name}</span>
                  <span className={`xml-reader-filetab-status xml-reader-filetab-status-${status}`}>{status}</span>
                </button>
              );
            })}
          </div>

          {activeFile ? (
            <div className="xml-reader-meta">
              <div>
                <strong>Active file</strong>: <code className="baseline-inline-code">{activeFile.name}</code>
              </div>
              <div>
                <strong>Size</strong>: {(activeFile.size / 1024).toFixed(activeFile.size >= 1024 ? 1 : 0)} KB
              </div>
              <div>
                <strong>Nodes</strong>: {activeNodeCount || "n/a"}
              </div>
              <div>
                <strong>Max depth</strong>: {activeMaxDepth || "n/a"}
              </div>
              <div>
                <strong>Visible rows</strong>: {visibleNodes.length || "n/a"}
              </div>
            </div>
          ) : null}

          {activeFileKey && !activeResult ? (
            <p className="schema-detail-explainer">Reading and parsing the selected XML file...</p>
          ) : null}

          {activeResult && "error" in activeResult ? (
            <div className="alert alert-error" role="alert">
              {activeResult.error}
            </div>
          ) : null}

          {activeResult && "root" in activeResult ? (
            <div className="xml-reader-grid">
              <section className="xml-reader-pane" aria-label="Source XML tree">
                <div className="xml-reader-pane-header">
                  <h4>Source tree</h4>
                  <p className="muted">Collapse nodes here to inspect opening tags, mixed text content, and child elements in source order.</p>
                </div>
                <div className="xml-reader-rows">
                  {sourceRows.map((row) => {
                    if (row.kind === "text") {
                      const isSelected = row.id === activeSelectedSourceTextId;
                      return (
                        <div key={row.id} className="xml-tree-row xml-tree-row-text" style={{ paddingLeft: `${row.depth * 22 + 12}px` }}>
                          <span className="xml-tree-text-marker" aria-hidden="true">
                            &quot;
                          </span>
                          <button
                            type="button"
                            className={`xml-tree-text-card xml-tree-text-button ${isSelected ? "is-selected" : ""}`}
                            onClick={() => activateSourceTextSelection(activeSelectedSourceTextId === row.id ? null : row.id)}
                            aria-pressed={isSelected}
                            ref={(element) => {
                              sourceTextButtonRefs.current[row.id] = element;
                            }}
                          >
                            <div className="xml-tree-text">{row.text}</div>
                            <div className="xml-tree-row-meta">
                              <span className="xml-reader-badge xml-reader-badge-accent">text node</span>
                              {isSelected ? <span className="xml-reader-badge">linked</span> : null}
                            </div>
                          </button>
                        </div>
                      );
                    }

                    const { node } = row;
                    const collapsed = activeCollapsed.includes(node.id);
                    const hasChildren = node.children.length > 0 && !isXmlViewerEquationNode(node);
                    const usesStructuredPreview = node.tagName === "subclause" || node.tagName === "clause";
                    const descendantPreview =
                      !node.directText && (hasChildren || isXmlViewerEquationNode(node)) && node.descendantText
                        ? usesStructuredPreview
                          ? renderSourcePreviewBody(node, row.id)
                          : summarizeDescendantPreview(node.descendantText)
                        : null;
                    return (
                      <div
                        key={row.id}
                        className={`xml-tree-row ${hasChildren ? "xml-tree-row-branch" : "xml-tree-row-leaf"}`}
                        style={{ paddingLeft: `${row.depth * 22 + 12}px` }}
                      >
                        <button
                          type="button"
                          className="xml-tree-toggle"
                          onClick={() => {
                            if (hasChildren) {
                              toggleNode(node.id);
                            }
                          }}
                          disabled={!hasChildren}
                          aria-label={hasChildren ? `${collapsed ? "Expand" : "Collapse"} ${node.tagName}` : `${node.tagName} has no children`}
                        >
                          {hasChildren ? (collapsed ? "+" : "-") : "·"}
                        </button>
                        <div className="xml-tree-card">
                          <div className="xml-tree-code">{renderTagOpen(node.tagName, node.attributes)}</div>
                          <div className="xml-tree-row-meta">
                            <code className="baseline-inline-code">{node.path}</code>
                            {hasChildren ? (
                              <span className="xml-reader-badge">{collapsed ? `${node.children.length} hidden` : `${node.children.length} children`}</span>
                            ) : (
                              <span className="xml-reader-badge">leaf</span>
                            )}
                            {isXmlViewerEquationNode(node) ? <span className="xml-reader-badge xml-reader-badge-accent">math</span> : null}
                            {node.directText ? <span className="xml-reader-badge xml-reader-badge-accent">mixed text</span> : null}
                            {descendantPreview ? <span className="xml-reader-badge">descendant preview</span> : null}
                          </div>
                          {descendantPreview ? (
                            <div className={`xml-tree-descendant-preview ${usesStructuredPreview ? "xml-tree-descendant-preview-subclause" : ""}`}>
                              {descendantPreview}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="xml-reader-pane" aria-label="Parsed XML text by node">
                <div className="xml-reader-pane-header">
                  <h4>Parsed text</h4>
                  <p className="muted">Each row shows the tag-stripped text carried by the same visible node. Click a direct text segment in either pane to mirror the selection.</p>
                </div>
                <div className="xml-reader-rows">
                  {visibleNodes.map((node) => {
                    const parsedSegments = getXmlViewerParsedSegments(node);
                    const hasSelectedSegment = Boolean(
                      activeSelectedSourceTextId && node.descendantText && node.descendantText.includes(selectedSourceTextRow?.text ?? "")
                    );

                    return (
                      <div
                        key={`${node.id}-parsed`}
                        className={`xml-parsed-row ${node.descendantText ? "" : "xml-parsed-row-empty"} ${hasSelectedSegment ? "xml-parsed-row-selected" : ""}`}
                        style={{ paddingLeft: `${node.depth * 22 + 12}px` }}
                      >
                        <div className="xml-parsed-row-header">
                          <strong>{node.tagName}</strong>
                          <div className="xml-parsed-row-badges">
                            {node.directText ? <span className="xml-reader-badge xml-reader-badge-accent">direct</span> : null}
                            {node.children.length ? <span className="xml-reader-badge">subtree</span> : <span className="xml-reader-badge">leaf</span>}
                            {node.listMarker ? <span className="xml-reader-badge xml-reader-badge-accent">list item</span> : null}
                            {isXmlViewerEquationNode(node) ? <span className="xml-reader-badge xml-reader-badge-accent">math</span> : null}
                            {extractXmlViewerTableModel(node) ? <span className="xml-reader-badge xml-reader-badge-accent">table</span> : null}
                            {selectedSourceTextRow?.parentId === node.id ? <span className="xml-reader-badge">linked selection</span> : null}
                          </div>
                        </div>
                        <div className={`xml-parsed-text ${node.tagName === "subclause" ? "xml-parsed-text-subclause" : ""}`}>
                          {parsedSegments.length || node.children.length
                            ? renderParsedNodeBody(node, node.id)
                            : "Structural node only. Expand deeper branches to inspect child content."}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
