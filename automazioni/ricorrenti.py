#!/usr/bin/env python3
"""Automazione "Issue ricorrenti".

Ogni domenica (alle 20:00) crea, per il lunedì dopo,
- la issue del diario di bordo, solo se la data è in automazioni/calendario-diari.toml,
  assegnata al Responsabile dello sprint di quel giorno;
- nell'ultima settimana di ogni sprint, cioè quando lo sprint successivo comincia entro
  sette giorni dal lunedì, la issue dell'aggiornamento del Piano di Progetto, assegnata
  al Responsabile uscente, con la versione successiva a quella del PDF pubblicato e la
  scadenza al primo giorno del nuovo sprint. Va nella milestone del nuovo sprint; se la
  milestone non esiste ancora, la issue nasce senza e le domeniche seguenti l'automazione
  la aggiunge appena la milestone c'è.
Ogni lunedì (alle 18:00, dopo la riunione) crea la issue del verbale interno della
riunione del giorno, senza assegnatario: il redattore si sceglie in riunione e se la
assegna.
Ogni martedì (alle 20:00) crea, per il mercoledì dopo, la issue del report settimanale
per l'incontro con M31, assegnata al Responsabile dello sprint di quel giorno.
Ogni mercoledì (alle 17:00, dopo l'incontro con M31) crea la issue del verbale esterno
dell'incontro del giorno, senza assegnatario, come quella del verbale interno.
Se l'incontro con M31 cambia giorno o non si tiene, il Responsabile corregge o scarta le
issue del report e del verbale esterno.
Le date degli sprint vengono da automazioni/ruoli.toml: se uno sprint si allunga, basta
aggiornarle lì.
Titoli, descrizione, etichette e milestone seguono le Norme di Progetto. Se una
issue con lo stesso titolo esiste già, non la ricrea.
Con OGGI=AAAA-MM-GG si prova una data diversa; con PROVA=1 non crea nulla.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sys

import comune as c


def milestone(titolo: str) -> int | None:
    for m in c.pagine(f"/repos/{c.REPO}/milestones?state=all"):
        if m["title"] == titolo:
            return m["number"]
    return None


def crea(titolo: str, corpo: str, etichette: list[str], milestone_n: int | None,
         assegnatari: list[str], esistenti: set[str]) -> str:
    if titolo in esistenti:
        return f"- già presente: *{titolo}*"
    if os.environ.get("PROVA"):
        return f"- da creare: *{titolo}* ({corpo.replace(chr(10), '; ')})"
    dati = {"title": titolo, "body": corpo, "labels": etichette, "assignees": assegnatari,
            "type": "Task"}
    if milestone_n:
        dati["milestone"] = milestone_n
    try:
        issue = c.richiesta("POST", f"/repos/{c.REPO}/issues", dati)
    except c.ErroreGitHub:
        dati.pop("type")                     # tipi delle issue non disponibili
        issue = c.richiesta("POST", f"/repos/{c.REPO}/issues", dati)
    return f"- creata #{issue['number']}: *{titolo}*"


def versione_piano() -> str | None:
    """Versione successiva a quella del Piano di Progetto pubblicato: X.Y.Z -> X.(Y+1).0."""
    pdf = c.RADICE / "documentazione-esterna" / "piano-di-progetto.pdf"
    try:
        spec = importlib.util.spec_from_file_location("genera", c.RADICE / "vista-web" / "genera.py")
        genera = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(genera)
        attuale = genera.versione_copertina(genera.leggi_pdf(pdf)[0])
    except Exception:  # noqa: BLE001 - PDF assente o illeggibile: la issue non si crea
        return None
    if not attuale:
        return None
    x, y, _ = (int(n) for n in attuale.split("."))
    return f"{x}.{y + 1}.0"


def piano_di_progetto(ruoli: dict, sprint: dict, lunedi: dt.date, issue: list[dict], titoli: set[str]) -> list[str]:
    """Issue dell'aggiornamento del Piano di Progetto nell'ultima settimana dello sprint."""
    successivo = c.sprint_numero(ruoli, sprint["numero"] + 1)
    if not successivo:
        return []
    inizio = dt.date.fromisoformat(str(successivo["inizio"]))
    righe = []
    m_nuova = milestone(f"Sprint {successivo['numero']}")
    # issue già aperta senza milestone: riceve la milestone dello sprint che comincia alla sua scadenza
    for i in issue:
        if (i["state"] != "open" or i.get("milestone")
                or not i["title"].startswith("Aggiornare il Piano di Progetto alla versione ")):
            continue
        scadenza = c.scadenza(i.get("body") or "")
        destinazione = c.sprint_del_giorno(ruoli, scadenza) if scadenza else None
        m_dest = milestone(f"Sprint {destinazione['numero']}") if destinazione else None
        if not m_dest:
            continue
        if os.environ.get("PROVA"):
            righe.append(f"- da spostare nella milestone Sprint {destinazione['numero']}: #{i['number']}")
        else:
            c.richiesta("PATCH", f"/repos/{c.REPO}/issues/{i['number']}", {"milestone": m_dest})
            righe.append(f"- #{i['number']} spostata nella milestone Sprint {destinazione['numero']}")
    if not 0 <= (inizio - lunedi).days <= 7:
        return righe
    versione = versione_piano()
    if not versione:
        return righe + ["- Piano di Progetto: versione pubblicata non trovata, issue non creata"]
    uscente = c.utente_di(ruoli, c.responsabile(ruoli, sprint))
    titolo = f"Aggiornare il Piano di Progetto alla versione {versione}"
    corpo = (f"Origine: cambio di sprint del {inizio}, retrospettiva dello Sprint {sprint['numero']}\n"
             f"Scadenza: {inizio}")
    righe.append(crea(titolo, corpo, ["documentation"], m_nuova, [uscente], titoli))
    if not m_nuova:
        righe.append(f"  (la milestone Sprint {successivo['numero']} non esiste ancora: la issue la riceve appena c'è)")
    return righe


def contesto(ruoli: dict, giorno: dt.date) -> tuple[dict, int | None, list[dict], set[str]] | None:
    """Sprint e milestone del giorno, issue del repository e loro titoli; None se il giorno
    non cade in nessuno sprint."""
    sprint = c.sprint_del_giorno(ruoli, giorno)
    if not sprint:
        c.riepilogo(f"{giorno} non cade in nessuno sprint di automazioni/ruoli.toml: nessuna issue.")
        return None
    issue = [i for i in c.pagine(f"/repos/{c.REPO}/issues?state=all") if "pull_request" not in i]
    return sprint, milestone(f"Sprint {sprint['numero']}"), issue, {i["title"] for i in issue}


def numero_verbale(cartella: str, tipo: str, inizio_titolo: str, issue: list[dict]) -> int:
    """Numero del prossimo verbale: verbali pubblicati + issue dei verbali ancora aperte + 1."""
    pubblicati = len(list((c.RADICE / cartella).glob(f"*_verbale-{tipo}.pdf")))
    aperti = sum(1 for i in issue if i["state"] == "open" and i["title"].startswith(inizio_titolo))
    return pubblicati + aperti + 1


def domenica(ruoli: dict, lunedi: dt.date) -> int:
    """Domenica: diario di bordo del lunedì, se in calendario, e Piano di Progetto
    nell'ultima settimana dello sprint."""
    dati = contesto(ruoli, lunedi)
    if not dati:
        return 0
    sprint, m, issue, titoli = dati
    righe = []
    if str(lunedi) in c.carica_calendario():
        resp = c.utente_di(ruoli, c.responsabile(ruoli, sprint))
        titolo = f"Creare, presentare e pubblicare il diario di bordo del {lunedi}"
        corpo = f"Origine: calendario delle lezioni, diario di bordo del {lunedi}\nScadenza: {lunedi}"
        righe.append(crea(titolo, corpo, ["documentation"], m, [resp], titoli))
    else:
        righe.append(f"- nessun diario di bordo il {lunedi} (data non presente nel calendario)")
    righe += piano_di_progetto(ruoli, sprint, lunedi, issue, titoli)
    c.riepilogo(f"### Issue ricorrenti per il {lunedi} (Sprint {sprint['numero']})\n" + "\n".join(righe))
    return 0


