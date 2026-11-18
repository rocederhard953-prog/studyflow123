# Black cosmos and persistent Telegram menu

## Website

- Three large islands: Study, Habits and Settings. Retained sections have direct `/orbit/<group>/<section>` addresses. Browser Back/Forward restores the previous orbit, including mouse navigation buttons. Deep links return the application shell.
- One black and white theme, glass buttons, slow island approach with synthesized sound, reduced-motion modes, optional snow, hover previews and an introductory tour. Sound and snow have explicit appearance controls. Navigation works without animation or audio support.
- Homepage search, per-account Continue shortcut, reversible delayed deletion, quick add and personal day plans with three priorities, estimated minutes and pointer reordering.
- Flexible weekly habits, numeric daily targets, individual notes, calendars, charts and heatmaps. Habit configuration and progress are stored on the server; no database schema migration is required.
- Goals support named blocks and checklist steps, an editable 27-task template, derived progress, charts and constellations. Revision checks reject stale edits. Existing numeric goals and records remain available.
- Personal and homework boards support flat and wireframe volume figures, whole-object erasing, viewport navigation, two-finger pan/zoom and fullscreen. Homework boards offer a condition/board/assistant workspace; mobile uses three tabs. Images are sent to AI only with the explicit checkbox. Existing provider configuration and limits still apply.
- Hidden old sections are removed from user navigation and AI navigation suggestions. Their records are retained.

## Telegram

The interactive menu uses `editMessageText`, `editMessageCaption` and multipart `editMessageMedia`. Its message ID, media type and current content persist per linked account, so bot restarts do not require sending a new menu. Long content and task photos page inside the same message. An unchanged edit and temporary failures do not send replacements. A replacement is created only when Telegram confirms the previous message is unavailable or cannot be edited. Scheduled reminders and broadcasts remain separate notifications.

Weekly reports are opt-in from Analytics. They use the account timezone and honour global notification and quiet-hour settings. Completed-task history starts with this release; earlier completion dates are not invented.

## Deployment

Deploy the full commit and restart both the web process and Telegram bot process. Keep the existing persistent DATA_DIR and database. No new API key is needed for navigation, figures, sound or goal features. AI still needs its configured provider key.

Automated checks use isolated databases and mocked Telegram calls. Local browser checks cover desktop and narrow layouts, goal progress, day plans, deep links and Back navigation. A real Telegram client and actual touch hardware still require an after-deployment check.

Selected finishing details include snow, volume wireframes, animated progress, activity heatmaps, first-use tour, glass controls, cursor response and route previews. Board paper remains suitable for the existing black/red/green ink tools. No real user data or Telegram messages are used during checks.

The carousel now uses five generated minimalist black cosmic backgrounds with live white text and scene-specific lightweight animation. The three previous illustrations are removed. Russian count labels share a tested pluralization helper, including 1/2/5 and 11/21 cases.

