#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

struct BackendState {
    port: Mutex<u16>,
}

#[tauri::command]
fn get_backend_port(state: tauri::State<BackendState>) -> Result<u16, String> {
    state.port.lock().map(|port| *port).map_err(|e| e.to_string())
}

fn main() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0")
        .expect("failed to bind to an available localhost port");
    let backend_port = listener
        .local_addr()
        .expect("failed to read allocated localhost port")
        .port();
    drop(listener);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState {
            port: Mutex::new(backend_port),
        })
        .setup(move |app| {
            let sidecar_command = app
                .handle()
                .shell()
                .sidecar("python-backend")
                .map_err(|e| format!("failed to create sidecar command: {e}"))?;

            let (mut receiver, _) = sidecar_command
                .args(["--port", &backend_port.to_string()])
                .spawn()
                .map_err(|e| format!("failed to spawn backend sidecar: {e}"))?;

            tauri::async_runtime::spawn(async move {
                while let Some(event) = receiver.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => println!("[python-backend] {line}"),
                        CommandEvent::Stderr(line) => eprintln!("[python-backend] {line}"),
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_backend_port])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
