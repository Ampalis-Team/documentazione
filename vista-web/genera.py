#!/usr/bin/env python3
"""Genera la vista web della documentazione di Ampalis Team.

La pagina si costruisce dai PDF presenti in documentazione-esterna/ e
documentazione-interna/, senza un elenco dei documenti da aggiornare a mano:

- tipo e uso: dalla cartella e dal nome del file;
- data di verbali, diari di bordo e Lettera di Presentazione: dal nome del file
  (AAAAMMGG_...);
- versione: dalla copertina del PDF ("Versione X.Y.Z");
- titolo: per i documenti dai metadati del PDF, che il preambolo comune imposta;
  per i verbali esterni l'azienda si legge tra i destinatari in copertina;
- consegna: verbali, diari e Lettera vanno nella prima consegna con data uguale
  o successiva alla loro; un documento va nella consegna della sua ultima
  approvazione per il rilascio, letta nel registro delle modifiche, oppure, se
  non è mai stato approvato, nella prima consegna dopo la data in copertina.

vista-web/documenti.toml contiene solo i testi della pagina e le consegne.

Uso, dalla radice del repository:
- python3 vista-web/genera.py
    genera la pagina in _site (la CI lo fa dopo ogni merge su main);
- python3 vista-web/genera.py --controlla [--base origin/main]
    controlla i PDF senza generare (la CI lo fa su ogni pull request); con
    --base controlla anche che ogni PDF già presente nel riferimento indicato,
    se modificato, abbia una versione più alta.

Opzioni: --uscita CARTELLA

Requisiti: Python 3.11 o successivo e la libreria pypdf.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import os
import re
import shutil
import string
import subprocess
import sys
import tomllib
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    print("ERRORE: serve la libreria pypdf (python3 -m pip install pypdf)", file=sys.stderr)
    sys.exit(1)

RADICE = Path(__file__).resolve().parent.parent
ELENCO = RADICE / "vista-web" / "documenti.toml"
MODELLO = RADICE / "vista-web" / "modello.html"
CARTELLE = {"esterno": "documentazione-esterna", "interno": "documentazione-interna"}
ETICHETTE = {"esterno": ("Documentazione esterna", "Verbali esterni"),
             "interno": ("Documentazione interna", "Verbali interni")}

# Nomi con la data in testa: tipo e uso che ne derivano. Tutti gli altri PDF sono documenti.
NOMI_CON_DATA = {
    "lettera-di-presentazione": ("lettera", "esterno", "Lettera di Presentazione"),
    "verbale-interno": ("verbale", "interno", "Verbale interno"),
    "verbale-esterno": ("verbale", "esterno", "Verbale esterno"),
    "diario-di-bordo": ("diario", "esterno", "Diario di bordo"),
}
CON_VERSIONE = ("documento", "verbale")

RE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_NOME = re.compile(r"^(?:(\d{4})(\d{2})(\d{2})_)?([a-z0-9]+(?:-[a-z0-9]+)*)\.pdf$")
RE_VERSIONE_COPERTINA = re.compile(r"Versione ?(\d+\.\d+\.\d+)")
RE_DATA_COPERTINA = re.compile(r"Data ?(\d{4}-\d{2}-\d{2})")
RE_RIGA_REGISTRO = re.compile(r"(\d+\.\d+\.\d+) (\d{4}-\d{2}-\d{2})")
RE_APPROVAZIONE = re.compile(r"(\d+)\.0\.0 (\d{4}-\d{2}-\d{2}) \D{0,80}?Approvazione per il rilascio")
RE_DESTINATARI = re.compile(r"Destinatari (.+?)(?: Redazione |$)")
REGISTRO = "Registro delle modifiche"


class Errore(Exception):
    """Errore che interrompe il programma, con un messaggio leggibile nel log."""


# Testi della pagina e consegne
def carica_elenco() -> dict:
    try:
        with ELENCO.open("rb") as f:
            dati = tomllib.load(f)
    except FileNotFoundError:
        raise Errore(f"file non trovato: {ELENCO.relative_to(RADICE)}")
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

    consegne = dati.get("consegne", [])
    if not consegne:
        raise Errore("serve almeno una consegna ([[consegne]])")
    visti: set[str] = set()
    for c in consegne:
        for chiave in ("id", "titolo", "data"):
            if chiave not in c:
                raise Errore(f'consegna "{c.get("titolo", "?")}": manca la chiave "{chiave}"')
        if "documenti" in c:
            raise Errore(f'consegna "{c["id"]}": i documenti non si elencano più, '
                         "la vista web li ricava dai PDF")
        if not RE_ID.match(c["id"]):
            raise Errore(f'consegna "{c["id"]}": l\'id usa solo minuscole, cifre e trattini')
        if c["id"] in visti:
            raise Errore(f'consegna "{c["id"]}": id ripetuto')
        visti.add(c["id"])
        if not RE_DATA.match(c["data"]):
            raise Errore(f'consegna "{c["id"]}": data non nel formato AAAA-MM-GG')
    dati["consegne"] = sorted(consegne, key=lambda c: c["data"])
    return dati


def consegna_dopo(consegne: list[dict], data: str) -> dict | None:
    """Prima consegna con data uguale o successiva a quella indicata."""
    return next((c for c in consegne if c["data"] >= data), None)


# Lettura dei PDF
def leggi_pdf(sorgente: Path | bytes) -> tuple[list[str], str]:
    """Testo delle prime pagine, con gli spazi normalizzati, e titolo nei metadati."""
    lettore = PdfReader(io.BytesIO(sorgente) if isinstance(sorgente, bytes) else sorgente)
    pagine = [" ".join((p.extract_text() or "").split()) for p in lettore.pages[:4]]
    titolo = ""
    if lettore.metadata and lettore.metadata.title:
        titolo = " ".join(str(lettore.metadata.title).split())
    return pagine, titolo


def versione_copertina(pagine: list[str]) -> str | None:
    m = RE_VERSIONE_COPERTINA.search(pagine[0]) if pagine else None
    return m.group(1) if m else None


def numeri(versione: str) -> tuple[int, ...]:
    return tuple(int(x) for x in versione.split("."))


def ripulisci(nome: str) -> str:
    # L'estrazione del testo può separare una maiuscola dal resto della parola ("T eam").
    return re.sub(r"\b([A-ZÀ-Ý]) (?=[a-zà-ÿ])", r"\1", nome).strip()


def azienda(pagine: list[str]) -> str | None:
    m = RE_DESTINATARI.search(pagine[0]) if pagine else None
    if not m:
        return None
    for parte in (p.strip() for p in m.group(1).split(",")):
        semplice = parte.replace(" ", "").lower()
        if parte and not semplice.startswith("ampalisteam") and not semplice.startswith("prof"):
            return ripulisci(parte)
    return None


def analizza(relativo: str, consegne: list[dict]) -> tuple[dict | None, list[str]]:
    """Ricava una voce della pagina da un PDF. Restituisce la voce (None se non si
    può pubblicare) e l'elenco dei problemi trovati."""
    percorso = Path(relativo)
    uso = next((u for u, cartella in CARTELLE.items() if percorso.parts[0] == cartella), None)
    m = RE_NOME.match(percorso.name)
    if not m:
        return None, [f"{relativo}: nome in minuscolo con parole separate da trattini, "
                      "eventuale data AAAAMMGG in testa seguita da un trattino basso"]
    data = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m.group(1) else None
    base = m.group(4)
    if data:
        try:
            dt.date.fromisoformat(data)
        except ValueError:
            return None, [f"{relativo}: {data} non è una data valida"]

    chiave = next((k for k in NOMI_CON_DATA if base == k or base.startswith(k + "-")), None)
    if chiave:
        tipo, uso_atteso, titolo = NOMI_CON_DATA[chiave]
        if not data:
            return None, [f"{relativo}: il nome deve iniziare con la data, AAAAMMGG_{base}.pdf"]
    else:
        if data:
            return None, [f"{relativo}: la data nel nome è solo per verbali, diari di bordo e "
                          "Lettera di Presentazione (verbale-interno, verbale-esterno, "
                          "diario-di-bordo, lettera-di-presentazione)"]
        tipo, uso_atteso, titolo = "documento", uso, ""
    problemi = []
    if uso != uso_atteso:
        problemi.append(f"{relativo}: va nella cartella {CARTELLE[uso_atteso]}/")

    try:
        pagine, titolo_pdf = leggi_pdf(RADICE / relativo)
    except Exception as err:  # PDF danneggiato o non leggibile
        return None, problemi + [f"{relativo}: PDF non leggibile ({err})"]

    d = {"file": relativo, "tipo": tipo, "uso": uso_atteso, "titolo": titolo}
    if data:
        d["data"] = data
    riferimento = data   # data che decide la consegna

    if tipo in CON_VERSIONE:
        versione = versione_copertina(pagine)
        if not versione:
            return None, problemi + [f"{relativo}: manca la versione in copertina (Versione X.Y.Z)"]
        d["versione"] = versione
        testo = " ".join(pagine)
        inizio = testo.find(REGISTRO)
        if inizio < 0:
            problemi.append(f"{relativo}: manca il registro delle modifiche")
            approvazioni = []
        else:
            prima = RE_RIGA_REGISTRO.search(testo, inizio)
            if prima and prima.group(1) != versione:
                problemi.append(f"{relativo}: versione {versione} in copertina, ma {prima.group(1)} "
                                "nella prima riga del registro")
            approvazioni = [(int(x), giorno) for x, giorno in RE_APPROVAZIONE.findall(testo, inizio)]
        x = numeri(versione)[0]
        if x >= 1 and not any(a == x for a, _ in approvazioni):
            problemi.append(f"{relativo}: versione {versione}, ma nel registro manca la riga "
                            f"di approvazione per il rilascio della {x}.0.0")

        if tipo == "documento":
            if not titolo_pdf:
                return None, problemi + [f"{relativo}: manca il titolo nei metadati del PDF "
                                         "(lo imposta il preambolo con \\TitoloDoc)"]
            d["titolo"] = titolo_pdf
            if approvazioni:
                riferimento = max(approvazioni)[1]
            else:
                m_data = RE_DATA_COPERTINA.search(pagine[0])
                if not m_data:
                    return None, problemi + [f"{relativo}: manca la data in copertina (Data AAAA-MM-GG)"]
                riferimento = m_data.group(1)
        elif uso_atteso == "esterno":
            nome = azienda(pagine)
            if not nome:
                return None, problemi + [f"{relativo}: manca l'azienda tra i destinatari in copertina"]
            d["titolo"] = f"Verbale esterno con {nome}"

    consegna = consegna_dopo(consegne, riferimento)
    if not consegna:
        return None, problemi + [f"{relativo}: nessuna consegna dal {riferimento} in poi "
                                 "in vista-web/documenti.toml"]
    d["consegna"] = consegna["id"]
    return d, problemi


