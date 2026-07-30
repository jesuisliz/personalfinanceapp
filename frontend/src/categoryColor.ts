// UI wayfinding only (identity labels in the transactions table) — never use
// these as a chart data-series color. Chart series colors are categorical
// data-identity and must be run through the dataviz skill's CVD-separation
// validator; these dots are chrome, the same exempt role as the accent color.
// See docs/lld_ui_polish_icons_badges_claude.md.
const CATEGORY_DOT_COLORS = [
  "#5b8dd6",
  "#8a6fd6",
  "#4fb3a9",
  "#c77dbb",
  "#7a9e4f",
  "#c99a4a",
  "#5aa8c2",
  "#a1729b",
  "#6f9ed9",
  "#b98a5e",
];

export function categoryDotColor(categoryId: number): string {
  return CATEGORY_DOT_COLORS[categoryId % CATEGORY_DOT_COLORS.length];
}
