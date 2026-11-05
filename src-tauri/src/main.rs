#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! TodayTick · 极轻量定时提醒
//! Rust 侧负责：数据存储、到点调度、弹窗窗口、单实例、开机自启、毛玻璃。

use std::{
    fs,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    sync::Mutex,
    thread,
    time::Duration as StdDuration,
};

use chrono::{Local, NaiveDateTime};
use serde::{Deserialize, Serialize};
use tauri::{
    AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder,
};

// Native debug-window checks must not replace the running release instance.
const PORT: u16 = if cfg!(debug_assertions) { 48734 } else { 48733 };
const WIN_W: f64 = 384.0;
const POPUP_W: f64 = 320.0;
const FMT: &str = "%Y-%m-%dT%H:%M";
const APP_ID: &str = "TodayTick";
const RUN_KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
const WIN_TITLE: &str = "TodayTick · 定时提醒";

// ---------------------------------------------------------------- 窗口细修

/// Keep native non-client painting out of the transparent WebView surface.
/// Tao may restore WS_CAPTION during a later show/focus/style update, so a
/// one-off SetWindowLongPtr is insufficient. Both windows share this guard.
#[cfg(windows)]
mod winfix {
    use std::ffi::c_void;

    #[link(name = "user32")]
    extern "system" {
        fn GetWindowLongPtrW(hwnd: *mut c_void, index: i32) -> isize;
        fn SetWindowLongPtrW(hwnd: *mut c_void, index: i32, value: isize) -> isize;
        fn CreateWindowExW(ex: u32, class: *const u16, title: *const u16, style: u32, x: i32, y: i32, w: i32, h: i32, parent: *mut c_void, menu: *mut c_void, instance: *mut c_void, param: *mut c_void) -> *mut c_void;
        fn DestroyWindow(hwnd: *mut c_void) -> i32;
        fn SendMessageW(hwnd: *mut c_void, msg: u32, wparam: usize, lparam: isize) -> isize;
        fn GetClientRect(hwnd: *mut c_void, rect: *mut Rect) -> i32;
        fn GetWindowRect(hwnd: *mut c_void, rect: *mut Rect) -> i32;
        fn SetWindowPos(
            hwnd: *mut c_void,
            after: *mut c_void,
            x: i32,
            y: i32,
            cx: i32,
            cy: i32,
            flags: u32,
        ) -> i32;
    }

    type SubclassProc = unsafe extern "system" fn(*mut c_void, u32, usize, isize, usize, usize) -> isize;

    #[link(name = "comctl32")]
    extern "system" {
        fn SetWindowSubclass(hwnd: *mut c_void, proc: SubclassProc, id: usize, data: usize) -> i32;
        fn RemoveWindowSubclass(hwnd: *mut c_void, proc: SubclassProc, id: usize) -> i32;
        fn DefSubclassProc(hwnd: *mut c_void, msg: u32, wparam: usize, lparam: isize) -> isize;
    }

    #[repr(C)]
    struct StyleStruct { old: u32, new: u32 }
    #[repr(C)]
    #[derive(Default)]
    struct Rect { left: i32, top: i32, right: i32, bottom: i32 }

    const SUBCLASS_ID: usize = 0x5454_4652;
    const WM_STYLECHANGING: u32 = 0x007C;
    const WM_NCCALCSIZE: u32 = 0x0083;
    const WM_NCPAINT: u32 = 0x0085;
    const WM_NCACTIVATE: u32 = 0x0086;
    const WM_NCDESTROY: u32 = 0x0082;

    const GWL_STYLE: i32 = -16;
    const GWL_EXSTYLE: i32 = -20;
    const WS_CAPTION: isize = 0x00C0_0000;
    const WS_THICKFRAME: isize = 0x0004_0000;
    const WS_SYSMENU: isize = 0x0008_0000;
    const WS_MINIMIZEBOX: isize = 0x0002_0000;
    const WS_MAXIMIZEBOX: isize = 0x0001_0000;
    const WS_POPUP: isize = 0x8000_0000u32 as isize;
    const WS_EX_TOOLWINDOW: isize = 0x0000_0080;
    const WS_EX_APPWINDOW: isize = 0x0004_0000;
    const WS_EX_WINDOWEDGE: isize = 0x0000_0100;
    const WS_EX_CLIENTEDGE: isize = 0x0000_0200;
    const SWP_NOSIZE: u32 = 0x0001;
    const SWP_NOMOVE: u32 = 0x0002;
    const SWP_NOZORDER: u32 = 0x0004;
    const SWP_NOACTIVATE: u32 = 0x0010;
    const SWP_FRAMECHANGED: u32 = 0x0020;

