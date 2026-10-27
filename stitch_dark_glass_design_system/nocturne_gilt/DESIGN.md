---
name: Nocturne & Gilt
colors:
  surface: '#111318'
  surface-dim: '#111318'
  surface-bright: '#37393e'
  surface-container-lowest: '#0c0e12'
  surface-container-low: '#1a1c20'
  surface-container: '#1e2024'
  surface-container-high: '#282a2e'
  surface-container-highest: '#333539'
  on-surface: '#e2e2e8'
  on-surface-variant: '#d0c5af'
  inverse-surface: '#e2e2e8'
  inverse-on-surface: '#2f3035'
  outline: '#99907c'
  outline-variant: '#4d4635'
  surface-tint: '#e9c349'
  primary: '#f2ca50'
  on-primary: '#3c2f00'
  primary-container: '#d4af37'
  on-primary-container: '#554300'
  inverse-primary: '#735c00'
  secondary: '#e3c36c'
  on-secondary: '#3d2f00'
  secondary-container: '#695200'
  on-secondary-container: '#e7c76f'
  tertiary: '#f2c877'
  on-tertiary: '#402d00'
  tertiary-container: '#d5ad5e'
  on-tertiary-container: '#5a4100'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffe088'
  primary-fixed-dim: '#e9c349'
  on-primary-fixed: '#241a00'
  on-primary-fixed-variant: '#574500'
  secondary-fixed: '#ffe08c'
  secondary-fixed-dim: '#e3c36c'
  on-secondary-fixed: '#241a00'
  on-secondary-fixed-variant: '#584400'
  tertiary-fixed: '#ffdea3'
  tertiary-fixed-dim: '#eac170'
  on-tertiary-fixed: '#261900'
  on-tertiary-fixed-variant: '#5d4200'
  background: '#111318'
  on-background: '#e2e2e8'
  surface-variant: '#333539'
typography:
  display:
    fontFamily: Fraunces
    fontSize: 56px
    fontWeight: '400'
    lineHeight: 64px
    letterSpacing: -0.02em
  display-mobile:
    fontFamily: Fraunces
    fontSize: 38px
    fontWeight: '400'
    lineHeight: 44px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Fraunces
    fontSize: 40px
    fontWeight: '400'
    lineHeight: 48px
    letterSpacing: -0.015em
  headline-lg-mobile:
    fontFamily: Fraunces
    fontSize: 28px
    fontWeight: '400'
    lineHeight: 34px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Fraunces
    fontSize: 28px
    fontWeight: '500'
    lineHeight: 36px
    letterSpacing: 0em
  headline-sm:
    fontFamily: Fraunces
    fontSize: 22px
    fontWeight: '500'
    lineHeight: 30px
    letterSpacing: 0.01em
  title-lg:
    fontFamily: Outfit
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: 0.01em
  title-md:
    fontFamily: Outfit
    fontSize: 17px
    fontWeight: '500'
    lineHeight: 24px
    letterSpacing: 0.01em
  body-lg:
    fontFamily: Outfit
    fontSize: 18px
    fontWeight: '300'
    lineHeight: 28px
    letterSpacing: 0.01em
  body-md:
    fontFamily: Outfit
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0.015em
  body-sm:
    fontFamily: Outfit
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0.02em
  label-md:
    fontFamily: Outfit
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.08em
  label-sm:
    fontFamily: Outfit
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.12em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 3rem
  margin-mobile: 1.25rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.75rem
  space-xl: 3rem
---

## Brand & Style

This design system expresses an intimate, nocturnal editorial atmosphere tailored for discerning epicures and luxury hospitality seekers in Bangalore. Drawing from high-end culinary journals, private salon culture, and sensory fine-dining experiences, the identity fuses moody architectural minimalism with dark-mode glassmorphic opulence.

The aesthetic avoids gaudy excess in favor of calibrated restraint: velvet-deep charcoal backgrounds, whisper-thin golden strokes, frosted surface diffusion, and warm atmospheric luminescence. The emotional intent is anticipatory indulgence—transporting the guest from routine screen engagement into an exclusive candlelit dining room.

## Colors

The palette is anchored by the deep obsidian baseline (`#0a0c10`), providing infinite contrast for luminous amber and metallic leaf details.

- **Primary (`#d4af37`):** Vintage bullion gold; reserved for primary interactive states, key iconography, and high-impact accent badges.
- **Secondary (`#e6c66e`):** Lighter champagne gold; applied to hover states, glowing rims, and elevated typographic hierarchies.
- **Tertiary (`#8c6b23`):** Burnished antique bronze; used for secondary hairline outlines, muted micro-labels, and dimmed active fills.
- **Neutral Base (`#0a0c10`):** An ink-black with an imperceptible cool indigo undertone. Surfaces build upward in stepped opacities: `rgba(16, 20, 27, 0.7)` for surface-tier cards and `rgba(26, 32, 44, 0.45)` for floating chrome overlays.
- **Text Layers:** High-emphasis copy utilizes `#f8f6f0` (raw silk), medium-emphasis uses `#b5b0a4` (mineral beige), and disabled states rest at `#524f48`.

## Typography

The type system creates an intentional juxtaposition between classical editorial heritage and streamlined modern utility:

- **Fraunces:** Selected for headline tiers to introduce nuanced, tactile curve cuts, soft serifs, and high-fashion grace. Editorial pull quotes, restaurant titles, and chef spotlight intros are styled with lighter weights to emulate bespoke pressings.
- **Outfit:** Handles utilitarian duties across descriptions, navigation, booking controls, and metadata. Its wide geometric construction balances Fraunces' calligraphic cadence, maintaining effortless legibility against dark, tinted backdrops.
- **Case and Tracking:** Category markers, metadata counters, and section headers employ `label-sm` or `label-md` transformed to uppercase with deliberate tracking (`0.08em` to `0.12em`), reinforcing an archival catalog demeanor.

