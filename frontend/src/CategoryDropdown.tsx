import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Category } from "./api";
import { categoryDotColor } from "./categoryColor";
import { IconChevronDown } from "./icons";
import { inputClass } from "./ui";

type PanelPosition = { top?: number; bottom?: number; left: number; maxHeight: number };

export function CategoryDropdown({
  categories,
  value,
  onChange,
}: {
  categories: Category[];
  value: number | null;
  onChange: (categoryId: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [panelPosition, setPanelPosition] = useState<PanelPosition | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const PANEL_HEIGHT = 390; // max-h-96 (384px) + a hair of margin
  const VIEWPORT_MARGIN = 8; // gap to leave against the viewport edge

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      const target = e.target as Node;
      if (rootRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    // The panel is positioned from the button's rect at open-time; if the page
    // (or a scrollable ancestor) scrolls while open, that rect goes stale, so close.
    function handleScroll() {
      setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    window.addEventListener("scroll", handleScroll, true);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [open]);

  const selected = categories.find((c) => c.id === value) ?? null;
  const label = selected ? selected.name : value !== null ? "Unknown category" : "Uncategorized";

  function selectOption(categoryId: number | null) {
    onChange(categoryId);
    setOpen(false);
  }

  function toggleOpen() {
    if (!open && rootRef.current) {
      const rect = rootRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      const upward = spaceBelow < PANEL_HEIGHT && spaceAbove > spaceBelow;
      const available = (upward ? spaceAbove : spaceBelow) - VIEWPORT_MARGIN;
      const maxHeight = Math.max(120, Math.min(384, available));
      setPanelPosition(
        upward
          ? { bottom: window.innerHeight - rect.top + 4, left: rect.left, maxHeight }
          : { top: rect.bottom + 4, left: rect.left, maxHeight }
      );
    }
    setOpen((o) => !o);
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className={`${inputClass} bg-canvas flex items-center gap-2 min-w-[9rem]`}
        onClick={toggleOpen}
      >
        {selected && (
          <span
            className="h-2 w-2 rounded-full shrink-0"
            style={{ backgroundColor: categoryDotColor(selected.id) }}
          />
        )}
        <span className="flex-1 text-left truncate">{label}</span>
        <IconChevronDown className="text-ink-muted shrink-0" />
      </button>

      {open &&
        panelPosition &&
        createPortal(
          <div
            ref={panelRef}
            className="fixed z-50 w-72 overflow-y-auto bg-surface border border-hairline-strong rounded-lg shadow-[0_8px_24px_-8px_rgba(0,0,0,0.5)] py-1"
            style={{
              top: panelPosition.top,
              bottom: panelPosition.bottom,
              left: panelPosition.left,
              maxHeight: panelPosition.maxHeight,
            }}
          >
            <button
              type="button"
              className={`w-full text-left px-2 py-1.5 text-sm hover:bg-surface-2 transition-colors ${
                value === null ? "text-ink" : "text-ink-secondary"
              }`}
              onClick={() => selectOption(null)}
            >
              Uncategorized
            </button>
            <div className="grid grid-cols-2">
              {categories.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`min-w-0 flex items-center gap-2 text-left px-2 py-1.5 text-sm hover:bg-surface-2 transition-colors ${
                    value === c.id ? "text-ink" : "text-ink-secondary"
                  }`}
                  onClick={() => selectOption(c.id)}
                >
                  <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: categoryDotColor(c.id) }} />
                  <span className="truncate">{c.name}</span>
                </button>
              ))}
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
