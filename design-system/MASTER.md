Design system: FormulaSnip User UI

- Query: Windows desktop formula OCR settings minimal sidebar tutorial stepper blue gray
- Matched profile: saas
- Style direction: minimal-modern
- Palette: graphite + signal blue + cyan status accents
- Typography: Inter + Space Grotesk
- Effects: crisp borders and restrained elevation
- Landing/layout bias: hero + product proof
- Avoid: low-contrast cards, gradients, glass effects, and persistent explanatory copy
- Notes: Optimize for task-first scanability and local state feedback.

## Desktop UI rules

- Use a single-line page header; actions stay in the same 64–68 px header row.
- Keep persistent helper text to the minimum needed to complete the current task.
- Show progress, validation, errors, and changed/custom states locally when they occur.
- Settings body text starts at 15 px; muted supporting text never drops below 13 px.
  Version labels and compact code/value chips may use 12 px.
- Build spacing from an 8 px / 12 px rhythm. Cards use crisp borders and moderate
  8–10 px corner radii.
- Preserve high contrast in light and dark themes and an explicit keyboard focus ring.
- Do not use gradients or glassmorphism.
- Signal blue is the default UI accent. Violet, cyan, and teal are user-selectable
  alternatives for primary actions, selection, and keyboard focus.
- The floating-orb ring is configured separately from the global UI accent.
  Cyan/teal status colors remain semantic and do not change with the chosen accent.
- Keep light mode cool and nearly neutral; dark mode uses true graphite rather
  than blue-gray surfaces.
