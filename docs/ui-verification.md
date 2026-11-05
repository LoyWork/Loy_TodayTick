# UI verification — 2026-11-05

- JavaScript syntax checks passed; time parser: 35 assertions passed.
- Browser CDP: widths 320, 384, 390, 768, 1440, 1920 and 2560 checked for overflow and control containment. These are resilience checks; the native utility is non-resizable at 384 px, popup 320 px.
- Inspected native-size screenshots: empty, populated, invalid time, close confirmation, many reminders, and long popup content. Scroll areas retain the action buttons.
- Real Windows WebView2: main interaction checks passed (add, invalid time, Chinese dates, quick time, delete, bulk list, clear); native layout passed for main and popup. Main shell matched 384×431 with three sample reminders, 44 px rows; popup 320×202.
- Popup queue: all seven checks passed on a fresh seeded run, including earliest reminder, overdue label, snooze, next item, acknowledge and queue empty. An earlier run failed its first-item check; the fresh repeat passed, so external interaction during testing remains a possible explanation rather than a confirmed diagnosis.
- Keyboard: visible focus, modal initial focus/trap/cancel, IME Enter protection; reduced-motion styling inspected. Browser console: no uncaught exceptions in the layout harness.
- Native screenshot capture initially failed with a desktop-composition error, then succeeded on retry. Acrylic was inspected in the active desktop session; backgrounds and machines may render it differently.
- Weakest remaining dimension: glass/text contrast across arbitrary wallpapers, remote sessions and disabled DWM. Those environments require a visual check on the target machine; opaque CSS layering was reduced and native acrylic retained.
- Startup registry writes were not validated in this UI task; existing startup implementation is unchanged.

Screenshots use sample reminders; production `dist/reminders.json` is preserved.

Release build passed and its SHA-256 matches dist/TodayTick.exe. The final release window was launched without a debugging port and visually checked; production reminder data was preserved byte-for-byte during binary replacement.

Final native review caught a system caption reappearing after window initialization. Frameless styling is now reapplied after acrylic, resize, and restore operations. The final rebuilt release was copied successfully, its hash rechecked, and a new native screenshot confirmed the caption is absent.

## Minimal composer and tray follow-up

- Removed the shortcut row and duplicate default time-format hint. Add now sits beside the time field. Parsed time / error only appears after typing; clearing restores the original height.
- Browser layout/feedback checks passed at 320, 384 and 390 px. Updated real WebView2 main checks passed.
- Strengthened hidecheck: now asserts document.visibilityState is hidden rather than merely that the click handler ran. This exposed the previous test's false positive: actual tray registration is failing.
- Current tray-icon 0.24.1 has no cbSize on four NOTIFYICONDATAW calls. Applied the upstream parameter initialization in a local licensed Cargo patch, with a registration-error diagnostic.
- On this automated launch path, registration still reports Windows error 5 (Access denied), and rect() is None. Do not claim successful tray integration from these runs. New hide guard keeps the window visible and reports the error instead of losing access to it.
- ShellExecute launch from the desktop automation helper also returned access denied. Manual launch in the user's desktop session is pending to distinguish an environment restriction from a remaining application issue.
- Production reminder data retained, including the existing scheduled reminder. No system tray preferences or Windows security settings were changed.

## Confirmed cause and deployment acceptance

- File ACL inspection showed the workspace and executable inherit a Low mandatory integrity label. Microsoft documents that executable integrity limits the spawned process, including manual launches. This accounts for the shell access restriction.
- User explicitly approved deployment to C:\Users\EDY\AppData\Local\Programs\TodayTick with existing reminders.
- Created the executable as a new file in that ordinary application directory; did not change the workspace ACL or integrity labels. Installed and release binary SHA-256 match.
- Desktop ShellExecute launch succeeded from the application directory. Windows NotifyIconSettings now contains that exact executable and TodayTick tooltip; no record existed for workspace builds.
- Actual UI acceptance: clicked close, then Hide to tray; the window disappeared from the desktop inventory (the new guard requires a valid native tray rectangle). Launching the installed executable again restored the same window ID, proving the single-instance restore path. Actual tray icon click is not independently automated; the registry and hide guard confirm registration.
- Existing scheduled reminder remains in the deployed data. No startup registry preference, notification-area promotion, or system security setting was modified.
- Portable ZIP excludes reminder data. Extract outside the Low-labeled development directory before running. README main screenshot now reflects the simplified empty composer from browser QA.

## Release pipeline and direct-close behavior

- User chose GitHub Releases for official distribution; README now describes Actions and downloaded release artifacts rather than local installation.
- Added Windows Release workflow: manual tag input or v* tag push, version/commit validation, locked x64 build, frontend parser checks, native self-test, executable/ZIP/SHA-256 assets, and GitHub Release creation. Existing Releases are not overwritten.
- Aligned Cargo.toml, Cargo.lock and tauri.conf.json at 2.1.0.
- Removed close dialog HTML, styles and JavaScript. X directly calls hide_main; native CloseRequested (including Alt+F4) prevents destruction and uses the same guarded hide path. Exit remains in the tray context menu.
- Direct-close browser check passed: one hide request, no dialog, and failed tray operation remains visible as feedback with no JS exception. Native CloseRequested compiled successfully; its OS-level behavior awaits release acceptance.
- Validation passed: actionlint 1.7.12, PowerShell syntax AST, actual ZIP content (only TodayTick.exe), checksums, JavaScript syntax, 35 parser assertions, and cargo check --offline --locked. The initial restricted build-script launch failed DLL initialization; normal-context cargo check passed.
- No GitHub remote is configured in this checkout. Workflow has not run on GitHub and no Release has been published. No additional local deployment was performed for these latest edits; they take effect in the next built release.

## Reminder placement

- User requested reminder cards at the bottom right. Replaced centered placement with the main window monitor's actual work area, keeping a 16 logical-pixel inset above/right of the taskbar and accounting for monitor origin and scaling.
- Existing popup resize/queue refresh paths reapply this position, so taller reminders remain anchored at the bottom.
- Updated native smoke expectation from center/top to the work-area bottom/right. OS-level multi-monitor/scale acceptance remains for the next release; source compilation is checked locally.