## Layout & Spacing

The layout is structured around an editorial fluid grid with strict breathing space, avoiding the high-density clutter common to generic food-delivery interfaces.

- **Grid Architecture:** Desktop displays feature a 12-column layout maxed at 1360px with generous 48px canvas margins. Tablets compress to 8 columns with 32px margins. Mobile screens resolve to a 4-column flow with 20px margins.
- **Vertical Cadence:** Generous section spacing (`space-xl` multiplied for thematic chapters) replicates coffee-table magazine pacing, encouraging deliberate contemplation of tasting menus, interior galleries, and reservation slots.
- **Rhythm:** Elements within cards adhere strictly to `space-sm` and `space-md` gaps. Asymmetrical card spans (e.g., 7 columns for venue photography paired with 5 columns for degustation notes) are favored over uniform grids.

## Elevation & Depth

Depth is articulated through tinted translucent planes, diffuse inner glows, and atmospheric backlighting rather than conventional heavy drop shadows.

- **Frosted Surfaces:** Floating panels feature backdrop blurs (`backdrop-filter: blur(16px)`) applied over dark glass fills (`rgba(16, 20, 27, 0.72)`).
- **Hairline Luminosity:** Panels employ a 1px border perimeter with directional opacity gradients: pure gilded highlights (`rgba(212, 175, 55, 0.35)`) along top-left edges tapering to dark bronze (`rgba(140, 107, 35, 0.08)`) at bottom-right edges.
- **Warm Ambient Radiance:** Elevated elements, active modals, and reservation cards project a diffuse, warm amber underglow: `0 20px 50px -12px rgba(212, 175, 55, 0.12)`. When elements hover, this glow intensifies to a soft champagne aura (`rgba(230, 198, 110, 0.2)`).
- **Surface Layering:**
  - *Base Canvas:* `#0a0c10` with optional radial gradients simulating distant dim amber spotlights.
  - *Tier 1 (Cards, Lists):* `rgba(18, 22, 30, 0.65)` with 1px border `rgba(212, 175, 55, 0.15)`.
  - *Tier 2 (Modals, Sticky Nav):* `rgba(10, 12, 16, 0.85)` with blur `24px` and border `rgba(230, 198, 110, 0.25)`.

## Shapes

The design system employs refined, subtle curvature (`roundedness: 1`). 

- Standard inputs, chips, and small cards utilize `0.25rem` (4px) radii, giving interactive edges crisp definition reminiscent of high-grade cardstock and brass menu clips.
- Larger discovery tiles, modal sheets, and hero frames use `0.5rem` (8px). 
- Fully circular shapes (`9999px`) are reserved exclusively for compact status indicators, sommelier badges, and audio-tour play triggers. Sweeping pill buttons are explicitly prohibited to prevent casual consumer tropes.

## Components

### Buttons
- **Primary:** Filled in solid vintage gold (`#d4af37`) with ink-black text (`#0a0c10`) rendered in `Outfit SemiBold`. Renders a soft champagne ambient glow on hover (`box-shadow: 0 0 20px rgba(212, 175, 55, 0.35)`).
- **Secondary (Ghost Outline):** Frosted dark glass fill (`rgba(212, 175, 55, 0.04)`) enclosed by a 1px gold hairline (`rgba(212, 175, 55, 0.4)`). Text in `#e6c66e`. Hover transitions background to `rgba(212, 175, 55, 0.12)`.
- **Editorial Text Action:** Pure Fraunces italic or Outfit uppercase label with a persistent 1px golden underline offset by 4px.

### Cards & Discovery Tiles
- Constructed from Tier 1 frosted glass with delicate interior padding (`space-lg`).
- Images feature rich, moody grading; hovering triggers a subtle 1.03x scale alongside an intensification of the top golden hairline border.
- Neighborhood tag (e.g., "Indiranagar", "Lavelle Road") floats over image corners in a micro-frosted pill container.

### Chips & Filter Pills
- Sharp, understated rectangles with `4px` corner radius.
- Inactive state: `rgba(255, 255, 255, 0.04)` fill with `#b5b0a4` typography.
- Active state: Charcoal fill with `1px solid #d4af37`, glowing inset shadow, and `#e6c66e` text.

### Form Inputs & Date Selectors
- Flat dark surface (`rgba(16, 20, 27, 0.9)`) inset with 1px border (`rgba(255, 255, 255, 0.1)`).
- Focus state switches border to `#d4af37` accompanied by a 2px diffuse outer blur in `#d4af3726`.
- Labels sit above inputs styled in `label-sm` with gold-tinted capitalization.

### Checkboxes & Radios
- Square (checkbox) or diamond-oriented square (radio) with a 1px hairline border.
- Checked state fills with `#d4af37` accompanied by a micro dark notch, surrounded by an ambient golden ring.

### Lists & Degustation Menus
- Borderless rows separated exclusively by 1px rules tinted with `#8c6b23` at 20% opacity.
- Item titles in `Fraunces Medium` paired with dot leaders connecting smoothly to prices in `Outfit Medium`.

### Hospitality-Specific Components
- **Tasting Note Badge:** Minimalist frosted swatch highlighting terroir, flavor profiles, and culinary lineage.
- **Reservation Seat Grid:** Stylized architectural table map rendered in fine gold strokes with real-time glow states denoting banquet, terrace, and chef’s counter seating.