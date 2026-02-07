import { useState, useEffect, useCallback } from "react";
import { Sun, Moon, Monitor } from "lucide-react";

type Theme = "light" | "dark" | "auto";

interface ThemeToggleProps {
  initialTheme?: Theme;
}

export function ThemeToggle({ initialTheme = "auto" }: ThemeToggleProps) {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  const applyTheme = useCallback((t: Theme) => {
    const isDark =
      t === "dark" ||
      (t === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", isDark);
  }, []);

  useEffect(() => {
    applyTheme(theme);

    if (theme === "auto") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const handler = () => applyTheme("auto");
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }
  }, [theme, applyTheme]);

  const cycle = () => {
    setTheme((prev) => {
      const next: Theme =
        prev === "light" ? "dark" : prev === "dark" ? "auto" : "light";
      return next;
    });
  };

  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;

  return (
    <button
      onClick={cycle}
      className="p-1.5 rounded-md hover:bg-[var(--color-surface-3)] transition-colors"
      title={`Theme: ${theme}`}
    >
      <Icon size={16} className="text-[var(--color-text-secondary)]" />
    </button>
  );
}
