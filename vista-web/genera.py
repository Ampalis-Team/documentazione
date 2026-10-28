#!/usr/bin/env python3
"""Genera la vista web della documentazione di Ampalis Team.

Legge vista-web/documenti.toml e scrive nella cartella di uscita (predefinita:
_site) la pagina index.html con i documenti il cui PDF è nel repository, più
una copia dei PDF e del logo.

Uso (dalla radice del repository):
- python3 vista-web/genera.py: genera la pagina (fatto in automatico ad ogni merga dalla CI su main)
- python3 vista-web/genera.py --controlla: controlla elenco, nomi dei file e PDF non elencati, senza generare

Opzioni: --uscita CARTELLA

Requisiti: Python 3.11 o successivo, senza librerie esterne.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import shutil
import string
import sys
import tomllib
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
ELENCO = RADICE / "vista-web" / "documenti.toml"
MODELLO = RADICE / "vista-web" / "modello.html"
CARTELLE = {"esterno": "documentazione-esterna", "interno": "documentazione-interna"}
ETICHETTE = {"esterno": ("Documentazione esterna", "Verbali esterni"),
             "interno": ("Documentazione interna", "Verbali interni")}

TIPI = ("lettera", "documento", "verbale", "diario")
USI = ("esterno", "interno")
CON_DATA = ("lettera", "verbale", "diario")
CON_VERSIONE = ("documento", "verbale")
RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_VERSIONE = re.compile(r"^\d+\.\d+\.\d+$")
RE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RE_NOME = re.compile(r"^(?:(\d{8})_)?[a-z0-9]+(?:-[a-z0-9]+)*\.pdf$")


class Errore(Exception):
    """Errore che interrompe la generazione, con un messaggio leggibile nel log."""

# Elenco dei documenti
def carica_elenco() -> dict:
    try:
        with ELENCO.open("rb") as f:
            dati = tomllib.load(f)
    except FileNotFoundError:
        raise Errore(f"elenco non trovato: {ELENCO.relative_to(RADICE)}")
    except tomllib.TOMLDecodeError as err:
        raise Errore(f"{ELENCO.name}: sintassi non valida ({err})")

    sito = dati.get("sito")
    if not isinstance(sito, dict):
        raise Errore("manca la sezione [sito]")
    for chiave in ("nome", "gruppo", "corso", "email", "repository", "logo",
                   "sottotitolo", "presentazione", "componenti"):
        if chiave not in sito:
            raise Errore(f'[sito]: manca la chiave "{chiave}"')
    if not (RADICE / sito["logo"]).is_file():
        raise Errore(f"[sito]: logo non trovato ({sito['logo']})")

    visti_id: set[str] = set()
    visti_file: set[str] = set()
    for c in dati.setdefault("consegne", []):
        for chiave in ("id", "titolo", "data"):
            if chiave not in c:
                raise Errore(f'consegna "{c.get("titolo", "?")}": manca la chiave "{chiave}"')
        if not RE_ID.match(c["id"]):
            raise Errore(f'consegna "{c["id"]}": l\'id usa solo minuscole, cifre e trattini')
        if c["id"] in visti_id:
            raise Errore(f'consegna "{c["id"]}": id ripetuto')
        visti_id.add(c["id"])
        if not RE_DATA.match(c["data"]):
            raise Errore(f'consegna "{c["id"]}": data non nel formato AAAA-MM-GG')
        documenti = c.setdefault("documenti", [])
        for d in documenti:
            controlla_voce(c, d)
            if d["file"] in visti_file:
                raise Errore(f'{d["file"]}: elencato più di una volta')
            visti_file.add(d["file"])
        if sum(d["tipo"] == "lettera" for d in documenti) > 1:
            raise Errore(f'consegna "{c["id"]}": più di una Lettera di Presentazione')
    return dati


def controlla_voce(c: dict, d: dict) -> None:
    dove = f'consegna "{c["id"]}", "{d.get("titolo", "?")}"'
    for chiave in ("titolo", "tipo", "file"):
        if chiave not in d:
            raise Errore(f'{dove}: manca la chiave "{chiave}"')
    if d["tipo"] not in TIPI:
        raise Errore(f'{dove}: "tipo" deve essere uno tra {", ".join(TIPI)}')
    if d["tipo"] in ("lettera", "diario"):
        d.setdefault("uso", "esterno")
    if d.get("uso") not in USI:
        raise Errore(f'{dove}: "uso" deve essere esterno o interno')
    if d["tipo"] in CON_DATA and "data" not in d:
        raise Errore(f'{dove}: lettera, verbali e diari richiedono "data"')
    if "data" in d and not RE_DATA.match(d["data"]):
        raise Errore(f"{dove}: data non nel formato AAAA-MM-GG")
    if d["tipo"] in CON_VERSIONE and "versione" not in d:
        raise Errore(f'{dove}: documenti e verbali richiedono "versione"')
    if d["tipo"] not in CON_VERSIONE and "versione" in d:
        raise Errore(f"{dove}: la lettera e il diario di bordo non hanno versione")
    if "versione" in d and not RE_VERSIONE.match(d["versione"]):
        raise Errore(f"{dove}: versione non nel formato X.Y.Z")


def problemi_nome(d: dict) -> list[str]:
    """Controlla cartella e nome del file secondo le regole del Way of Working."""
    problemi = []
    percorso = Path(d["file"])
    cartella = CARTELLE[d["uso"]]
    if percorso.parts[0] != cartella:
        problemi.append(f'{d["file"]}: un documento a uso {d["uso"]} va in {cartella}/')
    m = RE_NOME.match(percorso.name)
    if not m:
        problemi.append(f"{d['file']}: nome in minuscolo con parole separate da trattini, "
                        "eventuale data AAAAMMGG in testa seguita da un trattino basso")
    elif "data" in d and m.group(1) != d["data"].replace("-", ""):
        problemi.append(f"{d['file']}: il nome deve iniziare con la data {d['data'].replace('-', '')}_")
    return problemi


def pdf_non_elencati(dati: dict) -> list[str]:
    elencati = {d["file"] for c in dati["consegne"] for d in c["documenti"]}
    trovati = []
    for cartella in CARTELLE.values():
        for pdf in sorted((RADICE / cartella).rglob("*.pdf")):
            relativo = pdf.relative_to(RADICE).as_posix()
            if relativo not in elencati:
                trovati.append(relativo)
    return trovati


# Pagina
def e(testo) -> str:
    return html.escape(str(testo), quote=True)


def titolo_html(d: dict) -> str:
    # I nomi dei documenti vanno in corsivo; i verbali e il diario no.
    if d["tipo"] in ("documento", "lettera"):
        return f"<em>{e(d['titolo'])}</em>"
    return e(d["titolo"])


def collegamento(d: dict, contenuto: str, etichetta: str, classe: str = "") -> str:
    attributo_classe = f' class="{classe}"' if classe else ""
    return (f'<a{attributo_classe} href="{e(d["file"])}" target="_blank" rel="noopener" '
            f'aria-label="{e(etichetta)} (PDF, si apre in una nuova scheda)">{contenuto}</a>')


def riga(d: dict) -> str:
    data = (f'<time class="doc-data" datetime="{e(d["data"])}">{e(d["data"])}</time>'
            if d["tipo"] in ("verbale", "diario") else "")
    versione = f'<span class="doc-meta">v{e(d["versione"])}</span>' if "versione" in d else ""
    etichetta = d["titolo"]
    if "data" in d:
        etichetta += f' del {d["data"]}'
    if "versione" in d:
        etichetta += f', versione {d["versione"]}'
    contenuto = (f'{data}<span class="doc-titolo">{titolo_html(d)}</span>{versione}'
                 '<span class="doc-freccia" aria-hidden="true">↗</span>')
    return f"<li>{collegamento(d, contenuto, etichetta)}</li>"


def elenco_html(titolo: str, voci: list[dict]) -> str:
    if not voci:
        return ""
    return f"<h4>{e(titolo)}</h4><ul class=\"documenti\">" + "".join(riga(d) for d in voci) + "</ul>"


def blocco(uso: str, documenti: list[dict]) -> str:
    del_uso = [d for d in documenti if d["uso"] == uso and d["tipo"] != "lettera"]
    piu_recenti = lambda tipo: sorted((d for d in del_uso if d["tipo"] == tipo),
                                      key=lambda d: (d["data"], d["titolo"]), reverse=True)
    titolo_blocco, titolo_verbali = ETICHETTE[uso]
    parti = [f'<section class="blocco"><h3>{titolo_blocco}</h3>']
    if not del_uso:
        parti.append('<p class="vuoto">Nessun documento.</p>')
    parti.append(elenco_html("Documenti", [d for d in del_uso if d["tipo"] == "documento"]))
    parti.append(elenco_html(titolo_verbali, piu_recenti("verbale")))
    parti.append(elenco_html("Diari di bordo", piu_recenti("diario")))
    parti.append("</section>")
    return "".join(parti)


def sezione(c: dict, documenti: list[dict]) -> str:
    parti = [f'<section class="consegna" id="{e(c["id"])}" aria-labelledby="titolo-{e(c["id"])}">',
             '<div class="consegna-testata">'
             f'<h2 id="titolo-{e(c["id"])}">{e(c["titolo"])}</h2>'
             f'<time datetime="{e(c["data"])}">{e(c["data"])}</time></div>']
    lettera = next((d for d in documenti if d["tipo"] == "lettera"), None)
    if lettera:
        contenuto = ('<span><span class="lettera-etichetta">Da leggere per prima</span>'
                     f'<span class="lettera-titolo">{titolo_html(lettera)}</span>'
                     f'<span class="lettera-meta"><time datetime="{e(lettera["data"])}">'
                     f'{e(lettera["data"])}</time> · PDF</span></span>'
                     '<span class="lettera-freccia" aria-hidden="true">↗</span>')
        parti.append(collegamento(lettera, contenuto, f'{lettera["titolo"]} del {lettera["data"]}', "lettera"))
    parti.append('<div class="blocchi">' + blocco("esterno", documenti) + blocco("interno", documenti) + "</div>")
    parti.append("</section>")
    return "\n".join(parti)


def oggi() -> str:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
    except Exception:
        return dt.date.today().isoformat()


# Logica centrale
def main() -> int:
    ap = argparse.ArgumentParser(description="Genera la vista web della documentazione.")
    ap.add_argument("--uscita", default="_site", help="cartella di uscita (predefinita: _site)")
    ap.add_argument("--controlla", action="store_true",
                    help="controlla elenco, nomi dei file e PDF non elencati, senza generare")
    args = ap.parse_args()

    try:
        dati = carica_elenco()
    except Errore as err:
        print(f"ERRORE: {err}", file=sys.stderr)
        return 1

    sito = dati["sito"]
    consegne = sorted(dati["consegne"], key=lambda c: c["data"], reverse=True)
    tutti = [d for c in consegne for d in c["documenti"]]
    in_attesa = [d for d in tutti if not (RADICE / d["file"]).is_file()]
    problemi = [p for d in tutti for p in problemi_nome(d)]
    problemi += [f"{f}: PDF non elencato in vista-web/documenti.toml" for f in pdf_non_elencati(dati)]

    for d in in_attesa:
        print(f"in attesa  {d['file']} (compare quando il PDF è su main)")

    if args.controlla:
        for p in problemi:
            print(f"ERRORE {p}", file=sys.stderr)
        presenti = len(tutti) - len(in_attesa)
        print(f"Controllo completato: {presenti} documenti presenti, {len(in_attesa)} in attesa, "
              f"{len(problemi)} errori.")
        return 1 if problemi else 0

    # Su main gli errori di nome non fermano la pubblicazione: li segnala il controllo sulla pull request.
    for p in problemi:
        print(f"AVVISO {p}", file=sys.stderr)

    uscita = Path(args.uscita)
    if not uscita.is_absolute():
        uscita = RADICE / uscita
    if uscita.exists():
        shutil.rmtree(uscita)
    uscita.mkdir(parents=True)

    sezioni: list[str] = []
    pubblicati = 0
    for c in consegne:
        presenti = [d for d in c["documenti"] if d not in in_attesa]
        for d in presenti:
            destinazione = uscita / d["file"]
            destinazione.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RADICE / d["file"], destinazione)
        pubblicati += len(presenti)
        if presenti:
            sezioni.append(sezione(c, presenti))
    if not sezioni:
        sezioni.append('<p class="nessuno">Nessun documento ancora pubblicato.</p>')

    logo = "logo" + Path(sito["logo"]).suffix.lower()
    shutil.copyfile(RADICE / sito["logo"], uscita / logo)

    sha = os.environ.get("GITHUB_SHA", "")[:7]
    versione_sito = (f' dal <a href="{e(sito["repository"])}/commit/{e(sha)}">commit {e(sha)}</a>'
                     if sha else "")
    componenti = "\n".join(f"      <li>{e(n)}</li>" for n in sito["componenti"])

    pagina = string.Template(MODELLO.read_text(encoding="utf-8")).substitute(
        nome=e(sito["nome"]),
        gruppo=e(sito["gruppo"]),
        corso=e(sito["corso"]),
        sottotitolo=e(sito["sottotitolo"]),
        presentazione=e(" ".join(sito["presentazione"].split())),
        componenti=componenti,
        email=e(sito["email"]),
        repository=e(sito["repository"]),
        logo=logo,
        consegne="\n".join(sezioni),
        data_generazione=oggi(),
        versione_sito=versione_sito,
    )
    (uscita / "index.html").write_text(pagina, encoding="utf-8")

    dove = uscita.relative_to(RADICE) if uscita.is_relative_to(RADICE) else uscita
    print(f"Vista web in {dove}: {pubblicati} documenti pubblicati, {len(in_attesa)} in attesa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