def verbale_interno(ruoli: dict, lunedi: dt.date) -> int:
    """Lunedì, dopo la riunione: verbale interno, senza assegnatario."""
    dati = contesto(ruoli, lunedi)
    if not dati:
        return 0
    sprint, m, issue, titoli = dati
    n = numero_verbale("documentazione-interna/verbali-interni", "interno", "Scrivere verbale interno del ", issue)
    titolo = f"Scrivere verbale interno del {lunedi}"
    corpo = (f"Origine: riunione interna del {lunedi} (verbale interno VI{n})\n"
             f"Scadenza: {lunedi + dt.timedelta(days=4)}")
    riga = crea(titolo, corpo, ["documentation", "meeting"], m, [], titoli)
    c.riepilogo(f"### Issue ricorrenti per il {lunedi} (Sprint {sprint['numero']})\n{riga}")
    return 0


def report_settimanale(ruoli: dict, mercoledi: dt.date) -> int:
    """Martedì: report settimanale per l'incontro con M31 del mercoledì, al Responsabile."""
    dati = contesto(ruoli, mercoledi)
    if not dati:
        return 0
    sprint, m, _, titoli = dati
    resp = c.utente_di(ruoli, c.responsabile(ruoli, sprint))
    titolo = f"Creare report settimanale per incontro con M31 del {mercoledi}"
    corpo = f"Origine: incontro settimanale con M31 del {mercoledi}\nScadenza: {mercoledi}"
    riga = crea(titolo, corpo, ["documentation", "meeting"], m, [resp], titoli)
    c.riepilogo(f"### Issue ricorrenti per il {mercoledi} (Sprint {sprint['numero']})\n{riga}")
    return 0