def analizza_tutti(consegne: list[dict]) -> tuple[list[dict], list[str]]:
    documenti, problemi = [], []
    for cartella in CARTELLE.values():
        for pdf in sorted((RADICE / cartella).rglob("*.pdf")):
            d, trovati = analizza(pdf.relative_to(RADICE).as_posix(), consegne)
            problemi += trovati
            if d:
                documenti.append(d)
    for c in consegne:
        lettere = [d["file"] for d in documenti if d["tipo"] == "lettera" and d["consegna"] == c["id"]]
        if len(lettere) > 1:
            problemi.append(f'consegna "{c["id"]}": più di una Lettera di Presentazione '
                            f'({", ".join(lettere)})')
    return documenti, problemi


def git(*argomenti: str, testo: bool = True):
    esito = subprocess.run(["git", *argomenti], cwd=RADICE, capture_output=True, text=testo)
    if esito.returncode != 0:
        errore = esito.stderr if testo else esito.stderr.decode(errors="replace")
        raise Errore(f"git {' '.join(argomenti)}: {errore.strip()}")
    return esito.stdout


def controlla_versioni(base: str, documenti: list[dict]) -> list[str]:
    """Ogni PDF con versione già presente in base e poi modificato deve avere una versione più alta."""
    try:
        git("rev-parse", "--verify", f"{base}^{{commit}}")
    except Errore:
        raise Errore(f"--base {base}: riferimento non trovato (nella CI serve il checkout "
                     "completo, con fetch-depth: 0)")
    per_file = {d["file"]: d for d in documenti}
    problemi = []
    for riga in git("diff", "--name-status", base, "--", *CARTELLE.values()).splitlines():
        stato, _, percorso = riga.partition("\t")
        d = per_file.get(percorso)
        if stato != "M" or not d or "versione" not in d:
            continue
        precedente = versione_copertina(leggi_pdf(git("show", f"{base}:{percorso}", testo=False))[0])
        if precedente and numeri(d["versione"]) <= numeri(precedente):
            problemi.append(f"{percorso}: PDF modificato senza una versione più alta "
                            f"({precedente} in {base}, {d['versione']} ora)")
    return problemi


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
    parti.append(elenco_html("Documenti", sorted((d for d in del_uso if d["tipo"] == "documento"),
                                                 key=lambda d: d["titolo"].casefold())))
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
    ap.add_argument("--controlla", action="store_true", help="controlla i PDF, senza generare")
    ap.add_argument("--base", help="con --controlla, riferimento git con cui confrontare le versioni "
                                   "(per esempio origin/main)")
    args = ap.parse_args()

    try:
        dati = carica_elenco()
        consegne = dati["consegne"]
        documenti, problemi = analizza_tutti(consegne)
        if args.controlla and args.base:
            problemi += controlla_versioni(args.base, documenti)
    except Errore as err:
        print(f"ERRORE: {err}", file=sys.stderr)
        return 1

    if args.controlla:
        for d in sorted(documenti, key=lambda d: (d["consegna"], d["file"])):
            print(f'{d["consegna"]:<12} {d["tipo"]:<9} {d.get("versione", "-"):<8} {d["file"]}')
        for p in problemi:
            print(f"ERRORE {p}", file=sys.stderr)
        n = len(problemi)
        print(f"Controllo completato: {len(documenti)} documenti, {n} {'errore' if n == 1 else 'errori'}.")
        return 1 if problemi else 0

    # Su main un problema non ferma la pubblicazione: lo segnala il controllo sulla pull request.
    for p in problemi:
        print(f"AVVISO {p}", file=sys.stderr)

    sito = dati["sito"]
    uscita = Path(args.uscita)
    if not uscita.is_absolute():
        uscita = RADICE / uscita
    if uscita.exists():
        shutil.rmtree(uscita)
    uscita.mkdir(parents=True)

    sezioni: list[str] = []
    for c in reversed(consegne):   # dalla più recente
        della_consegna = [d for d in documenti if d["consegna"] == c["id"]]
        for d in della_consegna:
            destinazione = uscita / d["file"]
            destinazione.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RADICE / d["file"], destinazione)
        if della_consegna:
            sezioni.append(sezione(c, della_consegna))
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
    print(f"Vista web in {dove}: {len(documenti)} documenti pubblicati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
