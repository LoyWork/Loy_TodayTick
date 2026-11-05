# Glass UI design decision

- Surface: compact, non-resizable Windows reminder utility; write a reminder and its time.
- Hierarchy: reminder content → time → Add; pending reminders below, startup toggle last.
- Content: actual reminders only. Test fixtures stay in `.testenv/`.
- Composition (native 384 px, also checked at 320/390):
  ```
  TodayTick                  clock ×
  [ reminder text                 ]
  [ time                    + Add ]
  [ parse feedback, only if typed ]
  Pending                         n
  time    reminder                ×
  startup                 Enter hint
  ```
- System: one charcoal acrylic surface, fine light border, 16/13/12/11 px type, 4 px spacing rhythm, 16 px window / 11 px input / 7 px control radii; one stroke icon grammar.
- Signature: the desktop itself diffuses through native DWM acrylic. No painted wallpaper, glow, or decorative dashboard content.
- Cliche budget: glass only, as explicitly requested.
- Risks: compounded opacity hiding the glass; text losing contrast on a light desktop. Inspect native windows as well as CDP screenshots. Long reminders truncate with full text tooltips; long popup text scrolls without hiding actions.
- Wide/browser viewport checks apply only to layout resilience; the shipped app remains 384 px and the popup 320 px, independent of monitor size.
