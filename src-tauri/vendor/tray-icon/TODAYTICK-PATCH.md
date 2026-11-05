# Local Windows fix

Vendored from tray-icon 0.24.1 (MIT OR Apache-2.0; license files retained).
Changes: set `NOTIFYICONDATAW.cbSize` for all four Windows shell API calls,
and log a failed registration's Windows error. The registry version leaves
cbSize zero. The parameter fix matches upstream commit 729eb85 in PR #337:
https://github.com/tauri-apps/tray-icon/pull/337

Remove this Cargo patch when upgrading to a released version containing that fix.