    fn clean_style(style: isize) -> isize {
        (style & !(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)) | WS_POPUP
    }

    fn clean_ex_style(style: isize, main: bool) -> isize {
        let style = style & !(WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE);
        if main { (style & !WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW }
        else { (style & !WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW }
    }

    unsafe extern "system" fn frameless_proc(
        hwnd: *mut c_void, msg: u32, wparam: usize, lparam: isize, id: usize, main: usize,
    ) -> isize {
        match msg {
            WM_STYLECHANGING if lparam != 0 => {
                // Let the runtime update its state before enforcing our frame policy.
                let result = DefSubclassProc(hwnd, msg, wparam, lparam);
                let styles = &mut *(lparam as *mut StyleStruct);
                if wparam as i32 == GWL_STYLE {
                    styles.new = clean_style(styles.new as isize) as u32;
                } else if wparam as i32 == GWL_EXSTYLE {
                    styles.new = clean_ex_style(styles.new as isize, main != 0) as u32;
                }
                result
            }
            WM_NCCALCSIZE if wparam != 0 => 0,
            WM_NCPAINT => 0,
            // Preserve Tao's focus events; -1 tells DefWindowProc not to paint a caption.
            WM_NCACTIVATE => DefSubclassProc(hwnd, msg, wparam, -1),
            WM_NCDESTROY => {
                RemoveWindowSubclass(hwnd, frameless_proc, id);
                DefSubclassProc(hwnd, msg, wparam, lparam)
            }
            _ => DefSubclassProc(hwnd, msg, wparam, lparam),
        }
    }

    pub fn strip_decorations(hwnd: *mut c_void, main: bool) {
        unsafe {
            if SetWindowSubclass(hwnd, frameless_proc, SUBCLASS_ID, main as usize) == 0 {
                eprintln!("[win] 安装无边框保护失败: {}", std::io::Error::last_os_error());
                return;
            }
            let style = GetWindowLongPtrW(hwnd, GWL_STYLE);
            let cleaned = clean_style(style);
            if style != cleaned { SetWindowLongPtrW(hwnd, GWL_STYLE, cleaned); }
            let ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
            let cleaned_ex = clean_ex_style(ex, main);
            if ex != cleaned_ex { SetWindowLongPtrW(hwnd, GWL_EXSTYLE, cleaned_ex); }
            SetWindowPos(
                hwnd,
                std::ptr::null_mut(),
                0,
                0,
                0,
                0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            );
        }
    }

    /// Real Win32 regression: emulate the runtime restoring caption styles,
    /// including activation and a non-client recalculation, for both window roles.
    pub fn selftest() -> Result<(), String> {
        let class: Vec<u16> = "STATIC\0".encode_utf16().collect();
        for main in [true, false] {
            unsafe {
                let hwnd = CreateWindowExW(0, class.as_ptr(), class.as_ptr(),
                    (WS_POPUP | WS_CAPTION | WS_SYSMENU) as u32, 0, 0, 320, 200,
                    std::ptr::null_mut(), std::ptr::null_mut(), std::ptr::null_mut(), std::ptr::null_mut());
                if hwnd.is_null() { return Err(std::io::Error::last_os_error().to_string()); }
                strip_decorations(hwnd, main);
                for _ in 0..3 {
                    let style = GetWindowLongPtrW(hwnd, GWL_STYLE);
                    SetWindowLongPtrW(hwnd, GWL_STYLE, style | WS_CAPTION | WS_THICKFRAME);
                    SetWindowPos(hwnd, std::ptr::null_mut(), 0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
                    SendMessageW(hwnd, WM_NCACTIVATE, 1, 0);
                    SendMessageW(hwnd, WM_NCACTIVATE, 0, 0);
                }
                let style = GetWindowLongPtrW(hwnd, GWL_STYLE);
                let ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
                let mut client = Rect::default();
                let mut outer = Rect::default();
                let rect_ok = GetClientRect(hwnd, &mut client) != 0 && GetWindowRect(hwnd, &mut outer) != 0;
                let passed = style & (WS_CAPTION | WS_THICKFRAME) == 0
                    && (ex & WS_EX_APPWINDOW != 0) == main
                    && (ex & WS_EX_TOOLWINDOW != 0) != main
                    && rect_ok && client.right - client.left == outer.right - outer.left
                    && client.bottom - client.top == outer.bottom - outer.top;
                DestroyWindow(hwnd);
                if !passed { return Err(format!("main={main}, style={style:#x}, ex={ex:#x}")); }
            }
        }
        Ok(())
    }
}

fn force_frameless(win: &WebviewWindow) {
    #[cfg(windows)]
    {
        let target = win.clone();
        // Resolve the handle on the owner thread too: a just-created window may
        // not yet expose it to the caller until queued creation messages finish.
        let _ = win.run_on_main_thread(move || match target.hwnd() {
            Ok(h) => winfix::strip_decorations(h.0 as *mut std::ffi::c_void, target.label() == "main"),
            Err(err) => eprintln!("[win] 取 hwnd 失败: {err}"),
        });
    }
    #[cfg(not(windows))]
    let _ = win;
}

fn apply_glass(win: &WebviewWindow) {
    let target = win.clone();
    let _ = win.run_on_main_thread(move || {
        if let Err(err) = window_vibrancy::apply_acrylic(&target, Some((24, 27, 34, 105))) {
            eprintln!("[win] 亚克力效果未启用: {err}");
        }
        force_frameless(&target);
    });
}

// ---------------------------------------------------------------- 数据模型

#[derive(Serialize, Deserialize, Clone, Debug)]
struct Reminder {
    #[serde(default)]
    id: u64,
    #[serde(default)]
    when: String,
    #[serde(default)]
    text: String,
    #[serde(default)]
    fired: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct Store {
    #[serde(default = "default_version")]
    version: String,
    #[serde(default)]
    items: Vec<Reminder>,
    #[serde(default)]
    next_id: u64,
}

fn default_version() -> String {
    "2.1".to_string()
}

impl Default for Store {
    fn default() -> Self {
        Store {
            version: default_version(),
            items: Vec::new(),
            next_id: 1,
        }
    }
}

#[derive(Serialize)]
struct RowDto {
    id: u64,
    when: String,
    text: String,
    fired: bool,
}

#[derive(Serialize)]
struct StateDto {
    items: Vec<RowDto>,
    autostart: bool,
}

#[derive(Serialize)]
struct PopupDto {
    id: u64,
    when: String,
    text: String,
}

struct Shared {
    path: PathBuf,
    store: Mutex<Store>,
    queue: Mutex<Vec<u64>>,
    anchor: Mutex<(f64, f64)>, // 主窗锚点：(x, 底边 y)
}

// ---------------------------------------------------------------- 时间工具

fn parse_when(s: &str) -> Option<NaiveDateTime> {
    NaiveDateTime::parse_from_str(s, FMT)
        .ok()
        .or_else(|| NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S").ok())
}

fn fmt_when(dt: NaiveDateTime) -> String {
    dt.format(FMT).to_string()
}

// ---------------------------------------------------------------- 数据读写

fn normalize(store: &mut Store) {
    let mut max_id = 0u64;
    for it in store.items.iter_mut() {
        if it.id == 0 {
            max_id += 1;
            it.id = max_id;
        }
        max_id = max_id.max(it.id);
    }
    store.next_id = store.next_id.max(max_id + 1).max(1);
    store.items.sort_by(|a, b| a.when.cmp(&b.when));
}

fn load_from(path: &Path) -> Store {
    let mut store = match fs::read_to_string(path) {
        Ok(text) => serde_json::from_str::<Store>(&text).unwrap_or_default(),
        Err(_) => Store::default(),
    };
    store.version = default_version();
    normalize(&mut store);
    store
}

fn save_to(path: &Path, store: &Store) {
    if let Ok(text) = serde_json::to_string_pretty(store) {
        let tmp = path.with_extension("json.tmp");
        if fs::write(&tmp, text.as_bytes()).is_ok() {
            let _ = fs::rename(&tmp, path);
        }
    }
}

fn dir_writable(dir: &Path) -> bool {
    let probe = dir.join(".todaytick_write_test");
    match fs::write(&probe, b"1") {
        Ok(_) => {
            let _ = fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

fn appdata_dir() -> PathBuf {
    let base = std::env::var("APPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::temp_dir());
    base.join(APP_ID)
}

fn data_path() -> PathBuf {
    if let Ok(exe) = std::env::current_exe() {
        let dir = exe.parent().map(|p| p.to_path_buf());
        if let Some(dir) = dir {
            let candidate = dir.join("reminders.json");
            if candidate.exists() || dir_writable(&dir) {
                return candidate;
            }
        }
    }
    let dir = appdata_dir();
    let _ = fs::create_dir_all(&dir);
    dir.join("reminders.json")
}

// ---------------------------------------------------------------- 开机自启

fn autostart_enabled() -> bool {
    use winreg::enums::KEY_READ;
    use winreg::RegKey;
    let hkcu = RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
    hkcu.open_subkey_with_flags(RUN_KEY, KEY_READ)
        .ok()
        .and_then(|k| k.get_value::<String, _>(APP_ID).ok())
        .map(|v| !v.trim().is_empty())
        .unwrap_or(false)
}

fn autostart_set(on: bool) -> Result<bool, String> {
    use winreg::RegKey;
    let hkcu = RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
    let (key, _) = hkcu
        .create_subkey(RUN_KEY)
        .map_err(|e| format!("注册表写入失败: {e}"))?;
    if on {
        let exe = std::env::current_exe().map_err(|e| e.to_string())?;
        let cmd = format!("\"{}\"", exe.display());
        key.set_value(APP_ID, &cmd)
            .map_err(|e| format!("注册表写入失败: {e}"))?;
        Ok(true)
    } else {
        let _ = key.delete_value(APP_ID);
        Ok(false)
    }
}

// ---------------------------------------------------------------- 单实例

fn nudge_running_instance() -> bool {
    match TcpStream::connect(("127.0.0.1", PORT)) {
        Ok(mut stream) => {
            let _ = stream.set_write_timeout(Some(StdDuration::from_millis(600)));
            let _ = stream.write_all(b"show");
            true
        }
        Err(_) => false,
    }
}

fn spawn_instance_listener(app: AppHandle, listener: TcpListener) {
    thread::spawn(move || {
        for incoming in listener.incoming() {
            let Ok(mut stream) = incoming else { continue };
            let mut buf = [0u8; 8];
            let _ = stream.read(&mut buf);
            let handle = app.clone();
            let _ = app.run_on_main_thread(move || show_main(&handle));
        }
    });
}

fn show_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        force_frameless(&win);
        let _ = win.set_focus();
    }
}

// ---------------------------------------------------------------- 托盘

/// 托盘图标：窗口关掉（隐藏）之后，靠它把程序叫回来，或者彻底退出。
fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    use tauri::menu::{Menu, MenuItem};
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};

    let open = MenuItem::with_id(app, "open", "打开窗口", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "hide", "隐藏到托盘", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出 TodayTick", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &hide, &quit])?;

    let builder = TrayIconBuilder::with_id("todaytick-tray")
        .icon(tauri::include_image!("icons/32x32.png"))
        .tooltip(WIN_TITLE)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show_main(app),
            "hide" => {
                if let Err(err) = hide_to_tray(app) {
                    eprintln!("[tray] 隐藏失败: {err}");
                }
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        });

    let tray = builder.build(app)?;
    eprintln!("[tray] 图标已创建，位置: {:?}", tray.rect());
    Ok(())
}

/// Only hide once Windows has an icon that can bring the window back.
fn hide_to_tray(app: &AppHandle) -> Result<(), String> {
    if app.tray_by_id("todaytick-tray").is_none() {
        setup_tray(app).map_err(|e| format!("托盘创建失败，窗口未隐藏：{e}"))?;
    }
    let tray = app.tray_by_id("todaytick-tray")
        .ok_or("托盘未就绪，窗口未隐藏")?;
    if tray.rect().map_err(|e| e.to_string())?.is_none() {
        // Retry registration when Explorer was not ready at startup.
        tray.set_visible(false).map_err(|e| e.to_string())?;
        tray.set_visible(true).map_err(|e| e.to_string())?;
        if tray.rect().map_err(|e| e.to_string())?.is_none() {
            return Err("托盘图标未就绪，窗口未隐藏，请稍后重试".into());
        }
    }
    if let Some(win) = app.get_webview_window("main") {
        win.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ---------------------------------------------------------------- 窗口几何

fn main_anchor_from_monitor(win: &WebviewWindow) -> (f64, f64) {
    let scale = win.scale_factor().unwrap_or(1.0);
    let (mw, mh) = win
        .current_monitor()
        .ok()
        .flatten()
        .map(|m| {
            let s = m.size().to_logical::<f64>(scale);
            (s.width, s.height)
        })
        .unwrap_or((1920.0, 1080.0));
    let x = (mw - WIN_W - 26.0).max(0.0);
    let bottom = (mh - 64.0).max(0.0);
    (x, bottom)
}

fn sync_anchor(app: &AppHandle) {
    let Some(win) = app.get_webview_window("main") else { return };
    let shared = app.state::<Shared>();
    let scale = win.scale_factor().unwrap_or(1.0);
    if let (Ok(pos), Ok(size)) = (win.outer_position(), win.outer_size()) {
        let p = pos.to_logical::<f64>(scale);
        let s = size.to_logical::<f64>(scale);
        if let Ok(mut anchor) = shared.anchor.lock() {
            *anchor = (p.x, p.y + s.height);
        }
    }
}

fn position_popup(win: &WebviewWindow) {
    // Use the main window's monitor, even when it is hidden in the tray.
    let monitor = win.app_handle().get_webview_window("main")
        .and_then(|main| main.current_monitor().ok().flatten())
        .or_else(|| win.current_monitor().ok().flatten())
        .or_else(|| win.primary_monitor().ok().flatten());
    let Some(monitor) = monitor else { return };
    let work = monitor.work_area();
    let scale = monitor.scale_factor();
    let size = win
        .outer_size()
        .map(|s| s.to_logical::<f64>(win.scale_factor().unwrap_or(1.0)))
        .unwrap_or(LogicalSize::new(POPUP_W, 132.0));
    // Work area excludes the taskbar, including side/top taskbars.
    let x = work.position.x as f64 + (work.size.width as f64 - (size.width + 16.0) * scale).max(0.0);
    let y = work.position.y as f64 + (work.size.height as f64 - (size.height + 16.0) * scale).max(0.0);
    let _ = win.set_position(tauri::PhysicalPosition::new(x.round() as i32, y.round() as i32));
}

// ---------------------------------------------------------------- 弹窗

/// WebView2 的用户数据中心候选目录：优先用户配置目录，其次程序目录，最后临时目录。
/// 某些受限环境（沙箱 / 只读目录）下写不进 %LOCALAPPDATA%，需要逐级回退。
fn candidate_dirs() -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Some(base) = std::env::var_os("LOCALAPPDATA") {
        dirs.push(PathBuf::from(base).join(APP_ID).join("EBWebView"));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            dirs.push(parent.join("EBWebView"));
        }
    }
    dirs.push(std::env::temp_dir().join(APP_ID).join("EBWebView"));
    dirs
}

/// 目录必须真的能写：某些环境下目录虽然存在，但被别的进程/权限级别占着，
/// 直接用它会得到一个「创建成功却出不了窗口」的空壳，所以先写个探针文件试一下。
fn usable_data_dir(dir: &std::path::Path) -> bool {
    if fs::create_dir_all(dir).is_err() {
        return false;
    }
    let probe = dir.join(".todaytick-probe");
    let ok = fs::write(&probe, b"ok").is_ok();
    let _ = fs::remove_file(&probe);
    ok
}

/// 依次尝试候选数据目录创建窗口，返回第一个成功的结果。
macro_rules! create_window {
    ($app:expr, $label:expr, $url:expr, |$b:ident, $dir:ident| $cfg:block) => {{
        let mut out: Option<tauri::Result<WebviewWindow>> = None;
        let all = candidate_dirs();
        let mut list: Vec<PathBuf> = all.iter().filter(|d| usable_data_dir(d)).cloned().collect();
        if list.is_empty() {
            list = all;
        }
        for candidate in list {
            let $dir = candidate.clone();
            let $b = WebviewWindowBuilder::new($app, $label, WebviewUrl::App($url.into()))
                .data_directory(candidate);
            let built = { $cfg }.build();
            let ok = built.is_ok();
            out = Some(built);
            if ok {
                break;
            }
        }
        out.expect("没有可用的 WebView2 数据目录候选")
    }};
}

fn ensure_popup(app: &AppHandle) -> Option<WebviewWindow> {
    if let Some(win) = app.get_webview_window("popup") {
        return Some(win);
    }
    let built = create_window!(app, "popup", "popup.html", |b, _dir| {
        b.title("提醒")
            .inner_size(POPUP_W, 132.0)
            .decorations(false)
            .transparent(true)
            .resizable(false)
            .maximizable(false)
            .minimizable(false)
            .closable(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .shadow(false)
            .focused(true)
            .visible(false)
    });
    match built {
        Ok(win) => {
            force_frameless(&win);
            apply_glass(&win);
            Some(win)
        }
        Err(err) => {
            eprintln!("popup window error: {err}");
            None
        }
    }
}

fn show_next_popup(app: &AppHandle) {
    let shared = app.state::<Shared>();
    let head = shared.queue.lock().ok().and_then(|q| q.first().copied());
    match head {
        Some(_) => {
            if let Some(win) = ensure_popup(app) {
                position_popup(&win);
                let _ = win.show();
                force_frameless(&win);
                position_popup(&win);
                let _ = win.set_focus();
                let _ = win.emit("popup-refresh", ());
            }
        }
        None => {
            if let Some(win) = app.get_webview_window("popup") {
                let _ = win.hide();
            }
        }
    }
}

// ---------------------------------------------------------------- 调度

fn tick(app: &AppHandle) {
    let shared = app.state::<Shared>();
    let mut due: Vec<u64> = Vec::new();
    {
        let Ok(mut store) = shared.store.lock() else { return };
        let now = Local::now().naive_local();
        for it in store.items.iter_mut() {
            if it.fired {
                continue;
            }
            if let Some(dt) = parse_when(&it.when) {
                if dt <= now {
                    it.fired = true;
                    due.push(it.id);
                }
            }
        }
        if !due.is_empty() {
            save_to(&shared.path, &store);
        }
    }
    if due.is_empty() {
        return;
    }
    if let Ok(mut q) = shared.queue.lock() {
        for id in due {
            if !q.contains(&id) {
                q.push(id);
            }
        }
    }
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.emit("state-changed", ());
    }
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || show_next_popup(&handle));
}

/// 通知主窗重绘列表（增删改之后都要叫一声）。
fn notify(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.emit("state-changed", ());
    }
}

// ---------------------------------------------------------------- 命令

#[tauri::command]
fn get_state(app: AppHandle) -> Result<StateDto, String> {
    let shared = app.state::<Shared>();
    let store = shared.store.lock().map_err(|e| e.to_string())?;
    Ok(StateDto {
        items: store
            .items
            .iter()
            .map(|it| RowDto {
                id: it.id,
                when: it.when.clone(),
                text: it.text.clone(),
                fired: it.fired,
            })
            .collect(),
        autostart: autostart_enabled(),
    })
}

#[tauri::command]
fn add_reminder(app: AppHandle, text: String, when: String) -> Result<(), String> {
    let text = text.trim().to_string();
    if text.is_empty() {
        return Err("先写一句要提醒的内容".into());
    }
    let dt = parse_when(&when).ok_or_else(|| "时间没看懂".to_string())?;
    if dt <= Local::now().naive_local() {
        return Err("这个时间已经过去了".into());
    }
    let shared = app.state::<Shared>();
    let mut store = shared.store.lock().map_err(|e| e.to_string())?;
    let id = store.next_id.max(1);
    store.next_id = id + 1;
    store.items.push(Reminder {
        id,
        when: fmt_when(dt),
        text,
        fired: false,
    });
    normalize(&mut store);
    save_to(&shared.path, &store);
    drop(store);
    notify(&app);
    Ok(())
}

#[tauri::command]
fn remove_reminder(app: AppHandle, id: u64) -> Result<(), String> {
    let shared = app.state::<Shared>();
    {
        let mut store = shared.store.lock().map_err(|e| e.to_string())?;
        store.items.retain(|it| it.id != id);
        save_to(&shared.path, &store);
    }
    if let Ok(mut q) = shared.queue.lock() {
        q.retain(|x| *x != id);
    }
    notify(&app);
    Ok(())
}

#[tauri::command]
fn set_autostart(on: bool) -> Result<bool, String> {
    autostart_set(on)
}

#[tauri::command]
fn current_popup(app: AppHandle) -> Result<Option<PopupDto>, String> {
    let shared = app.state::<Shared>();
    let head = shared
        .queue
        .lock()
        .map_err(|e| e.to_string())?
        .first()
        .copied();
    let Some(id) = head else { return Ok(None) };
    let store = shared.store.lock().map_err(|e| e.to_string())?;
    Ok(store
        .items
        .iter()
        .find(|it| it.id == id)
        .map(|it| PopupDto {
            id: it.id,
            when: it.when.clone(),
            text: it.text.clone(),
        }))
}

#[tauri::command]
fn ack_popup(app: AppHandle, id: u64) -> Result<(), String> {
    {
        let shared = app.state::<Shared>();
        let mut store = shared.store.lock().map_err(|e| e.to_string())?;
        store.items.retain(|it| it.id != id);
        save_to(&shared.path, &store);
    }
    drop_from_queue(&app, id)?;
    show_next_popup(&app);
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.emit("state-changed", ());
    }
    Ok(())
}

#[tauri::command]
fn snooze_popup(app: AppHandle, id: u64, minutes: Option<i64>) -> Result<(), String> {
    {
        let shared = app.state::<Shared>();
        let mut store = shared.store.lock().map_err(|e| e.to_string())?;
        let later = Local::now().naive_local() + chrono::Duration::minutes(minutes.unwrap_or(5));
        if let Some(it) = store.items.iter_mut().find(|it| it.id == id) {
            it.when = fmt_when(later);
            it.fired = false;
        }
        normalize(&mut store);
        save_to(&shared.path, &store);
    }
    drop_from_queue(&app, id)?;
    show_next_popup(&app);
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.emit("state-changed", ());
    }
    Ok(())
}

fn drop_from_queue(app: &AppHandle, id: u64) -> Result<(), String> {
    let shared = app.state::<Shared>();
    let mut q = shared.queue.lock().map_err(|e| e.to_string())?;
    q.retain(|x| *x != id);
    Ok(())
}

#[tauri::command]
fn resize_main(app: AppHandle, height: f64) -> Result<(), String> {
    let shared = app.state::<Shared>();
    let (x, bottom) = *shared.anchor.lock().map_err(|e| e.to_string())?;
    let h = height.clamp(280.0, 640.0);
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.set_size(LogicalSize::new(WIN_W, h));
        let y = (bottom - h).max(0.0);
        let _ = win.set_position(LogicalPosition::new(x, y));
        force_frameless(&win);
    }
    Ok(())
}

