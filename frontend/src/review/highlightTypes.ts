export type BBox = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  page?: number;
};

export type HighlightStatus = "ok" | "invalid" | "error";

export type Highlight = {
  id: string;
  fieldKey: string;
  bbox: BBox;
  status: HighlightStatus;
  message?: string;
  createdAt: number;
};

export type Rect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

export type Viewport = {
  width: number;
  height: number;
};
