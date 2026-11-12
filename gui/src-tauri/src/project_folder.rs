#[tauri::command]
pub async fn pick_project_folder(
    window: tauri::WebviewWindow,
    title: String,
    accept: String,
    cancel: String,
) -> Result<Option<String>, String> {
    let (send, receive) = std::sync::mpsc::sync_channel(1);
    let parent = window.clone();
    window
        .run_on_main_thread(move || {
            let _ = send.send(pick(&parent, &title, &accept, &cancel));
        })
        .map_err(|error| error.to_string())?;
    tauri::async_runtime::spawn_blocking(move || receive.recv())
        .await
        .map_err(|error| error.to_string())?
        .map_err(|error| error.to_string())?
}

#[cfg(target_os = "linux")]
fn pick(
    window: &tauri::WebviewWindow,
    title: &str,
    accept: &str,
    cancel: &str,
) -> Result<Option<String>, String> {
    use gtk::prelude::*;

    let parent = window.gtk_window().map_err(|error| error.to_string())?;
    let chooser = gtk::FileChooserNative::new(
        Some(title),
        Some(&parent),
        gtk::FileChooserAction::SelectFolder,
        Some(accept),
        Some(cancel),
    );
    if chooser.run() != gtk::ResponseType::Accept {
        return Ok(None);
    }
    chooser
        .filename()
        .and_then(|path| path.into_os_string().into_string().ok())
        .map(Some)
        .ok_or_else(|| "project_path_unavailable".to_owned())
}

#[cfg(target_os = "windows")]
fn pick(
    window: &tauri::WebviewWindow,
    title: &str,
    accept: &str,
    _cancel: &str,
) -> Result<Option<String>, String> {
    use windows::Win32::System::Com::{CoInitializeEx, CoUninitialize, COINIT_APARTMENTTHREADED};

    let parent = window.hwnd().map_err(|error| error.to_string())?;
    // The modal dialog runs on the owning GUI thread in a COM STA.
    unsafe {
        CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            .ok()
            .map_err(|error| error.to_string())?;
        let result = pick_windows_dialog(parent, title, accept);
        CoUninitialize();
        result.map_err(|error| error.to_string())
    }
}

#[cfg(target_os = "windows")]
fn pick_windows_dialog(
    parent: windows::Win32::Foundation::HWND,
    title: &str,
    accept: &str,
) -> windows::core::Result<Option<String>> {
    use windows::core::{HRESULT, HSTRING};
    use windows::Win32::Foundation::ERROR_CANCELLED;
    use windows::Win32::System::Com::{CoCreateInstance, CoTaskMemFree, CLSCTX_INPROC_SERVER};
    use windows::Win32::UI::Shell::{
        FileOpenDialog, IFileOpenDialog, FOS_FORCEFILESYSTEM, FOS_PICKFOLDERS, SIGDN_FILESYSPATH,
    };

    // The caller initialized COM on this thread and supplied its live owner HWND.
    unsafe {
        let dialog: IFileOpenDialog =
            CoCreateInstance(&FileOpenDialog, None, CLSCTX_INPROC_SERVER)?;
        dialog.SetOptions(dialog.GetOptions()? | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM)?;
        dialog.SetTitle(&HSTRING::from(title))?;
        dialog.SetOkButtonLabel(&HSTRING::from(accept))?;
        match dialog.Show(Some(parent)) {
            Err(error) if error.code() == HRESULT::from_win32(ERROR_CANCELLED.0) => {
                return Ok(None)
            }
            result => result?,
        }
        let path = dialog.GetResult()?.GetDisplayName(SIGDN_FILESYSPATH)?;
        let result = path.to_string();
        CoTaskMemFree(Some(path.0.cast()));
        result.map(Some).map_err(Into::into)
    }
}

#[cfg(not(any(target_os = "linux", target_os = "windows")))]
fn pick(
    _window: &tauri::WebviewWindow,
    _title: &str,
    _accept: &str,
    _cancel: &str,
) -> Result<Option<String>, String> {
    Err("folder_picker_unavailable".to_owned())
}