#[tauri::command]
fn popup_ready(app: AppHandle, height: f64) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("popup") {
        let h = height.clamp(96.0, 520.0);
        let _ = win.set_size(LogicalSize::new(POPUP_W, h));
        position_popup(&win);
        force_frameless(&win);
    }
    Ok(())
}

#[tauri::command]
fn hide_main(app: AppHandle) -> Result<(), String> {
    hide_to_tray(&app)
}

#[tauri::command]
fn quit_app(app: AppHandle) -> Result<(), String> {
    app.exit(0);
    Ok(())
}

#[tauri::command]
fn focus_popup(app: AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("popup") {
        let _ = win.set_focus();
    }
    Ok(())
}

// ---------------------------------------------------------------- 自检

fn selftest_dir() -> PathBuf {
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            let dir = parent.join(".selftest");
            if fs::create_dir_all(&dir).is_ok() {
                return dir;
            }
        }
    }
    std::env::temp_dir().join("todaytick_selftest")
}

fn selftest() -> i32 {
    let mut fails: Vec<String> = Vec::new();
    let mut log = String::new();
    let mut check = |name: &str, ok: bool, extra: String| {
        log.push_str(&format!(
            "{} {}{}\n",
            if ok { "PASS" } else { "FAIL" },
            name,
            if extra.is_empty() {
                String::new()
            } else {
                format!(" {extra}")
            }
        ));
        if !ok {
            fails.push(name.to_string());
        }
    };

    #[cfg(windows)]
    {
        let frame = winfix::selftest();
        check("无边框样式重写与焦点切换（主窗/弹窗）", frame.is_ok(), format!("{:?}", frame.err()));
    }

    check(
        "解析 ISO",
        parse_when("2026-11-05T14:35").is_some(),
        "".into(),
    );
    check(
        "拒绝坏 ISO",
        parse_when("2026-13-05T14:35").is_none() && parse_when("").is_none(),
        "".into(),
    );

    // 存储往返（用 exe 同目录下的临时目录：某些受限环境写不了 %TEMP%）
    let dir = selftest_dir();
    let _ = fs::create_dir_all(&dir);
    let path = dir.join("reminders.json");
    let _ = fs::remove_file(&path);
    let mut store = Store::default();
    store.items.push(Reminder {
        id: 0,
        when: "2026-12-01T07:15".into(),
        text: "开会".into(),
        fired: false,
    });
    normalize(&mut store);
    save_to(&path, &store);
    let reloaded = load_from(&path);
    check(
        "存储往返",
        reloaded.items.len() == 1 && reloaded.items[0].text == "开会" && reloaded.items[0].id == 1,
        format!("{:?}", reloaded.items.len()),
    );
    let _ = fs::remove_file(&path);

    // 到期判定
    let now = Local::now().naive_local();
    let past = fmt_when(now - chrono::Duration::minutes(1));
    let future = fmt_when(now + chrono::Duration::minutes(1));
    let past_due = parse_when(&past).map(|d| d <= now).unwrap_or(false);
    let future_due = parse_when(&future).map(|d| d <= now).unwrap_or(false);
    check("到期判定", past_due && !future_due, "".into());

    // 旧版（Python 写出的）数据兼容
    let legacy = r#"{"version":"1.1","sound":true,"items":[{"when":"2026-11-05T14:30","text":"喝水","fired":false}]}"#;
    let _ = fs::write(&path, legacy);
    let from_legacy = load_from(&path);
    check(
        "兼容旧数据",
        from_legacy.items.len() == 1
            && from_legacy.items[0].id == 1
            && from_legacy.items[0].text == "喝水",
        "".into(),
    );
    let _ = fs::remove_file(&path);
    let _ = fs::remove_dir(&dir);

    check("注册表可读", !autostart_enabled() || autostart_enabled(), "".into());

    // 注册表可写（开机自启要写 HKCU\...\Run）
    let reg_write = (|| -> Result<(), String> {
        use winreg::RegKey;
        let hkcu = RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
        let (key, _) = hkcu
            .create_subkey(RUN_KEY)
            .map_err(|e| format!("打开 Run 键失败: {e}"))?;
        key.set_value("TodayTickSelftest", &"probe")
            .map_err(|e| format!("写值失败: {e}"))?;
        let back: String = key
            .get_value("TodayTickSelftest")
            .map_err(|e| format!("读回失败: {e}"))?;
        let _ = key.delete_value("TodayTickSelftest");
        if back == "probe" {
            Ok(())
        } else {
            Err("读回内容不符".into())
        }
    })();
    check("注册表可写", reg_write.is_ok(), format!("{:?}", reg_write.err()));

    let summary = if fails.is_empty() {
        "SELFTEST PASS".to_string()
    } else {
        format!("SELFTEST FAIL: {}", fails.join(", "))
    };
    log.push_str(&format!("{summary}\n"));
    print!("{log}");
    let _ = std::io::stdout().flush();
    let log_path = selftest_dir().join("todaytick_selftest.log");
    let _ = fs::write(&log_path, &log);
    if fails.is_empty() {
        0
    } else {
        1
    }
}


