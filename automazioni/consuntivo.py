#!/usr/bin/env python3
"""Automazione "Consuntivo delle ore" (Norme di Progetto, paragrafo sul
rendiconto delle ore), dallo Sprint 2.

Legge dalla Project Board le issue dello sprint e i campi Ore effettive e Ore di
verifica; confronta le ore produttive con quelle previste (automazioni/ruoli.toml,
chiave previste, dal Piano di Progetto); ricava il ruolo dal campo Ruolo (se diverso) della issue, se compilato, altrimenti
da persona e sprint (automazioni/ruoli.toml), e le ore di riunione dai verbali del
repository. Scrive in consuntivo/:
- consuntivo.csv: una riga per sprint, componente e ruolo;
- consuntivo-sprint-N.tex: tabella per il consuntivo del Piano di Progetto.
Formazione e altro vengono dal foglio Google Sheets, pubblicato come CSV
(variabile FOGLIO_ORE_CSV); le ore di riunione dai verbali, contando solo chi è
nella lista dei partecipanti del gruppo.

Ore effettive: dell'assegnatario della issue (una issue con ore ha un solo
assegnatario). Ore di verifica: dei componenti scelti nel campo Verificatori,
se compilato (verifica divisa in parti uguali); altrimenti dei componenti che hanno
approvato la pull request che ha chiuso la issue, divise in parti uguali se sono
più di uno. Le ore di verifica contano sempre come lavoro da Verificatore, chiunque
le svolga; le ore effettive con il ruolo del campo Ruolo (se diverso), compilato quando un
componente svolge una issue in un ruolo diverso dal suo, altrimenti con il ruolo
della matrice. L'aggiornamento del Piano di Progetto conta come lavoro da Responsabile.
Le issue madri (con sotto-issue) e le issue chiuse come non pianificate non hanno
ore: non si segnalano come incomplete, ma le ore scritte si contano.

Se a una issue chiusa dello sprint mancano dei dati, il consuntivo si calcola lo
stesso, il riepilogo elenca le issue incomplete e l'esecuzione termina con un
errore; la issue di avviso "Riempire dati riguardanti ore produttive mancanti,
necessarie per il consuntivo (AAAA-MM-GG)", con la data di apertura, si apre o si
aggiorna, e si chiude da sola alla prima esecuzione completa.
Variabili: PROJECT_TOKEN (dalla GitHub App), GITHUB_TOKEN, PROGETTO_NUMERO; SPRINT per scegliere
lo sprint (predefinito: quello di ieri, cioè lo sprint appena concluso il lunedì).
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import os
import re
import sys
import urllib.request
from collections import defaultdict

import comune as c

TITOLO_AVVISO = "Riempire dati riguardanti ore produttive mancanti, necessarie per il consuntivo"
TITOLO_AVVISO_FOGLIO = "Correggere il foglio delle ore di orologio, necessario per il consuntivo"
TITOLO_PIANO = "Aggiornare il Piano di Progetto"
CAMPO_RUOLO = "Ruolo (se diverso)"  # campo a scelta della Project Board
USCITA = c.RADICE / "consuntivo"
RE_ORA = re.compile(r"\bOra (\d{1,2})[:.](\d{2}) ?[–-] ?(\d{1,2})[:.](\d{2})")
FINE_PARTECIPANTI = ("Assenti", "Responsabile", "Redattore", "Partecipanti", "Conferma", "Ordine del giorno")
RE_ORARIO = re.compile(r"(\d{1,2})[:.](\d{2})")

QUERY = """query($org:String!,$n:Int!,$dopo:String){organization(login:$org){projectV2(number:$n){
 items(first:100,after:$dopo){pageInfo{hasNextPage endCursor} nodes{
  fieldValues(first:30){nodes{  ... on ProjectV2ItemFieldNumberValue{number field{... on ProjectV2Field{name}}}
  ... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2SingleSelectField{name}}}
  ... on ProjectV2ItemFieldMultiSelectValue{options{id name} field{... on ProjectV2Field{name}}}}}
  content{... on Issue{number title state stateReason url milestone{title} assignees(first:5){nodes{login}}
   subIssues(first:1){totalCount}
   timelineItems(itemTypes:[CLOSED_EVENT],last:1){nodes{... on ClosedEvent{closer{
    ... on PullRequest{number reviews(states:APPROVED,first:10){nodes{author{login}}}}}}}}}}}}}}}"""


def elementi() -> list[dict]:
    org, n = c.REPO.split("/")[0], int(os.environ["PROGETTO_NUMERO"])
    tutti, dopo = [], None
    while True:
        dati = c.graphql(QUERY, {"org": org, "n": n, "dopo": dopo})["organization"]["projectV2"]["items"]
        for nodo in dati["nodes"]:
            issue = nodo.get("content") or {}
            if "number" not in issue:
                continue                           # pull request o bozza
            campi = {v["field"]["name"]: v["number"] for v in nodo["fieldValues"]["nodes"] if v and "number" in v}
            scelte = {v["field"]["name"]: v["name"] for v in nodo["fieldValues"]["nodes"]
                      if v and "name" in v and v.get("field")}
            multi = {v["field"]["name"]: [o["name"] for o in v.get("options", [])]
                     for v in nodo["fieldValues"]["nodes"]
                     if v and "options" in v and v.get("field")}
            chiusura = issue["timelineItems"]["nodes"]
            closer = (chiusura[0].get("closer") or {}) if chiusura else {}
            tutti.append({
                "numero": issue["number"], "titolo": issue["title"], "stato": issue["state"],
                "senza_ore": issue.get("stateReason") == "NOT_PLANNED"
                             or bool((issue.get("subIssues") or {}).get("totalCount")),
                "verificatori_campo": (multi.get("Verificatori")
                                       or ([scelte["Verificatore"]] if scelte.get("Verificatore") else [])),
                "ruolo": scelte.get(CAMPO_RUOLO),
                "milestone": (issue.get("milestone") or {}).get("title"),
                "assegnatari": [a["login"] for a in issue["assignees"]["nodes"]],
                "verificatori": sorted({r["author"]["login"] for r in (closer.get("reviews") or {}).get("nodes", [])
                                        if r.get("author")}),
                "pull_request": closer.get("number"),
                "effettive": campi.get("Ore effettive"),
                "verifica": campi.get("Ore di verifica"),
            })
        if not dati["pageInfo"]["hasNextPage"]:
            return tutti
        dopo = dati["pageInfo"]["endCursor"]


def minuti(h: str, m: str) -> int:
    return int(h) * 60 + int(m)


def presenze(testo: str, ruoli: dict) -> list[tuple[str, int | None, int | None]]:
    """Componenti presenti secondo il campo Partecipanti del verbale: nei verbali
    esterni conta solo la lista "Partecipanti Ampalis Team", non i campi
    Responsabile e Redattore. Chi è presente solo in parte si scrive con l'orario
    tra parentesi, per esempio "Mario Rossi (dalle 17:00)", "(fino alle 18:00)" o
    "(dalle 16:30 alle 18:00)": restituisce nome, inizio e fine in minuti (None se
    coincidono con quelli della riunione)."""
    chiave = "Partecipanti Ampalis Team"
    inizio = testo.find(chiave)
    inizio = inizio + len(chiave) if inizio >= 0 else testo.find("Partecipanti") + len("Partecipanti")
    if inizio < len("Partecipanti"):
        return []
    fine = min([i for i in (testo.find(k, inizio) for k in FINE_PARTECIPANTI) if i >= 0] or [len(testo)])
    lista = testo[inizio:fine]
    risultato = []
    for nome in ruoli["componenti"]:
        i = lista.find(nome)
        if i < 0:
            continue
        dopo = lista[i + len(nome):].lstrip()
        da = a = None
        if dopo.startswith("("):
            parentesi = dopo[1:dopo.find(")")] if ")" in dopo else ""
            orari = RE_ORARIO.findall(parentesi)
            if "dalle" in parentesi and orari:
                da = minuti(*orari[0])
                if len(orari) > 1:
                    a = minuti(*orari[1])
            elif "alle" in parentesi and orari:
                a = minuti(*orari[0])
        risultato.append((nome, da, a))
    return risultato


def ore_riunioni(ruoli: dict, sprint: dict) -> tuple[dict[str, float], list[str]]:
    """Ore di riunioni e incontri per componente, dai verbali dello sprint, e
    righe di riepilogo (verbale, durata, presenti)."""
    spec = importlib.util.spec_from_file_location("genera", c.RADICE / "vista-web" / "genera.py")
    genera = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(genera)
    ore, righe = defaultdict(float), []
    inizio, fine = c.data(sprint["inizio"]), c.data(sprint["fine"])
    for pdf in sorted(c.RADICE.glob("documentazione-*/verbali-*/*_verbale-*.pdf")):
        giorno = dt.date(int(pdf.name[:4]), int(pdf.name[4:6]), int(pdf.name[6:8]))
        if not inizio <= giorno <= fine:
            continue
        testo = " ".join(" ".join(genera.leggi_pdf(pdf)[0][:4]).split())
        m = RE_ORA.search(testo)
        if not m:
            righe.append(f"| {pdf.name} | orario non trovato | |")
            continue
        h1, m1, h2, m2 = m.groups()
        t1, t2 = minuti(h1, m1), minuti(h2, m2)
        presenti = presenze(testo, ruoli)
        nomi = []
        for nome, da, a in presenti:
            durata = ((a or t2) - (da or t1)) / 60
            ore[nome] += max(durata, 0)
            nomi.append(nome if da is None and a is None else f"{nome} ({durata:.2f} h)".replace(".", ","))
        durata_riunione = f"{(t2 - t1) / 60:.2f}".replace(".", ",")
        righe.append(f"| {pdf.name} | {durata_riunione} h | {', '.join(nomi) or 'nessuno'} |")
    return ore, righe


def ore_foglio(ruoli: dict, sprint: dict) -> tuple[dict[str, tuple[float, float]], list[str]]:
    """Formazione e altro per componente dal foglio Google Sheets, pubblicato come
    CSV (File, Condividi, Pubblica sul web, scheda delle ore, formato CSV).
    L'indirizzo è nella variabile del repository FOGLIO_ORE_CSV. Il foglio ha una
    riga per componente e per sprint, con le colonne Sprint, Componente,
    Formazione e Altro; le altre colonne si ignorano."""
    url = os.environ.get("FOGLIO_ORE_CSV", "")
    if not url:
        return {}, ["manca la variabile del repository FOGLIO_ORE_CSV con l'indirizzo del foglio pubblicato: formazione e altro non sono stati letti"]
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            testo = r.read().decode("utf-8-sig")
    except OSError as e:
        return {}, [f"il foglio pubblicato non si raggiunge ({e}): controllate che sia ancora pubblicato e che l'indirizzo in FOGLIO_ORE_CSV sia giusto"]
    righe = list(csv.reader(testo.splitlines()))
    intestazione = next((i for i, r in enumerate(righe)
                         if {"Sprint", "Componente", "Formazione", "Altro"} <= {x.strip() for x in r}), None)
    if intestazione is None:
        return {}, ["nel foglio pubblicato manca la riga d'intestazione con le colonne Sprint, Componente, Formazione e Altro"]
    col = {x.strip(): i for i, x in enumerate(righe[intestazione])}

    def numero(x: str) -> float:
        x = x.strip().replace(".", "").replace(",", ".") if "," in x else x.strip()
        return float(x) if x else 0.0

    ore, problemi = defaultdict(lambda: [0.0, 0.0]), []
    for r in righe[intestazione + 1:]:
        if len(r) <= max(col.values()) or r[col["Sprint"]].strip() != str(sprint["numero"]):
            continue
        nome = r[col["Componente"]].strip()
        if nome not in ruoli["componenti"]:
            problemi.append(f"riga dello Sprint {sprint['numero']} con il componente \"{nome}\", che non corrisponde a nessun nome di automazioni/ruoli.toml: va scelto dal menu a tendina")
            continue
        try:
            ore[nome][0] += numero(r[col["Formazione"]])
            ore[nome][1] += numero(r[col["Altro"]])
        except ValueError:
            problemi.append(f"riga dello Sprint {sprint['numero']} di {nome}: Formazione o Altro non è un numero")
    return {n: tuple(v) for n, v in ore.items()}, problemi


SIGLE = {esteso: sigla for sigla, esteso in c.RUOLI_ESTESI.items()}   # "Analista" -> "An"
VERIFICA = "Ve"                       # le ore di verifica sono sempre da Verificatore


def calcola(ruoli: dict, sprint: dict, voci: list[dict]) -> tuple[dict, list[str]]:
    """Ore per (componente, ruolo) e problemi trovati."""
    numero = sprint["numero"]
    tot = defaultdict(lambda: {"produttive": 0.0})
    problemi = []
    for v in voci:
        if v["milestone"] != f"Sprint {numero}":
            continue
        ruolo_forzato = "Re" if v["titolo"].startswith(TITOLO_PIANO) else None
        if len(v["assegnatari"]) != 1:
            if v["stato"] == "CLOSED" and not v["senza_ore"]:
                problemi.append(f"#{v['numero']}: {len(v['assegnatari'])} assegnatari; una issue con ore ne ha uno solo")
            continue
        nome = c.nome_di(ruoli, v["assegnatari"][0])
        if not nome:
            problemi.append(f"#{v['numero']}: {v['assegnatari'][0]} non è in automazioni/ruoli.toml")
            continue
        ruolo_scelto = SIGLE.get(v.get("ruolo") or "")
        if v.get("ruolo") and not ruolo_scelto:
            problemi.append(f"#{v['numero']}: il campo {CAMPO_RUOLO} vale {v['ruolo']}, che non è un ruolo")
        ruolo = ruolo_forzato or ruolo_scelto or sprint["ruoli"][nome]
        if v["stato"] != "CLOSED":
            continue
        if v["effettive"] is None:
            if not v["senza_ore"]:
                problemi.append(f"#{v['numero']} *{v['titolo']}*: mancano le Ore effettive (@{v['assegnatari'][0]})")
        else:
            tot[(nome, ruolo)]["produttive"] += v["effettive"]
        if v["verificatori_campo"]:              # verifica divisa in parti uguali tra i verificatori selezionati
            validi = []
            for verificatore in v["verificatori_campo"]:
                if verificatore not in sprint["ruoli"]:
                    problemi.append(f"#{v['numero']}: Verificatori contiene {verificatore}, che non è in automazioni/ruoli.toml")
                else:
                    validi.append(verificatore)
            if v["verifica"] is None:
                if not v["senza_ore"] and validi:
                    problemi.append(f"#{v['numero']} *{v['titolo']}*: mancano le Ore di verifica ({', '.join(validi)})")
            else:
                for verificatore in validi:
                    tot[(verificatore, VERIFICA)]["produttive"] += v["verifica"] / len(validi)
        elif v["verificatori"]:
            if v["verifica"] is None:
                if not v["senza_ore"]:
                    chi = " ".join(f"@{u}" for u in v["verificatori"])
                    problemi.append(f"#{v['numero']} *{v['titolo']}*: mancano le Ore di verifica ({chi})")
            else:
                for u in v["verificatori"]:
                    vn = c.nome_di(ruoli, u)
                    if vn:
                        tot[(vn, VERIFICA)]["produttive"] += v["verifica"] / len(v["verificatori"])
    return tot, problemi


def scrivi(ruoli: dict, sprint: dict, tot: dict, riunioni: dict, foglio: dict) -> list[list]:
    USCITA.mkdir(exist_ok=True)
    righe = []
    for nome in ruoli["componenti"]:
        previste = sprint.get("previste", {}).get(nome, {})
        chiavi = list({k for k in tot if k[0] == nome} | {(nome, sprint["ruoli"][nome])}
                      | {(nome, r) for r in previste})
        for i, (n, ruolo) in enumerate(sorted(chiavi, key=lambda k: k[1] != sprint["ruoli"][nome])):
            t = tot.get((n, ruolo), {"produttive": 0})
            costo = t["produttive"] * ruoli["costi"][ruolo]
            riun = riunioni.get(n, 0) if i == 0 else 0
            form, altro = foglio.get(n, (0, 0)) if i == 0 else (0, 0)
            righe.append([sprint["numero"], n, c.RUOLI_ESTESI[ruolo], round(previste.get(ruolo, 0), 2),
                          round(t["produttive"], 2), round(costo, 2), round(riun, 2), round(form, 2),
                          round(altro, 2), round(t["produttive"] + riun + form + altro, 2)])
    with open(USCITA / "consuntivo.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sprint", "componente", "ruolo", "ore_previste", "ore_produttive", "costo_euro",
                    "riunioni", "formazione", "altro", "ore_di_orologio"])
        w.writerows(righe)

    def num(x: float) -> str:
        return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",") if x else "0"

    def euro(x: float) -> str:
        return f"{x:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    tex = [r"% Generato da automazioni/consuntivo.py: non modificare a mano",
           r"\begin{tabular}{L{3cm} L{2.3cm} r r r r r r r}", r"\toprule",
           r"\intestazione{Componente} & \intestazione{Ruolo} & \intestazione{Previste} & "
           r"\intestazione{Prod.} & \intestazione{Costo} & \intestazione{Riun.} & "
           r"\intestazione{Form.} & \intestazione{Altro} & \intestazione{Orologio} \\", r"\midrule"]
    for _, n, ruolo, prev, ore, costo, riun, form, altro, orol in righe:
        tex.append(rf"{n} & {ruolo} & {num(prev)} & {num(ore)} & \euro{{{euro(costo)}}} & "
                   rf"{num(riun)} & {num(form)} & {num(altro)} & {num(orol)} \\")
    somma = [sum(r[k] for r in righe) for k in range(3, 10)]
    tex += [r"\midrule",
            rf"Totale & & {num(somma[0])} & {num(somma[1])} & \euro{{{euro(somma[2])}}} & {num(somma[3])} & "
            rf"{num(somma[4])} & {num(somma[5])} & {num(somma[6])} \\",
            r"\bottomrule", r"\end{tabular}"]
    (USCITA / f"consuntivo-sprint-{sprint['numero']}.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
    return righe


def avviso(titolo: str, introduzione: str, problemi: list[str], ruoli: dict, sprint: dict) -> None:
    """Apre o aggiorna la issue di avviso con il titolo dato (più la data di
    apertura), oppure la chiude quando i problemi sono risolti."""
    aperte = [i for i in c.pagine(f"/repos/{c.REPO}/issues?state=open&labels=infrastructure")
              if i["title"].startswith(titolo) and "pull_request" not in i]
    amm = c.utente_di(ruoli, next(n for n, r in sprint["ruoli"].items() if r == "Am"))
    if problemi:
        corpo = (f"{introduzione} Dopo la correzione rieseguite l'automazione (Actions, *Consuntivo delle ore*, "
                 f"Run workflow, oppure Re-run jobs sull'ultima esecuzione). @{amm}\n\n"
                 + "\n".join(f"- {p}" for p in problemi))
        if aperte:
            c.richiesta("PATCH", f"/repos/{c.REPO}/issues/{aperte[0]['number']}", {"body": corpo})
        else:
            c.richiesta("POST", f"/repos/{c.REPO}/issues", {"title": f"{titolo} ({c.oggi()})", "body": corpo,
                                                          "labels": ["infrastructure"]})
    else:
        for i in aperte:
            c.richiesta("POST", f"/repos/{c.REPO}/issues/{i['number']}/comments",
                        {"body": "Dati completi: consuntivo calcolato."})
            c.richiesta("PATCH", f"/repos/{c.REPO}/issues/{i['number']}", {"state": "closed"})


def principale() -> int:
    if not os.environ.get("PROJECT_TOKEN") or not os.environ.get("PROGETTO_NUMERO"):
        c.riepilogo("Manca il token della GitHub App (variabile APP_CLIENT_ID e secret "
                    "APP_PRIVATE_KEY) o la variabile PROGETTO_NUMERO: automazione non ancora "
                    "configurata (automazioni/README.md).")
        return 0
    ruoli = c.carica_ruoli()
    if os.environ.get("SPRINT"):
        sprint = c.sprint_numero(ruoli, int(os.environ["SPRINT"]))
    else:
        sprint = c.sprint_del_giorno(ruoli, c.oggi() - dt.timedelta(days=1))
    if not sprint:
        c.riepilogo("Nessuno sprint da consuntivare.")
        return 0
    tot, problemi = calcola(ruoli, sprint, elementi())
    riunioni, verbali = ore_riunioni(ruoli, sprint)
    foglio, problemi_foglio = ore_foglio(ruoli, sprint)
    righe = scrivi(ruoli, sprint, tot, riunioni, foglio)
    tabella = ["| Componente | Ruolo | Previste | Produttive | Costo (€) | Riunioni | Formazione | Altro | Orologio |",
               "|---|---|---|---|---|---|---|---|---|"]
    tabella += [f"| {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]:.2f} | {r[6]} | {r[7]} | {r[8]} | {r[9]} |" for r in righe]
    c.riepilogo(f"### Consuntivo dello Sprint {sprint['numero']} ({sprint['inizio']} - {sprint['fine']})\n\n"
                + "\n".join(tabella)
                + "\n\n#### Riunioni e incontri, dai verbali\n\n| Verbale | Durata | Presenti |\n|---|---|---|\n"
                + "\n".join(verbali))
    if not os.environ.get("PROVA"):
        avviso(TITOLO_AVVISO,
               f"Consuntivo dello Sprint {sprint['numero']}: nella Project Board mancano dei campi delle ore "
               "produttive. Ognuno compila i campi delle issue in cui è menzionato.", problemi, ruoli, sprint)
        avviso(TITOLO_AVVISO_FOGLIO,
               f"Consuntivo dello Sprint {sprint['numero']}: il foglio delle ore di orologio ha dei problemi, "
               "quindi formazione e altro delle righe indicate non sono entrati nel consuntivo.",
               problemi_foglio, ruoli, sprint)
    return c.esci(problemi + problemi_foglio, "Dati mancanti")


if __name__ == "__main__":
    sys.exit(principale())
