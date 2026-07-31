import { useEffect, useRef, useState } from "react";
import type { Category } from "./api";
import { categoryDotColor } from "./categoryColor";
import { IconChevronDown } from "./icons";
import { inputClass } from "./ui";

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
  const [openUpward, setOpenUpward] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const PANEL_HEIGHT = 390; // max-h-96 (384px) + a hair of margin

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
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
      setOpenUpward(spaceBelow < PANEL_HEIGHT && spaceAbove > spaceBelow);
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

      {open && (
        <div
          className={`absolute z-10 w-72 max-h-96 overflow-y-auto bg-surface border border-hairline-strong rounded-lg shadow-[0_8px_24px_-8px_rgba(0,0,0,0.5)] py-1 ${
            openUpward ? "bottom-full mb-1" : "mt-1"
          }`}
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
        </div>
      )}
    </div>
  );
}
