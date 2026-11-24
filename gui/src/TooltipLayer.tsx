import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const hoverDelay = 350;
const viewportGutter = 8;
const anchorGap = 5;

function triggerAt(target: EventTarget | null) {
  return target instanceof Element ? target.closest<HTMLElement>("[data-tooltip]") : null;
}

function canShow(anchor: HTMLElement) {
  return anchor.isConnected && Boolean(anchor.dataset.tooltip)
    && (!anchor.hasAttribute("data-tooltip-overflow")
      || Array.from(anchor.children).some((label) => label.scrollWidth > label.clientWidth));
}

export function TooltipLayer() {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const bubble = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current: HTMLElement | null = null;
    let timer: number | undefined;

    function hide() {
      window.clearTimeout(timer);
      current = null;
      setAnchor(null);
    }

    function show(next: HTMLElement | null, delay: number) {
      hide();
      if (!next || !canShow(next)) return;
      current = next;
      if (delay === 0) setAnchor(next);
      else timer = window.setTimeout(() => { if (canShow(next)) setAnchor(next); }, delay);
    }

    function enter(event: PointerEvent) {
      if (event.pointerType === "touch") return;
      const next = triggerAt(event.target);
      if (next !== current) show(next, hoverDelay);
    }

    function leave(event: PointerEvent) {
      if (current && triggerAt(event.target) === current && triggerAt(event.relatedTarget) !== current) hide();
    }

    function focus(event: FocusEvent) {
      const next = triggerAt(event.target);
      if (next?.matches(":focus-visible")) show(next, 0);
    }

    function blur(event: FocusEvent) {
      if (current && triggerAt(event.target) === current) hide();
    }

    function key(event: KeyboardEvent) {
      if (event.key === "Escape") hide();
    }

    const scope = new AbortController();
    const options = { capture: true, signal: scope.signal };
    document.addEventListener("pointerover", enter, options);
    document.addEventListener("pointerout", leave, options);
    document.addEventListener("focusin", focus, options);
    document.addEventListener("focusout", blur, options);
    document.addEventListener("keydown", key, options);
    document.addEventListener("pointerdown", hide, options);
    document.addEventListener("contextmenu", hide, options);
    document.addEventListener("close", hide, options);
    window.addEventListener("scroll", hide, options);
    window.addEventListener("resize", hide, options);
    window.addEventListener("blur", hide, { signal: scope.signal });
    return () => {
      scope.abort();
      window.clearTimeout(timer);
    };
  }, []);

  useLayoutEffect(() => {
    if (!anchor || !bubble.current) return;
    const target = anchor.getBoundingClientRect();
    const { offsetWidth, offsetHeight, style } = bubble.current;
    const left = target.left + (target.width - offsetWidth) / 2;
    const above = target.top - offsetHeight - anchorGap;
    const top = above >= viewportGutter ? above : target.bottom + anchorGap;
    style.left = `${Math.max(viewportGutter, Math.min(left, window.innerWidth - offsetWidth - viewportGutter))}px`;
    style.top = `${Math.max(viewportGutter, Math.min(top, window.innerHeight - offsetHeight - viewportGutter))}px`;
  }, [anchor]);

  if (!anchor || !canShow(anchor)) return null;
  return createPortal(<div ref={bubble} className="app-tooltip" aria-hidden="true">
    {anchor.dataset.tooltip}
    {anchor.dataset.tooltipDetail ? <small>{anchor.dataset.tooltipDetail}</small> : null}
  </div>, anchor.closest("dialog[open]") ?? document.body);
}
