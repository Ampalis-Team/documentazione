#!/usr/bin/env python3
"""Automazione "Scadenze": ogni giorno legge la riga Scadenza delle issue aperte
e, il giorno prima della scadenza, commenta la issue menzionando gli assegnatari
(una sola volta per scadenza). La scadenza di una issue è indicativa: quelle che
contano sono le scadenze degli sprint. Le issue senza milestone (avvisi delle
automazioni) e le pull request sono escluse.
"""
from __future__ import annotations

import datetime as dt
import sys

import comune as c


def principale() -> int:
    oggi = c.oggi()
    domani = oggi + dt.timedelta(days=1)
    righe = []
    for issue in c.pagine(f"/repos/{c.REPO}/issues?state=open"):
        if "pull_request" in issue or not issue.get("milestone"):
            continue
        n = issue["number"]
        scade = c.scadenza(issue.get("body"))
        if scade is None:
            righe.append(f"- #{n}: manca la riga Scadenza nella descrizione")
            continue
        if scade == domani:
            segno = f"<!-- promemoria-scadenza {scade} -->"
            commenti = c.pagine(f"/repos/{c.REPO}/issues/{n}/comments")
            if not any(segno in (k.get("body") or "") for k in commenti):
                chi = " ".join(f"@{a['login']}" for a in issue["assignees"]) or "nessun assegnatario"
                c.richiesta("POST", f"/repos/{c.REPO}/issues/{n}/comments", {
                    "body": f"{segno}\nPromemoria: questa issue scade domani, {scade}. {chi}"})
                righe.append(f"- #{n}: promemoria della scadenza di domani")
    c.riepilogo(f"### Scadenze del {oggi}\n" + ("\n".join(righe) if righe else "Nessuna modifica."))
    return 0


if __name__ == "__main__":
    sys.exit(principale())
