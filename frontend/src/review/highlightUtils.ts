import type { BBox, Rect, Viewport } from "./highlightTypes";

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

export function normalizeBBox(
  raw: BBox | number[] | null | undefined,
  fallbackPage?: number,
): BBox | null {
  if (!raw) {
    return null;
  }

  if (Array.isArray(raw)) {
    if (raw.length !== 4) {
      return null;
    }
    const [x1, y1, x2, y2] = raw.map((item) => Number(item) || 0);
    return { x1, y1, x2, y2, page: fallbackPage };
  }

  const x1 = Number(raw.x1);
  const y1 = Number(raw.y1);
  const x2 = Number(raw.x2);
  const y2 = Number(raw.y2);

  if ([x1, y1, x2, y2].some((value) => Number.isNaN(value))) {
    return null;
  }

  return {
    x1,
    y1,
    x2,
    y2,
    page: Number.isFinite(Number(raw.page)) ? Number(raw.page) : fallbackPage,
  };
}

export function bboxToRect(
  bbox: BBox,
  dimensions: {
    displayWidth: number;
    displayHeight: number;
    naturalWidth?: number;
    naturalHeight?: number;
    bboxRelative?: boolean | null;
  },
): Rect {
  const { displayWidth, displayHeight, naturalWidth, naturalHeight, bboxRelative } = dimensions;
  const inferredRelative =
    typeof bboxRelative === "boolean"
      ? bboxRelative
      : Math.max(bbox.x1, bbox.y1, bbox.x2, bbox.y2) <= 1.5;

  if (inferredRelative) {
    return {
      left: bbox.x1 * displayWidth,
      top: bbox.y1 * displayHeight,
      width: Math.max((bbox.x2 - bbox.x1) * displayWidth, 2),
      height: Math.max((bbox.y2 - bbox.y1) * displayHeight, 2),
    };
  }

  const scaleX = naturalWidth ? displayWidth / naturalWidth : 1;
  const scaleY = naturalHeight ? displayHeight / naturalHeight : 1;

  return {
    left: bbox.x1 * scaleX,
    top: bbox.y1 * scaleY,
    width: Math.max((bbox.x2 - bbox.x1) * scaleX, 2),
    height: Math.max((bbox.y2 - bbox.y1) * scaleY, 2),
  };
}

export function rectCenter(rect: Rect): { x: number; y: number } {
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  };
}

export function computeZoomToFit(
  rect: Rect,
  viewport: Viewport,
  padding = 20,
  minZoom = 1,
  maxZoom = 3,
): number {
  const safeWidth = Math.max(rect.width + padding * 2, 1);
  const safeHeight = Math.max(rect.height + padding * 2, 1);

  const zoomX = viewport.width / safeWidth;
  const zoomY = viewport.height / safeHeight;
  const target = Math.min(zoomX, zoomY);

  return clamp(target, minZoom, maxZoom);
}
