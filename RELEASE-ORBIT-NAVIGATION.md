# Cosmic background and orbit navigation

- Replaced the island popup with a real landing page for each orbit. A persistent section switcher and breadcrumbs remain available inside every section. Sibling tab changes replace the section history entry, so browser Back returns directly to the island directory.
- Corrected assistant launcher positioning after the glass-button CSS rule, increased habit action buttons to at least 44 px, and styled quantity/note controls. Selected calendar days open a wider editable dialog. Quantity and note updates continue to use the existing private API.
- Added one bounded cosmic canvas across all routes: stars, restrained dust, constellation fragments, scroll parallax and two comet styles. Homepage density and comet frequency are higher. The animation stops in hidden tabs and honours reduced-motion settings.
- Preserved labels above transformed island artwork, added an orbit satellite, route previews, return-camera animation and glass highlights.
- Added safe search highlighting, per-account recent sections, contextual mobile actions, keyboard-accessible assistant panel resizing, task editing actions, completion outlines and record reflow.
- Habit cards show numeric progress. Goals highlight their next incomplete step and collapse completed blocks without losing their items.

No schema changes or new external services are required. Deploy the full commit. Automated browser-math tests use fake data; local browser checks cover directory navigation, Back behaviour, habit progress, assistant resizing and narrow layouts.
