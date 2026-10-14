#!/usr/bin/env python3
"""Genera worker.js inserendo index.html, style.css e app.js dentro worker_template.js.
Uso: python3 build_worker.py   (rilancialo dopo ogni modifica a uno dei tre file)"""
import json, pathlib

root = pathlib.Path(__file__).parent
template = (root / "worker_template.js").read_text(encoding="utf-8")


def literal(name):
    text = (root / name).read_text(encoding="utf-8")
    # json.dumps produce una stringa JavaScript valida; "</" viene protetto per sicurezza
    return json.dumps(text, ensure_ascii=False).replace("</", "<\\/")


for marker, name in (("__HTML__", "index.html"), ("__CSS__", "style.css"), ("__JS__", "app.js")):
    assert template.count(marker) == 1, marker
    template = template.replace(marker, literal(name))
(root / "worker.js").write_text(template, encoding="utf-8")
print("worker.js generato da index.html, style.css, app.js")
