/** Where to put a popover of up to `maxWidth` px for an anchor at `anchor` (viewport coordinates), so it stays inside
 * a viewport `viewportWidth` wide with an 8px margin: centred on the anchor when there's room, shifted inward at the
 * edges, above the anchor unless there's too little room (then below). */
export function popoverPosition(anchor: { left: number; top: number; width: number; bottom: number },
                                viewportWidth: number, maxWidth = 256) {
  const margin = 8;
  const width = Math.min(maxWidth, viewportWidth - 2 * margin);
  const centred = anchor.left + anchor.width / 2 - width / 2;
  const left = Math.min(Math.max(margin, centred), viewportWidth - width - margin);
  const above = anchor.top > 140;
  return { left, width, top: above ? anchor.top - margin : anchor.bottom + margin, above };
}
