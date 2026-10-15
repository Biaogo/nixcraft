"""Input methods: the fcitx5 commit event, the caret rect, and focus that never settles.

DeckCraft / DesignCraft canvas editors only handle Event::Text, and fcitx5 commits arrive as
Event::Ime. A caret that never publishes an IME rect leaves the candidate window with nothing
to anchor to. Requesting focus on every frame interrupts composition on every frame, which
dismisses fcitx5.
"""


def patch_deck_ime(path, text):
    old = "                egui::Event::Text(t) => {"
    new = "                egui::Event::Text(t) | egui::Event::Ime(egui::ImeEvent::Commit(t)) => {"
    if "fn keyboard" not in text or old not in text or "ImeEvent::Commit" in text:
        return text, False
    text = text.replace(old, new, 1)
    return text, True


def patch_deck_caret(path, text):
    old = '''            if blink && let Some((cx, top, bot)) = l.caret(deckcraft_text::Pos { para: ts.caret.0, ch: ts.caret.1 }) {
                let (p0, p1) = (xf.to_screen(m * Point::new(cx, top)), xf.to_screen(m * Point::new(cx, bot)));
                painter.line_segment([p0, p1], Stroke::new(1.5, t.caret));
            }'''
    new = '''            if let Some((cx, top, bot)) = l.caret(deckcraft_text::Pos { para: ts.caret.0, ch: ts.caret.1 }) {
                let (p0, p1) = (xf.to_screen(m * Point::new(cx, top)), xf.to_screen(m * Point::new(cx, bot)));
                if blink {
                    painter.line_segment([p0, p1], Stroke::new(1.5, t.caret));
                }
                let cr = egui::Rect::from_two_pos(p0, p1);
                ui.ctx().output_mut(|o| {
                    o.ime = Some(egui::output::IMEOutput {
                        rect: cr,
                        cursor_rect: cr,
                        purpose: Default::default(),
                        should_interrupt_composition: false,
                    });
                });
            }'''
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


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
    old = '''        let blink = (painter.ctx().input(|i| i.time) * 1.6) as i64 % 2 == 0;
        if blink {
            let p0 = xf.to_screen(m * Point::new(x, bl - asc));
            let p1 = xf.to_screen(m * Point::new(x, bl + desc));
            painter.line_segment([p0, p1], Stroke::new(1.0, Color32::BLACK));
        }
        painter.ctx().request_repaint_after(std::time::Duration::from_millis(330));'''
    new = '''        let blink = (painter.ctx().input(|i| i.time) * 1.6) as i64 % 2 == 0;
        let p0 = xf.to_screen(m * Point::new(x, bl - asc));
        let p1 = xf.to_screen(m * Point::new(x, bl + desc));
        if blink {
            painter.line_segment([p0, p1], Stroke::new(1.0, Color32::BLACK));
        }
        let cr = egui::Rect::from_two_pos(p0, p1);
        painter.ctx().output_mut(|o| {
            o.ime = Some(egui::output::IMEOutput {
                rect: cr,
                cursor_rect: cr,
                purpose: Default::default(),
                should_interrupt_composition: false,
            });
        });
        painter.ctx().request_repaint_after(std::time::Duration::from_millis(330));'''
    if old not in text:
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
