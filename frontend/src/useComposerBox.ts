import {
  useEffect,
  useLayoutEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";

export type ComposerBoxApi = {
  boxRef: RefObject<HTMLDivElement | null>;
  taRef: RefObject<HTMLTextAreaElement | null>;
  resetSize: () => void;
  onGripPointerDown: (e: ReactPointerEvent<HTMLButtonElement>) => void;
};

const MIN = 58;
const MAX = 132;

export function useComposerBox(value: string): ComposerBoxApi {
  const boxRef: RefObject<HTMLDivElement | null> = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const manual = useRef<number | null>(null);
  const lastAuto = useRef(MIN);

  function measureNeeded(): number {
    const box = boxRef.current;
    const ta = taRef.current;
    if (!box || !ta) return MIN;
    const prev = ta.style.height;
    ta.style.height = "0px";
    const content = ta.scrollHeight;
    ta.style.height = prev;
    const css = getComputedStyle(box);
    const pad =
      (parseFloat(css.paddingTop) || 0) + (parseFloat(css.paddingBottom) || 0);
    return Math.min(Math.max(content + pad, MIN), MAX);
  }

  function apply(h: number) {
    const box = boxRef.current;
    if (!box) return;
    lastAuto.current = h;
    box.style.height = `${h}px`;
    box.classList.toggle("is-grown", h > MIN + 8);
  }

  useLayoutEffect(() => {
    if (manual.current != null) {
      apply(Math.min(Math.max(manual.current, MIN), MAX));
      return;
    }
    apply(measureNeeded());
  }, [value]);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    let primed = false;
    const ro = new ResizeObserver(() => {
      if (!primed) {
        primed = true;
        return;
      }
      const h = box.offsetHeight;
      if (Math.abs(h - lastAuto.current) <= 4) return;
      manual.current = Math.min(Math.max(h, MIN), MAX);
    });
    ro.observe(box);
    return () => ro.disconnect();
  }, []);

  function resetSize() {
    manual.current = null;
    apply(MIN);
  }

  function onGripPointerDown(e: ReactPointerEvent<HTMLButtonElement>) {
    if (e.button !== 0) return;
    const box = boxRef.current;
    if (!box) return;
    e.preventDefault();
    const grip = e.currentTarget;
    grip.setPointerCapture(e.pointerId);
    const startY = e.clientY;
    const startH = box.offsetHeight;
    const onMove = (ev: PointerEvent) => {
      const next = Math.min(MAX, Math.max(MIN, startH + (startY - ev.clientY)));
      manual.current = next;
      apply(next);
    };
    const onUp = () => {
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
  }

  return { boxRef, taRef, resetSize, onGripPointerDown };
}
