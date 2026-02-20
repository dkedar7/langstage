# Cowork Dash Custom Theme Reference

This document describes how to create a custom CSS theme for Cowork Dash. You can point an AI agent at this document to generate a theme file.

## Quick Start

1. Create a CSS file (e.g., `my-theme.css`) that overrides the CSS variables listed below.
2. Run the app with: `cowork-dash run --custom-css my-theme.css`
3. Or set the environment variable: `DEEPAGENT_CUSTOM_CSS=my-theme.css`

## How It Works

Cowork Dash uses CSS custom properties (variables) for all colors. Your custom CSS file overrides these variables on `:root` (light mode) and `.dark` (dark mode). The file is injected after the built-in stylesheet, so your values take precedence.

## Available CSS Variables

### Color Variables

| Variable | Description | Light Default | Dark Default |
|----------|-------------|--------------|-------------|
| `--color-primary` | Primary brand color (buttons, links, active states) | `#2563eb` | `#2563eb` |
| `--color-primary-light` | Lighter primary (hover states) | `#3b82f6` | `#3b82f6` |
| `--color-primary-dark` | Darker primary (active/pressed states, gradients) | `#1d4ed8` | `#1d4ed8` |
| `--color-surface` | Main background | `#ffffff` | `#171717` |
| `--color-surface-2` | Secondary background (cards, panels) | `#f9fafb` | `#212121` |
| `--color-surface-3` | Tertiary background (hover states, code blocks) | `#f3f4f6` | `#2a2a2a` |
| `--color-border` | Borders, dividers, separators | `#e5e7eb` | `#333333` |
| `--color-text` | Primary text | `#111827` | `#ececec` |
| `--color-text-secondary` | Secondary text (labels, descriptions) | `#6b7280` | `#a0a0a0` |
| `--color-text-muted` | Muted text (placeholders, disabled) | `#9ca3af` | `#666666` |
| `--color-success` | Success indicators (green) | `#059669` | `#059669` |
| `--color-error` | Error states (red) | `#dc2626` | `#dc2626` |
| `--color-warning` | Warning indicators (orange) | `#d97706` | `#d97706` |

### Design Guidelines

- **Surface hierarchy**: `surface` < `surface-2` < `surface-3` (increasing visual weight)
- **Text hierarchy**: `text` > `text-secondary` > `text-muted` (decreasing emphasis)
- **Contrast**: Ensure `--color-text` has sufficient contrast against `--color-surface` (WCAG AA: 4.5:1 minimum)
- **Dark mode**: The `.dark` selector overrides only what changes between modes. Primary, success, error, and warning colors often stay the same.

## CSS File Format

Your CSS file should follow this structure:

```css
/* Light mode overrides */
:root {
  --color-primary: #your-color;
  --color-primary-light: #your-color;
  --color-primary-dark: #your-color;
  --color-surface: #your-color;
  --color-surface-2: #your-color;
  --color-surface-3: #your-color;
  --color-border: #your-color;
  --color-text: #your-color;
  --color-text-secondary: #your-color;
  --color-text-muted: #your-color;
  --color-success: #your-color;
  --color-error: #your-color;
  --color-warning: #your-color;
}

/* Dark mode overrides */
.dark {
  --color-surface: #your-color;
  --color-surface-2: #your-color;
  --color-surface-3: #your-color;
  --color-border: #your-color;
  --color-text: #your-color;
  --color-text-secondary: #your-color;
  --color-text-muted: #your-color;
}
```

You can override as few or as many variables as you want. Any variable not overridden keeps its default value.

You may also add additional CSS rules beyond variable overrides (e.g., custom fonts, border-radius changes, etc.). The file is standard CSS.

## Example Themes

### Ocean Blue

```css
:root {
  --color-primary: #0077b6;
  --color-primary-light: #0096c7;
  --color-primary-dark: #005f8d;
  --color-surface: #f8fbff;
  --color-surface-2: #eef5fc;
  --color-surface-3: #dceaf5;
  --color-border: #b8d4e8;
  --color-text: #0a1628;
  --color-text-secondary: #4a6580;
  --color-text-muted: #7a9ab5;
  --color-success: #0a8754;
  --color-error: #c1272d;
  --color-warning: #c47f17;
}

.dark {
  --color-surface: #0a1628;
  --color-surface-2: #122240;
  --color-surface-3: #1a3055;
  --color-border: #1e3a5f;
  --color-text: #e0eaf5;
  --color-text-secondary: #8aaec8;
  --color-text-muted: #4a6580;
}
```

### Warm Earth

```css
:root {
  --color-primary: #b45309;
  --color-primary-light: #d97706;
  --color-primary-dark: #92400e;
  --color-surface: #fdfaf6;
  --color-surface-2: #f5efe6;
  --color-surface-3: #ede4d6;
  --color-border: #d6c9b6;
  --color-text: #1c1410;
  --color-text-secondary: #6b5c4f;
  --color-text-muted: #9a8b7d;
  --color-success: #047857;
  --color-error: #b91c1c;
  --color-warning: #a16207;
}

.dark {
  --color-surface: #1c1410;
  --color-surface-2: #2a2018;
  --color-surface-3: #3a2e22;
  --color-border: #4a3c2e;
  --color-text: #f0e6d8;
  --color-text-secondary: #b5a594;
  --color-text-muted: #6b5c4f;
}
```

## Usage

### CLI

```bash
cowork-dash run --custom-css my-theme.css
```

### Environment Variable

```bash
export DEEPAGENT_CUSTOM_CSS=my-theme.css
cowork-dash run
```

### Python API

```python
from cowork_dash import CoworkApp

app = CoworkApp(agent=my_agent, custom_css="my-theme.css")
app.run()
```

## Notes

- The CSS file is read once at server startup. Changes require a server restart.
- The built-in light/dark mode toggle continues to work with custom themes.
- Paths can be absolute or relative to the working directory.
- Only standard CSS is supported (no Sass, Less, or PostCSS).
