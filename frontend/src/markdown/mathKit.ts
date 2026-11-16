/**
 * The heavy half of math rendering: KaTeX, its stylesheet and its fonts (gh #233).
 * Imported only through `import()` in `Markdown.tsx`, so it is its own chunk and a
 * session with no math never downloads it. Everything is bundled: no CDN.
 */
import "katex/dist/katex.min.css";

export { rehypeMath } from "./mathRender";
