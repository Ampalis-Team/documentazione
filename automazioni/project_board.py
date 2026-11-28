#!/usr/bin/env python3
"""Automazione "Project Board automatica" (Norme di Progetto, paragrafo sulle automazioni).

Completa le automazioni già comprese nella Project Board (Auto-add to project,
Item added to project -> Attivo, Item closed e Pull request merged -> Completato):
- issue aperta: la aggiunge alla Project Board e, se ha una milestone, la mette
  nell'iterazione in corso;
- issue chiusa come non pianificata: la sposta in Scartato (l'automazione compresa
  la mette in Completato come ogni issue chiusa; questa viene eseguita dopo);
- pull request aperta: la aggiunge, la mette nell'iterazione in corso e in In corso;
- push: ogni issue citata in un commit con "Refs #N" (o con una parola chiave di
  chiusura, per i commit più vecchi) passa a In corso, se è in Sprint Backlog o Attivo.

Il token predefinito delle Actions non può modificare i progetti
dell'organizzazione: il workflow ottiene un token dalla GitHub App del gruppo e
lo passa come PROJECT_TOKEN. Serve anche la variabile del repository
PROGETTO_NUMERO, il numero della Project Board (lo si legge nel suo indirizzo,
.../orgs/Ampalis-Team/projects/N).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys

import comune as c

RE_RIFERIMENTO = re.compile(r"\b(?:refs|close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
STATO = "Status"
ITERAZIONE = "Iterazione"
IN_CORSO = "In corso"
DA_AVVIARE = (None, "Sprint Backlog", "Attivo")
SCARTATO = "Scartato"


def progetto() -> dict:
    org = c.REPO.split("/")[0]
    numero = int(os.environ["PROGETTO_NUMERO"])
    q = """query($org:String!,$n:Int!){organization(login:$org){projectV2(number:$n){id
      fields(first:50){nodes{
        ... on ProjectV2SingleSelectField{id name options{id name}}
        ... on ProjectV2IterationField{id name configuration{iterations{id startDate duration}}}}}}}}"""
    p = c.graphql(q, {"org": org, "n": numero})["organization"]["projectV2"]
    campi = {f["name"]: f for f in p["fields"]["nodes"] if f}
    return {"id": p["id"], "campi": campi}


def aggiungi(prog: dict, nodo: str) -> str:
    q = """mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}"""
    return c.graphql(q, {"p": prog["id"], "c": nodo})["addProjectV2ItemById"]["item"]["id"]


def imposta(prog: dict, elemento: str, campo: str, valore: dict) -> None:
    q = """mutation($p:ID!,$i:ID!,$f:ID!,$v:ProjectV2FieldValue!){
      updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:$v}){projectV2Item{id}}}"""
    c.graphql(q, {"p": prog["id"], "i": elemento, "f": prog["campi"][campo]["id"], "v": valore})


def stato(prog: dict, elemento: str, nome: str) -> None:
    opzione = next(o["id"] for o in prog["campi"][STATO]["options"] if o["name"] == nome)
    imposta(prog, elemento, STATO, {"singleSelectOptionId": opzione})


def stato_attuale(elemento: str) -> str | None:
    q = """query($i:ID!){node(id:$i){... on ProjectV2Item{fieldValueByName(name:"Status"){
      ... on ProjectV2ItemFieldSingleSelectValue{name}}}}}"""
    valore = c.graphql(q, {"i": elemento})["node"]["fieldValueByName"]
    return valore["name"] if valore else None


def iterazione_in_corso(prog: dict, giorno: dt.date) -> str | None:
    campo = prog["campi"].get(ITERAZIONE)
    if not campo:
        return None
    for it in campo["configuration"]["iterations"]:
        inizio = c.data(it["startDate"])
        if inizio <= giorno < inizio + dt.timedelta(days=it["duration"]):
            return it["id"]
    return None


def nella_iterazione(prog: dict, elemento: str) -> str:
    it = iterazione_in_corso(prog, c.oggi())
    if it:
        imposta(prog, elemento, ITERAZIONE, {"iterationId": it})
        return "iterazione in corso"
    return "nessuna iterazione in corso"


def principale() -> int:
    if not os.environ.get("PROJECT_TOKEN") or not os.environ.get("PROGETTO_NUMERO"):
        c.riepilogo("Manca il token della GitHub App (variabile APP_CLIENT_ID e secret "
                    "APP_PRIVATE_KEY) o la variabile PROGETTO_NUMERO: automazione non ancora "
                    "configurata (automazioni/README.md).")
        return 0
    ev, nome = c.evento(), os.environ.get("GITHUB_EVENT_NAME", "")
    prog = progetto()
    righe = []
    if nome == "issues" and ev.get("action") == "closed":
        issue = ev["issue"]
        if issue.get("state_reason") == "not_planned":
            elemento = aggiungi(prog, issue["node_id"])
            stato(prog, elemento, SCARTATO)
            righe.append(f"- issue #{issue['number']} in {SCARTATO} (chiusa come non pianificata)")
    elif nome == "issues":
        issue = ev["issue"]
        elemento = aggiungi(prog, issue["node_id"])
        nota = nella_iterazione(prog, elemento) if issue.get("milestone") else "senza milestone"
        righe.append(f"- issue #{issue['number']} nella Project Board ({nota})")
    elif nome == "pull_request":
        pr = ev["pull_request"]
        elemento = aggiungi(prog, pr["node_id"])
        nota = nella_iterazione(prog, elemento)
        stato(prog, elemento, IN_CORSO)
        righe.append(f"- pull request #{pr['number']} in {IN_CORSO} ({nota})")
    elif nome == "push":
        numeri = sorted({int(n) for k in ev.get("commits", []) for n in RE_RIFERIMENTO.findall(k["message"])})
        for n in numeri:
            issue = c.richiesta("GET", f"/repos/{c.REPO}/issues/{n}")
            if "pull_request" in issue or issue["state"] != "open":
                continue
            elemento = aggiungi(prog, issue["node_id"])
            if stato_attuale(elemento) in DA_AVVIARE:
                stato(prog, elemento, IN_CORSO)
                righe.append(f"- issue #{n} in {IN_CORSO}")
    c.riepilogo("### Project Board\n" + ("\n".join(righe) if righe else "Nessuna modifica."))
    return 0


if __name__ == "__main__":
    sys.exit(principale())
