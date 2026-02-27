use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, Emitter};

mod window_detect;

// ═══════════════════════════════════════════════════════════════════
// Python Backend Process Manager
// ═══════════════════════════════════════════════════════════════════

struct BackendProcess {
    child: Option<Child>,
}

impl BackendProcess {
    fn new() -> Self {
        Self { child: None }
    }

    fn start(&mut self, app_dir: &str) -> Result<(), String> {
        if self.child.is_some() {
            return Ok(()); // Already running
        }

        let script = format!("{}\\backend\\autoclicker_service.py", app_dir);

        let child = Command::new("python")
            .arg(&script)
            .current_dir(app_dir)
            .env("PYTHONIOENCODING", "utf-8")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to start Python backend: {}", e))?;

        log::info!("Python backend started (PID: {})", child.id());
        self.child = Some(child);
        Ok(())
    }

    fn stop(&mut self) {
        if let Some(mut child) = self.child.take() {
            log::info!("Stopping Python backend...");
            let _ = child.kill();
            let _ = child.wait();
            log::info!("Python backend stopped");
        }
    }
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        self.stop();
    }
}

// ═══════════════════════════════════════════════════════════════════
// Tauri Commands — Proxy to Python Backend
// ═══════════════════════════════════════════════════════════════════

const BACKEND_URL: &str = "http://127.0.0.1:9876";

/// Generic proxy — forward a GET request to the Python backend
#[tauri::command]
async fn proxy_get(path: String) -> Result<String, String> {
    let url = format!("{}{}", BACKEND_URL, path);
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("Backend unreachable: {}", e))?;
    resp.text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))
}

/// Generic proxy — forward a POST request to the Python backend
#[tauri::command]
async fn proxy_post(path: String, body: String) -> Result<String, String> {
    let client = reqwest::Client::new();
    let url = format!("{}{}", BACKEND_URL, path);
    let resp = client
        .post(&url)
        .header("Content-Type", "application/json")
        .body(body)
        .send()
        .await
        .map_err(|e| format!("Backend unreachable: {}", e))?;
    resp.text()
        .await
        .map_err(|e| format!("Failed to read response: {}", e))
}

/// Start the Python backend process
#[tauri::command]
async fn start_backend(state: tauri::State<'_, Mutex<BackendProcess>>) -> Result<String, String> {
    let app_dir = std::env::current_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| ".".to_string());

    let mut backend = state.lock().map_err(|_| "Lock error".to_string())?;
    backend.start(&app_dir)?;
    Ok("Backend started".to_string())
}

/// Stop the Python backend process
#[tauri::command]
async fn stop_backend(state: tauri::State<'_, Mutex<BackendProcess>>) -> Result<String, String> {
    let mut backend = state.lock().map_err(|_| "Lock error".to_string())?;
    backend.stop();
    Ok("Backend stopped".to_string())
}

/// Check if backend is reachable
#[tauri::command]
async fn check_backend() -> bool {
    reqwest::get(format!("{}/api/health", BACKEND_URL))
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

// ═══════════════════════════════════════════════════════════════════
// App Entry
// ═══════════════════════════════════════════════════════════════════

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::new().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .manage(Mutex::new(BackendProcess::new()))
        .invoke_handler(tauri::generate_handler![
            proxy_get,
            proxy_post,
            start_backend,
            stop_backend,
            check_backend,
            window_detect::detect_ide_windows,
        ])
        .setup(|app| {
            // Auto-start Python backend on app launch
            // CWD during tauri dev is src-tauri, so go up one level to project root
            let managed: tauri::State<Mutex<BackendProcess>> = app.state();
            let cwd: String = std::env::current_dir()
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_else(|_| ".".to_string());
            
            // If CWD ends with src-tauri, go up to project root
            let app_dir: String = if cwd.ends_with("src-tauri") {
                std::path::Path::new(&cwd)
                    .parent()
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or(cwd.clone())
            } else {
                cwd.clone()
            };
            
            log::info!("Project root: {}", app_dir);

            if let Ok(mut backend) = managed.lock() {
                let result: Result<(), String> = backend.start(&app_dir);
                match result {
                    Ok(()) => log::info!("Auto-started Python backend"),
                    Err(e) => log::warn!("Failed to auto-start backend: {}", e),
                }
            }

            // Register global shortcut: F12 = Kill Switch
            use tauri_plugin_global_shortcut::GlobalShortcutExt;
            let app_handle = app.handle().clone();
            let _ = app.global_shortcut().on_shortcut("F12", move |_app, _shortcut, event| {
                if event.state == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                    log::info!("F12 Kill Switch pressed!");
                    // Fire kill switch via backend API
                    let handle = app_handle.clone();
                    std::thread::spawn(move || {
                        let _ = reqwest::blocking::Client::new()
                            .post(format!("{}/api/killswitch/activate", BACKEND_URL))
                            .send();
                        // Emit event to frontend
                        let _ = handle.emit("kill-switch", true);
                    });
                }
            });
            log::info!("Global shortcut F12 registered (Kill Switch)");

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app, event| {
            // Auto-pause scanner when our window gains focus,
            // resume when it loses focus
            if let tauri::RunEvent::WindowEvent { event: win_event, .. } = &event {
                match win_event {
                    tauri::WindowEvent::Focused(focused) => {
                        let is_focused = *focused;
                        std::thread::spawn(move || {
                            if is_focused {
                                // Window gained focus — pause scanner
                                let _ = reqwest::blocking::Client::new()
                                    .post(format!("{}/api/scanner/focuspause", BACKEND_URL))
                                    .body("{\"focused\": true}")
                                    .header("Content-Type", "application/json")
                                    .send();
                            } else {
                                // Window lost focus — resume scanner
                                let _ = reqwest::blocking::Client::new()
                                    .post(format!("{}/api/scanner/focuspause", BACKEND_URL))
                                    .body("{\"focused\": false}")
                                    .header("Content-Type", "application/json")
                                    .send();
                            }
                        });
                    }
                    _ => {}
                }
            }
        });
}
