# AG Grid expert review (2026-10-22)

Source: expert panel subagent a7009253, completed 2026-10-22 21:23 UTC. Scope: pact/static/index.html, app.js, styles.css.

## Plain / unfinished points
- Event names render as raw code ids (payment_approval_requested) instead of human labels. Most visible plainness.
- Event payload (data object with PayPal order/capture ids, measured vs required, amounts) is never shown. No row click, expansion, tooltip, inspector. Audit ledger whose evidence cannot be opened reads as a log viewer.
- No Amount column. Money buried in Detail prose.
- Grid chrome minimal: one quick filter + summary line. No export, no clear filters, floating filters off, only 2 of 5 columns filterable.
- Summary strip counts events, not money held / at risk.
- Empty state is stock "No Rows To Show".
- Time column is time of day only, no date.
- Ledger card is last on page; first screen reads as a form, not a dashboard.
- Reputation is a bare number, no bar/meter/chart.
- No favicon, no meta description.

## Top 3 upgrades (all Community edition)
1. Dashboard strip over grid: KPI tiles (money held, bond at risk, checks passed rate, event count) plus one small AG Charts Community chart (reputation by agent, or ledger events by family). Load AG Charts UMD, create in init(), update from renderLedger/renderAgents. Palette ink #1d2733, accent #0b5fff, good #177245, bad #b3261e. Chart ~160-180px, inside ledger card.
2. Openable rows via full width rows (Community has no master detail): getRowId from seq, Set of expanded seq ids, interleave detail records, isFullWidthRow + fullWidthCellRenderer rendering data payload as key/value table, toggle from onCellClicked on Event column. Plus display name map for event types, raw id as tooltip.
3. Grid chrome and state: toolbar with CSV export (exportDataAsCsv, Community), Reset view (setFilterModel(null) + clear quick filter), theme toggle Quartz vs dark via setGridOption("theme"). floatingFilter true, filter true on all columns. Custom noRowsOverlayComponent with product copy. Persist column state to localStorage on move/resize/sort, restore with applyColumnState after createGrid.

## Judging window risks (Dec 1-15)
- HIGHEST: single CDN point of failure. Grid script loads synchronously in head from jsdelivr, no defer, no SRI, no local copy. If it fails, centerpiece drops to fallback. Mitigation: vendor AG Grid Community bundle + styles into /static, or script error fallback to a second source.
- Theming has no fallback: legacy ag-theme-quartz.css loads but container div lacks the ag-theme-quartz class. If themeQuartz undefined, grid renders unstyled. Put class back on container as belt and braces.
- No try/catch around createGrid. If it throws, gridApi null and no fallback element is built, ledger is an empty box. Wrap creation, build fallback table on failure.
- Fallback path weak: quick filter listener only attached in success branch, fallback shows raw timestamps, no pills, drops seq column.
- Version pin 32.3.3 is correct; do NOT upgrade casually. Later majors changed distribution/UMD path.
- renderLedger replaces all rowData each step with no getRowId, so rows reflow and scroll/sort reset. getRowId in upgrade 2 fixes most.
- Loading both legacy theme CSS and Theming API is untidy; a sponsor judge reading the repo will spot it. Remove legacy link tags once container class question is settled.
