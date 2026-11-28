"""Funzioni comuni alle automazioni del repository documentazione.

Solo libreria standard di Python 3.12: le chiamate a GitHub usano urllib,
così i workflow non installano dipendenze (tranne dove serve leggere i PDF).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
CARTELLA = Path(__file__).resolve().parent
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
REPO = os.environ.get("GITHUB_REPOSITORY", "Ampalis-Team/documentazione")

RUOLI_ESTESI = {"Re": "Responsabile", "Am": "Amministratore", "An": "Analista",
                "Pg": "Progettista", "Pr": "Programmatore", "Ve": "Verificatore"}


# ---------------------------------------------------------------------
# Dati del gruppo
# ---------------------------------------------------------------------
def carica_ruoli() -> dict:
    with open(CARTELLA / "ruoli.toml", "rb") as f:
        return tomllib.load(f)


def carica_calendario() -> list[str]:
    with open(CARTELLA / "calendario-diari.toml", "rb") as f:
        return list(tomllib.load(f)["date"])


def data(testo: str) -> dt.date:
    return dt.date.fromisoformat(testo)


def sprint_del_giorno(ruoli: dict, giorno: dt.date) -> dict | None:
    for s in ruoli["sprint"]:
        if data(s["inizio"]) <= giorno <= data(s["fine"]):
            return s
    return None


def sprint_numero(ruoli: dict, numero: int) -> dict | None:
    return next((s for s in ruoli["sprint"] if s["numero"] == numero), None)


def nome_di(ruoli: dict, utente: str) -> str | None:
    for nome, u in ruoli["componenti"].items():
        if u.lower() == (utente or "").lower():
            return nome
    return None


def utente_di(ruoli: dict, nome: str) -> str | None:
    return ruoli["componenti"].get(nome)


def responsabile(ruoli: dict, sprint: dict) -> str:
    return next(n for n, r in sprint["ruoli"].items() if r == "Re")


# ---------------------------------------------------------------------
# Issue: righe Origine e Scadenza
# ---------------------------------------------------------------------
# "Scadenza: AAAA-MM-GG" su una riga, oppure il campo del modulo delle issue
# ("### Scadenza" seguito dalla data)
RIGA_SCADENZA = re.compile(r"^\s*(?:Scadenza:|#+\s*Scadenza\s*\n+)\s*(\d{4}-\d{2}-\d{2})\s*$", re.M)
RIGA_ORIGINE = re.compile(r"^\s*Origine:\s*\S", re.M)


def scadenza(corpo: str | None) -> dt.date | None:
    m = RIGA_SCADENZA.search(corpo or "")
    return data(m.group(1)) if m else None


# ---------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------
class ErroreGitHub(RuntimeError):
    pass


def _token(nome: str = "GITHUB_TOKEN") -> str:
    t = os.environ.get(nome, "")
    if not t:
        raise ErroreGitHub(f"manca la variabile {nome}: va impostata nel workflow")
    return t


def richiesta(metodo: str, percorso: str, corpo=None, token: str = "GITHUB_TOKEN"):
    """Chiamata REST. percorso relativo all'API, per esempio /repos/{REPO}/issues."""
    url = percorso if percorso.startswith("http") else API + percorso
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dati, method=metodo, headers={
        "Authorization": f"Bearer {_token(token)}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ampalis-automazioni",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            testo = r.read().decode()
            return json.loads(testo) if testo else None
    except urllib.error.HTTPError as e:
        raise ErroreGitHub(f"{metodo} {percorso}: {e.code} {e.read().decode()[:300]}") from None


def pagine(percorso: str, token: str = "GITHUB_TOKEN") -> list:
    """Tutte le pagine di un elenco REST."""
    risultati, pagina = [], 1
    sep = "&" if "?" in percorso else "?"
    while True:
        parte = richiesta("GET", f"{percorso}{sep}per_page=100&page={pagina}", token=token)
        if not parte:
            return risultati
        risultati.extend(parte)
        if len(parte) < 100:
            return risultati
        pagina += 1


def graphql(query: str, variabili: dict | None = None, token: str = "PROJECT_TOKEN") -> dict:
    risposta = richiesta("POST", "/graphql", {"query": query, "variables": variabili or {}}, token=token)
    if risposta.get("errors"):
        raise ErroreGitHub(json.dumps(risposta["errors"])[:500])
    return risposta["data"]


def evento() -> dict:
    percorso = os.environ.get("GITHUB_EVENT_PATH")
    if not percorso:
        return {}
    with open(percorso, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------
# Uscita
# ---------------------------------------------------------------------
def riepilogo(testo: str) -> None:
    """Scrive nel riepilogo dell'esecuzione (o a video, in locale)."""
    percorso = os.environ.get("GITHUB_STEP_SUMMARY")
    if percorso:
        with open(percorso, "a", encoding="utf-8") as f:
            f.write(testo.rstrip() + "\n")
    else:
        print(testo)


def errore(messaggio: str) -> None:
    print(f"::error::{messaggio}")


def avviso(messaggio: str) -> None:
    print(f"::warning::{messaggio}")


def oggi() -> dt.date:
    """Data di oggi a Roma (le esecuzioni programmate partono in UTC)."""
    forzata = os.environ.get("OGGI")
    if forzata:
        return data(forzata)
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Europe/Rome")).date()


def esci(errori: list[str], titolo: str) -> int:
    if errori:
        riepilogo(f"### {titolo}: {len(errori)} problemi\n")
        for e in errori:
            riepilogo(f"- {e}")
            errore(e)
        return 1
    riepilogo(f"### {titolo}: nessun problema")
    return 0


if __name__ == "__main__":
    r = carica_ruoli()
    s = sprint_del_giorno(r, oggi())
    print("Sprint di oggi:", s["numero"] if s else "nessuno")
    sys.exit(0)
