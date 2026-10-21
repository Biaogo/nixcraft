"""Input method fixes for focus that re-requests every frame.

DesignCraft v0.9+ handles the fcitx5 commit, the caret-anchored candidate window, and its own
search field upstream (Event::Ime -> ime_event, ime_output, search_field). This module only
carries the remaining film focus and vector palette focus rules.
"""


def patch_film_focus(path, text):
    old = '''    ui.memory_mut(|m| {
        m.request_focus(eid);
        m.set_focus_lock_filter(eid, egui::EventFilter { tab: true, horizontal_arrows: true, vertical_arrows: true, escape: true });
    });'''
    new = '''    ui.memory_mut(|m| {
        // request_focus every frame resets the focus lock and dismisses fcitx on the video frame.
        if m.focused() != Some(eid) {
            m.request_focus(eid);
            m.set_focus_lock_filter(eid, egui::EventFilter { tab: true, horizontal_arrows: true, vertical_arrows: true, escape: true });
        }
    });'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def patch_vector_search_ime(path, text):
    """request_focus every frame resets text-input-v3 and fcitx dismisses."""
    changed = False
    old = '''pub fn show(app: &mut VectorcraftApp, ctx: &egui::Context) {
    if !app.ui.palette_open {
        return;
    }'''
    new = '''pub fn show(app: &mut VectorcraftApp, ctx: &egui::Context) {
    if !app.ui.palette_open {
        ctx.data_mut(|d| d.remove::<bool>(egui::Id::new("palette-ime-focus")));
        return;
    }'''
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    old = '''            let r = ui.add(egui::TextEdit::singleline(&mut app.ui.palette_query).hint_text(tl!("Search commands and tools…")).desired_width(500.0));
            r.request_focus();'''
    new = '''            let r = ui.add(egui::TextEdit::singleline(&mut app.ui.palette_query).hint_text(tl!("Search commands and tools…")).desired_width(500.0));
            // Once per open. Every frame dismisses fcitx.
            let ime = egui::Id::new("palette-ime-focus");
            if !ui.data(|d| d.get_temp::<bool>(ime)).unwrap_or(false) {
                r.request_focus();
                ui.data_mut(|d| d.insert_temp(ime, true));
            }'''
    if old in text:
        text = text.replace(old, new, 1)
        changed = True
    old = '''    if ui.memory(|m| m.focused().is_none()) {
        ui.memory_mut(|m| m.request_focus(field.with("edit")));
    }'''
    new = '''    // The sizing pass has no widget yet. Focus once on the next frame, not every frame.
    if pass == st.opened + 1 {
        ui.memory_mut(|m| m.request_focus(field.with("edit")));
    }'''
    if old in text and "pass == st.opened + 1" not in text:
        text = text.replace(old, new, 1)
        changed = True
    return text, changed
