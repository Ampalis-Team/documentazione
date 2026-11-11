# Ampalis Team

Documentazione di progetto di Ampalis Team (Gruppo 2), per il corso di Ingegneria del Software dell'Università degli Studi di Padova, a.a. 2026/2027.

**Vista web:** https://ampalis-team.github.io/documentazione/

La vista web raccoglie i documenti pubblicati divisi per consegna, con la *Lettera di Presentazione* di ogni consegna in evidenza in cima.

## Struttura

```
documentazione/
├── documentazione-esterna/   # documenti per committente e proponente
│   ├── verbali-esterni/
│   └── diari-di-bordo/
├── documentazione-interna/   # documenti a uso del gruppo
├── template/                 # modelli dei documenti
├── logo/                     # logo del gruppo
├── vista-web/                # generatore della vista web, testi della pagina e consegne
└── .github/workflows/        # pubblicazione della vista web
```

Il repository contiene solo i PDF dei documenti verificati; le versioni X.0.0 sono quelle approvate per il rilascio dal Responsabile. Le bozze restano nel repository privato del gruppo. Le regole di lavoro, versionamento compreso, sono nelle *Norme di Progetto*.

## Vista web

La pagina si rigenera a ogni modifica di `main` a partire dai PDF presenti: un documento compare quando il suo PDF è su `main`, cioè dopo l'unione della pull request. Non c'è un elenco dei documenti da aggiornare:

- tipo e uso si ricavano dalla cartella e dal nome del file; verbali, diari di bordo e Lettera di Presentazione hanno la data in testa al nome (`20261104_verbale-interno.pdf`);
- la versione si legge dalla copertina del PDF, il titolo dei documenti dai metadati del PDF e, per i verbali esterni, l'azienda dai destinatari in copertina;
- verbali, diari e Lettera compaiono nella prima consegna con data uguale o successiva alla loro; un documento compare nella consegna della sua ultima approvazione per il rilascio, letta nel registro delle modifiche, oppure, se non è mai stato approvato, nella prima consegna dopo la data in copertina.

`vista-web/documenti.toml` contiene solo i testi della pagina e le consegne, e si modifica solo quando cambiano. La pubblicazione non fa commit.

Su ogni pull request un controllo automatico segnala i nomi di file fuori regola, i documenti senza versione in copertina o con copertina e registro diversi, una versione X.0.0 senza la riga di approvazione per il rilascio, più di una Lettera di Presentazione per consegna e i PDF già su `main` modificati senza una versione più alta. La pull request si unisce solo con il controllo superato.

Prova in locale, dalla radice del repository (servono Python 3.11 o successivo e `python3 -m pip install pypdf`):

```
python3 vista-web/genera.py --controlla --base origin/main
python3 vista-web/genera.py
```

La pagina generata è in `_site/index.html`.
