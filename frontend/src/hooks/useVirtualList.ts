/**
 * Tiny fixed-height list virtualization (SPEC §28) — enough for queue rows,
 * log tails, and session records without pulling in a heavy dependency.
 */

import { useCallback, useMemo, useRef, useState } from "react";

export interface VirtualRange {
  startIndex: number;
  endIndex: number;
  offsetTop: number;
  totalHeight: number;
  onScroll: (event: React.UIEvent<HTMLElement>) => void;
  containerRef: React.RefObject<HTMLDivElement | null>;
}

export function useVirtualList(options: {
  itemCount: number;
  itemHeight: number;
  overscan?: number;
  viewportHeight: number;
}): VirtualRange {
  const { itemCount, itemHeight, overscan = 6, viewportHeight } = options;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);

  const onScroll = useCallback((event: React.UIEvent<HTMLElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
  }, []);

  const { startIndex, endIndex } = useMemo(() => {
    const start = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
    const visible = Math.ceil(viewportHeight / itemHeight) + overscan * 2;
    return {
      startIndex: start,
      endIndex: Math.min(itemCount, start + visible),
    };
  }, [scrollTop, itemHeight, itemCount, overscan, viewportHeight]);

  return {
    startIndex,
    endIndex,
    offsetTop: startIndex * itemHeight,
    totalHeight: itemCount * itemHeight,
    onScroll,
    containerRef,
  };
}
