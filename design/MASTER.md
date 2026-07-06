# AzimeAI — Design System Master

> Global Source of Truth. All pages inherit from this document.

## Brand Identity

**Name:** AzimeAI  
**Tagline:** Invoice Processor  
**Register:** Product (tool)  
**Reference:** Claude.ai (Anthropic) — dark, minimal, chat-first  

## Color Strategy: Restrained Monochrome

Dark-first. Black + white + neutral grays. Zero decorative color.
Semantic colors only for state feedback (success/error/warning).

### Tokens (OKLCH approximations)

| Token | Hex | Role |
|-------|-----|------|
| `--bg-primary` | `#0a0a0a` | App background |
| `--bg-secondary` | `#111111` | Sidebar / panels |
| `--bg-tertiary` | `#181818` | Inputs, cards, messages |
| `--bg-surface` | `#1e1e1e` | Popovers, dropdowns |
| `--bg-hover` | `#242424` | Hover state |
| `--border-primary` | `#2a2a2a` | Subtle borders |
| `--border-secondary` | `#333333` | Input borders |
| `--border-focus` | `#555555` | Focus ring |
| `--text-primary` | `#ededed` | Body text |
| `--text-secondary` | `#a8a8a8` | Labels, secondary |
| `--text-tertiary` | `#6b6b6b` | Captions, hints |
| `--success` | `#4ade80` | Success state |
| `--error` | `#f87171` | Error state |
| `--warning` | `#facc15` | Warning state |

### Contrast Verification
- Body text `#ededed` on `#0a0a0a`: **17.4:1** (AAA)
- Secondary `#a8a8a8` on `#0a0a0a`: **8.9:1** (AAA)
- Tertiary `#6b6b6b` on `#0a0a0a`: **3.2:1** (AA Large)

## Typography

**Family:** Inter (Google Fonts)  
**Weights:** 400 (body), 500 (labels), 600 (headings)  
**Scale:**
| Level | Size | Weight | Use |
|-------|------|--------|-----|
| Heading | 1.375rem | 500 | Welcome title |
| Body | 0.875rem | 400 | Messages, content |
| Label | 0.65rem | 500 | Message role labels |
| Caption | 0.75rem | 400 | Hints, metadata |
| Button | 0.85rem | 500 | All buttons |

**Letter-spacing:** -0.01em on headings, 0.06em uppercase on labels  
**Line-height:** 1.6 body, 1.5 headings

## Layout

- **Max width:** 720px (centered, single column)
- **Padding:** 1.5rem sides, 0.75rem header
- **Spacing rhythm:** 8px base (0.5rem), 4/8/12/16/24/32 scale
- **Border radius:** 6px (small), 10px (medium), 16px (large), 22px (xl)
- **Z-index scale:** dropdown (100), popover (200), dialog (300), toast (400)

## Components

### Chat Messages
- User: right-aligned, bg-tertiary, border-primary, left margin 2rem
- Assistant: left-aligned, transparent bg, left border 2px secondary
- System: centered, pill shape (radius 100px), max-width 320px
- Error: red tint (rgba 0.06), red border (rgba 0.15)
- Success: green tint, green border

### Buttons
- Default: bg-tertiary, border-secondary, text-primary
- Primary: bg text-primary (white), text bg-primary (black) — inverted
- Hover: bg-hover + border-focus
- Transition: 200ms cubic-bezier(0.16, 1, 0.3, 1)

### File Uploader (Welcome)
- bg-tertiary, dashed border-secondary
- Padding: 2rem 1.5rem
- Hover: border-focus, bg-hover
- Pulse animation on idle

### Inputs
- bg-tertiary, border-secondary, radius-md
- Focus: border-focus + 1px shadow ring
- Placeholder: text-tertiary

### Dataframe
- bg-tertiary, border-primary
- Header: bg-secondary, text-secondary, 0.7rem
- Body: 0.75rem
- Row hover: bg-hover

## Motion

### Durations
- Micro-interactions: 200ms
- Message reveal: 400ms
- Loading spinner: 700ms (loop)

### Easing
- Primary: `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo)
- Linear: spinner rotation only

### Animations
| Name | Property | Duration | Use |
|------|----------|----------|-----|
| `msgReveal` | opacity + translateY | 400ms | New messages fade in |
| `azimeSpin` | rotate | 700ms loop | Loading spinner |
| `azimeDotPulse` | opacity | 1200ms loop | Loading dots |
| `azimePulse` | box-shadow | 2s loop | Upload area glow |
| `cursorBlink` | opacity | 800ms loop | Streaming cursor |

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
    * { animation-duration: 0.01ms !important; }
}
```

## Icons

**Library:** Inline SVG (Lucide-style, stroke 1.5px)  
**Size:** 16-18px for UI controls, 32px for decorative  
**Color:** `currentColor` (inherits text color)

Icons used:
- Gear (settings)
- Upload (file input)
- Play (process button)
- Check (confirm, success)
- Download (export)
- Skip (skip action)
- Spinner (loading)
- Dots (typing indicator)

## Logo

SVG geometric monogram: rounded square outline + filled triangle ("A" shape) + inner cutout.  
File: `design/logo.svg`  
Display sizes: 32px (header wordmark), 48px (welcome screen)

## Anti-Patterns (Avoid)

- No emojis as structural icons
- No gradient text
- No glassmorphism
- No side-stripe borders
- No card grids
- No decorative grid backgrounds
- No cream/sand/beige backgrounds
- No `border-radius` > 16px on cards
- No `box-shadow` > 8px blur paired with border

## Page Architecture

### Welcome (app_stage = init)
```
┌─────────────────────────────────┐
│         [Logo 48px]             │
│                                 │
│  Olá! Insira a Invoice do       │
│  fornecedor para iniciar...     │
│                                 │
│  [Upload area - dashed border]  │
│  Formatos: .xlsx, .csv          │
│                                 │
└─────────────────────────────────┘
```

### Chat (app_stage = config/ready/processing/done)
```
┌─────────────────────────────────┐
│ [Logo wordmark]        [⚙]     │
│─────────────────────────────────│
│                                 │
│  AZIME                          │
│  Recebi o arquivo X...          │
│                                 │
│              VOCÊ               │
│              Enviei arquivo X   │
│                                 │
│  AZIME                          │
│  Qual a marca e fornecedor?     │
│                                 │
│  [Marca ▾]  [Código ERP]       │
│  [Continuar]  [Pular]          │
│                                 │
└─────────────────────────────────┘
```
