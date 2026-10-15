"""Widgets the app paints by hand.

A painted control is not a widget: ui.allocate_exact_size returns (Rect, Response), and
keeping only the Rect drops every click on it.
"""


def patch_design_search(path, text):
    """The app bar's Search field is painted by hand and its response was dropped.

    ``allocate_exact_size`` returns ``(Rect, Response)``; the app kept the Rect for
    painting and bound the Response to ``_``, so a click on the field did nothing.
    Bind it and open Quick Apply, the app's only search UI.
    """
    old = '''                        // Search field.
                        let (r, _) = ui.allocate_exact_size(vec2(125.0, 18.0), Sense::click());'''
    new = '''                        // Search field. The field is painted by hand, so its response is the
                        // only thing that knows it was clicked; it opens Quick Apply (Cmd+Return).
                        let (r, search_resp) = ui.allocate_exact_size(vec2(125.0, 18.0), Sense::click());
                        if search_resp.clicked() {
                            let _ = app.run("app.palette", json!(null));
                        }'''
    if new in text:
        return text, False
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True
