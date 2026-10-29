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
├── vista-web/                # elenco dei documenti e generatore della vista web
└── .github/workflows/        # pubblicazione della vista web
```

Il repository contiene solo i PDF dei documenti verificati e approvati; le bozze restano nel repository privato del gruppo. Le regole di lavoro sono nel *Way of Working*.

## Vista web

La pagina si rigenera a ogni modifica di `main` a partire da `vista-web/documenti.toml`. Un documento compare quando il suo PDF è su `main`, cioè dopo che il Responsabile ha unito la pull request.

La pull request che aggiunge un PDF, o ne pubblica una nuova versione, aggiorna anche la voce del documento in `vista-web/documenti.toml` (titolo, data, versione). Su ogni pull request un controllo automatico segnala i PDF non elencati, le voci incomplete e i nomi di file che non seguono le regole.

Prova in locale, dalla radice del repository (serve Python 3.11 o successivo):

```
python3 vista-web/genera.py --controlla
python3 vista-web/genera.py
```

La pagina generata è in `_site/index.html`.