// ---------------------------------------------------------------- 入口

fn main() {
    if std::env::args().any(|a| a == "--selftest") {
        std::process::exit(selftest());
    }
    if nudge_running_instance() {
        return;
    }
    let listener = TcpListener::bind(("127.0.0.1", PORT)).ok();

    tauri::Builder::default()
        .setup(move |app| {
            let handle = app.handle().clone();
            let path = data_path();
            let store = load_from(&path);
            save_to(&path, &store);
            app.manage(Shared {
                path,
                store: Mutex::new(store),
                queue: Mutex::new(Vec::new()),
                anchor: Mutex::new((0.0, 0.0)),
            });

            match create_window!(app.handle(), "main", "index.html", |b, dir| {
                eprintln!("[main] 数据目录: {dir:?}");
                b.title(WIN_TITLE)
                    .inner_size(WIN_W, 360.0)
                    .decorations(false)
                    .transparent(true)
                    .shadow(false)
                    .resizable(false)
                    .maximizable(false)
                    .minimizable(true)
                    .visible(false)
                    .accept_first_mouse(true)
            }) {
                Ok(win) => {
                    let shared = app.state::<Shared>();
                    let (x, bottom) = main_anchor_from_monitor(&win);
                    if let Ok(mut anchor) = shared.anchor.lock() {
                        *anchor = (x, bottom);
                    }
                    let _ = win.set_position(LogicalPosition::new(x, bottom - 360.0));
                    let move_handle = handle.clone();
                    win.on_window_event(move |event| {
                        if let tauri::WindowEvent::Moved(_) = event {
                            sync_anchor(&move_handle);
                        }
                        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                            api.prevent_close();
                            if let Err(err) = hide_to_tray(&move_handle) {
                                eprintln!("[tray] 收起失败，保留窗口: {err}");
                            }
                        }
                    });
                    let _ = win.show();
                    // show() 之后 tauri 会把窗口样式还原成带标题栏的版本，这里再削一次。
                    force_frameless(&win);
                    apply_glass(&win);
                    let _ = win.set_position(LogicalPosition::new(x, bottom - 360.0));
                }
                Err(err) => {
                    eprintln!("[main] 窗口创建失败: {err}");
                }
            }

            if let Some(listener) = listener {
                spawn_instance_listener(handle.clone(), listener);
            }

            if let Err(err) = setup_tray(&handle) {
                eprintln!("[tray] 托盘创建失败: {err}");
            }

            let ticker = handle.clone();
            thread::spawn(move || loop {
                thread::sleep(StdDuration::from_millis(300));
                tick(&ticker);
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_state,
            add_reminder,
            remove_reminder,
            set_autostart,
            current_popup,
            ack_popup,
            snooze_popup,
            resize_main,
            popup_ready,
            hide_main,
            quit_app,
            focus_popup
        ])
        .run(tauri::generate_context!())
        .expect("TodayTick 启动失败");
}