def verbale_esterno(ruoli: dict, mercoledi: dt.date) -> int:
    """Mercoledì, dopo l'incontro con M31: verbale esterno, senza assegnatario."""
    dati = contesto(ruoli, mercoledi)
    if not dati:
        return 0
    sprint, m, issue, titoli = dati
    n = numero_verbale("documentazione-esterna/verbali-esterni", "esterno", "Scrivere verbale esterno con ", issue)
    titolo = f"Scrivere verbale esterno con M31 del {mercoledi}"
    corpo = (f"Origine: incontro con M31 del {mercoledi} (verbale esterno VE{n})\n"
             f"Scadenza: {mercoledi + dt.timedelta(days=4)}")
    riga = crea(titolo, corpo, ["documentation", "meeting"], m, [], titoli)
    c.riepilogo(f"### Issue ricorrenti per il {mercoledi} (Sprint {sprint['numero']})\n{riga}")
    return 0


def principale() -> int:
    ruoli = c.carica_ruoli()
    oggi = c.oggi()
    domani = oggi + dt.timedelta(days=1)
    giorni = {6: lambda: domenica(ruoli, domani),
              0: lambda: verbale_interno(ruoli, oggi),
              1: lambda: report_settimanale(ruoli, domani),
              2: lambda: verbale_esterno(ruoli, oggi)}
    if oggi.weekday() not in giorni:
        c.riepilogo(f"{oggi}: le issue ricorrenti si creano solo da domenica a mercoledì, nessuna issue.")
        return 0
    return giorni[oggi.weekday()]()


if __name__ == "__main__":
    sys.exit(principale())
