#!/usr/bin/env python3
"""Automazione "Preparazione della consegna", da avviare a mano prima di RTB e PB.

Elenca i documenti e i verbali modificati dopo l'ultima approvazione per il
rilascio, cioè con versione X.Y.Z e Y o Z diversi da zero: prima della consegna
hanno bisogno della riga di approvazione X+1.0.0 del Responsabile (Norme di
Progetto, versionamento). I documenti incrementali ancora alla 0.Y.Z hanno
bisogno della 1.0.0 solo se si presentano a questa revisione: sono elencati a parte.
Se nessun documento ha bisogno di approvazione, scrive in consegna/elenco.txt i
PDF da allegare alla release, che il workflow crea con gh.
"""
from __future__ import annotations

import importlib.util
import sys

import comune as c

spec = importlib.util.spec_from_file_location("genera", c.RADICE / "vista-web" / "genera.py")
genera = importlib.util.module_from_spec(spec)
spec.loader.exec_module(genera)


def principale() -> int:
    consegne = genera.carica_elenco()["consegne"]
    documenti, _ = genera.analizza_tutti(consegne)
    da_approvare, incrementali, pdf = [], [], []
    for d in documenti:
        pdf.append(d["file"])
        if "versione" not in d:
            continue
        x, y, z = genera.numeri(d["versione"])
        if x == 0:
            incrementali.append(d)
        elif y or z:
            da_approvare.append(d)
    righe = ["### Preparazione della consegna", ""]
    if da_approvare:
        righe.append("Hanno bisogno dell'approvazione per il rilascio (riga X+1.0.0):")
        righe += [f"- `{d['file']}`: {d['versione']} -> {genera.numeri(d['versione'])[0] + 1}.0.0"
                  for d in da_approvare]
    else:
        righe.append("Nessun documento rilasciato ha modifiche da approvare.")
    if incrementali:
        righe += ["", "Ancora alla 0.Y.Z (1.0.0 solo se si presentano a questa revisione):"]
        righe += [f"- `{d['file']}`: {d['versione']}" for d in incrementali]
    c.riepilogo("\n".join(righe))
    if da_approvare:
        for d in da_approvare:
            c.errore(f"{d['file']}: manca l'approvazione per il rilascio ({d['versione']})")
        return 1
    (c.RADICE / "consegna").mkdir(exist_ok=True)
    (c.RADICE / "consegna" / "elenco.txt").write_text("\n".join(sorted(pdf)) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(principale())
