//! Native window detection for VegaAutoclicker.
//! Enumerates visible windows, filters by known IDE executables,
//! and returns ranked matches. ~100x faster than Python's win32gui approach.

use serde::Serialize;
use std::ffi::OsString;
use std::os::windows::ffi::OsStringExt;
use windows_sys::Win32::Foundation::{CloseHandle, BOOL, HWND, LPARAM, TRUE};
use windows_sys::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetWindowRect, GetWindowTextLengthW, GetWindowTextW, GetWindowThreadProcessId,
    IsWindowVisible,
};

/// A detected IDE window
#[derive(Debug, Clone, Serialize)]
pub struct DetectedWindow {
    pub hwnd: isize,
    pub title: String,
    pub exe: String,
    pub left: i32,
    pub top: i32,
    pub right: i32,
    pub bottom: i32,
    pub width: i32,
    pub height: i32,
    pub score: i32,
}

/// Known IDE executable basenames (lowercase, without path)
const IDE_EXES: &[&str] = &[
    "code.exe",
    "code - insiders.exe",
    "antigravity.exe",
    "cursor.exe",
    "windsurf.exe",
    "kimi.exe",
];

/// Window title substrings to exclude (our own app)
const EXCLUDE_TITLES: &[&str] = &["\u{26a1} vegaautoclicker", "vegaautoclicker"];

/// Get the executable basename for a window's process
fn get_exe_name(hwnd: HWND) -> Option<String> {
    unsafe {
        let mut pid: u32 = 0;
        GetWindowThreadProcessId(hwnd, &mut pid);
        if pid == 0 {
            return None;
        }

        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return None;
        }

        let mut buf = [0u16; 512];
        let mut len = buf.len() as u32;
        let ok = QueryFullProcessImageNameW(handle, 0, buf.as_mut_ptr(), &mut len);
        CloseHandle(handle);

        if ok == 0 || len == 0 {
            return None;
        }

        let path = OsString::from_wide(&buf[..len as usize])
            .to_string_lossy()
            .to_string();
        path.rsplit('\\').next().map(|s| s.to_lowercase())
    }
}

/// Get window title as String
fn get_window_title(hwnd: HWND) -> Option<String> {
    unsafe {
        let len = GetWindowTextLengthW(hwnd);
        if len == 0 {
            return None;
        }
        let mut buf = vec![0u16; (len + 1) as usize];
        let copied = GetWindowTextW(hwnd, buf.as_mut_ptr(), buf.len() as i32);
        if copied == 0 {
            return None;
        }
        Some(
            OsString::from_wide(&buf[..copied as usize])
                .to_string_lossy()
                .to_string(),
        )
    }
}

struct CallbackData {
    hints: Vec<String>,
    results: Vec<DetectedWindow>,
}

/// Find all visible IDE windows matching the given hint strings.
/// Returns them ranked by relevance (main IDE window first).
pub fn find_ide_windows(hints: &[&str]) -> Vec<DetectedWindow> {
    let mut data = Box::new(CallbackData {
        hints: hints.iter().map(|s| s.to_lowercase()).collect(),
        results: Vec::new(),
    });

    unsafe extern "system" fn enum_callback(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let data = &mut *(lparam as *mut CallbackData);

        if IsWindowVisible(hwnd) == 0 {
            return TRUE;
        }

        let title = match get_window_title(hwnd) {
            Some(t) if t.len() > 3 => t,
            _ => return TRUE,
        };

        let title_lower = title.to_lowercase();

        // Skip our own app windows
        for exclude in EXCLUDE_TITLES {
            if title_lower.contains(exclude) {
                return TRUE;
            }
        }

        // Check if this is a whitelisted IDE process
        let exe = match get_exe_name(hwnd) {
            Some(e) => e,
            None => return TRUE,
        };

        if !IDE_EXES.iter().any(|&ide| ide == exe) {
            return TRUE;
        }

        // Check if any hint matches the title
        let mut matched = false;
        for hint in &data.hints {
            if title_lower.contains(hint.as_str()) {
                matched = true;
                break;
            }
        }

        if !matched {
            return TRUE;
        }

        // Get window rect
        let mut rect = windows_sys::Win32::Foundation::RECT {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        GetWindowRect(hwnd, &mut rect);
        let w = rect.right - rect.left;
        let h = rect.bottom - rect.top;

        if w < 200 || h < 200 {
            return TRUE;
        }

        // Score: larger windows score higher, IDE name at end of title = bonus
        let mut score = (w * h) / 10000;
        for hint in &data.hints {
            if title_lower.trim_end().ends_with(hint.as_str()) {
                score += 1000;
                break;
            }
        }

        data.results.push(DetectedWindow {
            hwnd: hwnd as isize,
            title,
            exe,
            left: rect.left,
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
            width: w,
            height: h,
            score,
        });

        TRUE
    }

    let data_ptr = &mut *data as *mut CallbackData as LPARAM;
    unsafe {
        EnumWindows(Some(enum_callback), data_ptr);
    }

    data.results.sort_by(|a, b| b.score.cmp(&a.score));
    data.results
}

/// Tauri command: find IDE windows from the frontend or Python backend
#[tauri::command]
pub fn detect_ide_windows(hints: Vec<String>) -> Vec<DetectedWindow> {
    let hint_refs: Vec<&str> = hints.iter().map(|s| s.as_str()).collect();
    find_ide_windows(&hint_refs)
}
