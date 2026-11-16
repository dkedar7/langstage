/**
 * The one markdown renderer for agent text: chat bubbles, the task detail stream,
 * the welcome message and Canvas markdown items.
 *
 * GitHub-flavoured markdown plus TeX math (gh #233): `\( … \)`, `\[ … \]` and
 * `$$ … $$` render with KaTeX. KaTeX is fetched the first time a message contains
 * math; until it arrives, and if it can't be loaded, each formula shows as the exact
 * source the agent wrote.
 */
import { useEffect, useMemo, useSyncExternalStore } from "react";
import ReactMarkdown, { type Options } from "react-markdown";
import remarkGfm from "remark-gfm";
import { hasMathCandidate, prepareMath, type PreparedMath } from "../markdown/mathSyntax";
import { remarkLiteralMathDelimiters, remarkMathSegments } from "../markdown/mathPlugins";

type Plugins = NonNullable<Options["remarkPlugins"]>;
type Plugin = Plugins[number];

let rehypeMath: Plugin | null = null;
let kitState: "idle" | "loading" | "ready" | "failed" = "idle";
const listeners = new Set<() => void>();

function loadMathKit() {
  if (kitState !== "idle") return;
  kitState = "loading";
  import("../markdown/mathKit")
    .then(
      (kit) => {
        rehypeMath = kit.rehypeMath as Plugin;
        kitState = "ready";
      },
      (err) => {
        // Formulas stay as source text; the reply is still readable.
        console.warn("Math rendering unavailable:", err);
        kitState = "failed";
      },
    )
    .finally(() => listeners.forEach((notify) => notify()));
}

function subscribe(notify: () => void) {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
}

const kitReady = () => kitState === "ready";

/**
 * The plugin lists for one render. `typesetter` is `rehypeMath` once KaTeX has
 * loaded, else null. Exported for tests, which pass the typesetter in directly.
 */
export function markdownPlugins(
  prepared: PreparedMath | null,
  typesetter: Plugin | null,
): { remarkPlugins: Plugins; rehypePlugins: Plugins } {
  const remarkPlugins: Plugins = [remarkGfm, remarkLiteralMathDelimiters as Plugin];
  const rehypePlugins: Plugins = [];
  if (prepared) {
    remarkPlugins.push([remarkMathSegments, { prepared, render: !!typesetter }] as Plugin);
    if (typesetter) rehypePlugins.push([typesetter, { prepared }] as Plugin);
  }
  return { remarkPlugins, rehypePlugins };
}

interface MarkdownProps {
  children: string;
  /** The text is still streaming in: hold an unfinished formula as source text. */
  streaming?: boolean;
}

export function Markdown({ children, streaming = false }: MarkdownProps) {
  const prepared = useMemo(() => {
    if (!hasMathCandidate(children)) return null;
    const p = prepareMath(children, { streaming });
    return p.segments.length ? p : null;
  }, [children, streaming]);

  const ready = useSyncExternalStore(subscribe, kitReady, kitReady);
  const wantsMath = prepared !== null;
  useEffect(() => {
    if (wantsMath) loadMathKit();
  }, [wantsMath]);

  const { remarkPlugins, rehypePlugins } = markdownPlugins(prepared, ready ? rehypeMath : null);
  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
      {prepared ? prepared.text : children}
    </ReactMarkdown>
  );
}
