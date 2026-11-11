#[tauri::command]
pub async fn pick_project_folder(
    window: tauri::WebviewWindow,
    title: String,
    accept: String,
    cancel: String,
) -> Result<Option<String>, String> {
    #[cfg(target_os = "linux")]
    {
        use gtk::prelude::*;

        let (send, receive) = std::sync::mpsc::sync_channel(1);
        let parent = window.clone();
        window
            .run_on_main_thread(move || {
                let result = parent
                    .gtk_window()
                    .map_err(|error| error.to_string())
                    .and_then(|parent| {
                        let chooser = gtk::FileChooserNative::new(
                            Some(&title),
                            Some(&parent),
                            gtk::FileChooserAction::SelectFolder,
                            Some(&accept),
                            Some(&cancel),
                        );
                        if chooser.run() != gtk::ResponseType::Accept {
                            return Ok(None);
                        }
                        chooser
                            .filename()
                            .and_then(|path| path.into_os_string().into_string().ok())
                            .map(Some)
                            .ok_or_else(|| "project_path_unavailable".to_owned())
                    });
                let _ = send.send(result);
            })
            .map_err(|error| error.to_string())?;
        tauri::async_runtime::spawn_blocking(move || receive.recv())
            .await
            .map_err(|error| error.to_string())?
            .map_err(|error| error.to_string())?
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (window, title, accept, cancel);
        Err("folder_picker_unavailable".to_owned())
    }
}
