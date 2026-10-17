"""Input methods: the fcitx5 commit event, the caret rect, and focus that never settles.

DesignCraft's canvas editor only handles Event::Text, so fcitx5 commits arrive as Event::Ime
and are dropped. A caret that never publishes an IME rect leaves the candidate window with
nothing to anchor to. Requesting focus on every frame interrupts composition on every frame,
which dismisses fcitx5.

DeckCraft needed both of the first two: its v0.8 slide editor now runs its own ime_event
(preedit, commit, end) and publishes IMEOutput from the caret itself, so its rules are gone.
DesignCraft's v0.9 (unreleased at the time of writing) does the same; the two rules that
still rewrite it are `pending` in the drift report and go when that release lands.
"""


def patch_design_ime(path, text):
    old = '''            egui::Event::Text(t) if wants_text => {
                let _ = app.run("text.insert", json!({"text": t}));
            }'''
    new = '''            egui::Event::Text(t) | egui::Event::Ime(egui::ImeEvent::Commit(t)) if wants_text => {
                let _ = app.run("text.insert", json!({"text": t}));
            }'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


def patch_design_caret(path, text):
    """Publish the caret rect so fcitx5 anchors the candidate window at it.

    v0.8.0 paints the caret inside `if blink` and builds both endpoints there, so the rect
    only exists while the caret is shown: lift the endpoints out, paint from them, and hand
    the same rect to egui's IME output on every frame.
    """
    old = '''        let m = a * doc.text_xf(it);
        let blink = (painter.ctx().input(|i| i.time) * 1.6) as i64 % 2 == 0;
        if blink {
            // Type on a path: the caret stands across the path where it is along it.
            let on = |p: Point| compose::PathTextMap::new(it, ft).map_or(p, |map| map.to_path(p));
            let p0 = xf.to_screen(m * on(Point::new(x, bl - asc)));
            let p1 = xf.to_screen(m * on(Point::new(x, bl + desc)));
            painter.line_segment([p0, p1], Stroke::new(1.0, Color32::BLACK));
        }
        painter.ctx().request_repaint_after(std::time::Duration::from_millis(330));'''
    new = '''        let m = a * doc.text_xf(it);
        // Type on a path: the caret stands across the path where it is along it.
        let on = |p: Point| compose::PathTextMap::new(it, ft).map_or(p, |map| map.to_path(p));
        let p0 = xf.to_screen(m * on(Point::new(x, bl - asc)));
        let p1 = xf.to_screen(m * on(Point::new(x, bl + desc)));
        let blink = (painter.ctx().input(|i| i.time) * 1.6) as i64 % 2 == 0;
        if blink {
            painter.line_segment([p0, p1], Stroke::new(1.0, Color32::BLACK));
        }
        // The candidate window follows the caret; without a rect fcitx5 anchors it to the window.
        // A focused widget (a dialog field, the palette) publishes its own - leave that one alone.
        if painter.ctx().memory(|mem| mem.focused().is_none()) {
            let cr = egui::Rect::from_two_pos(p0, p1).expand(1.0);
            painter.ctx().output_mut(|o| {
                o.ime = Some(egui::output::IMEOutput {
                    rect: cr,
                    cursor_rect: cr,
                    purpose: egui::IMEPurpose::Normal,
                    should_interrupt_composition: false,
                });
            });
        }
        painter.ctx().request_repaint_after(std::time::Duration::from_millis(330));'''
    if "The candidate window follows the caret" in text or old not in text:
        return text, False
    return text.replace(old, new, 1), True


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
