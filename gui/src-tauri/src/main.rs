// Keep the desktop executable in the Windows GUI subsystem in every profile.
#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

fn main() {
    #[cfg(target_os = "linux")]
    {
        // Match the installed ai.loushang.desktop launcher in Wayland docks.
        gtk::glib::set_prgname(Some("ai.loushang"));
        if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
            std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
        }
    }

    harness_gui_lib::run();
}
