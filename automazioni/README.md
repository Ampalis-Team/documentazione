# Automazioni del repository documentazione

Script e dati delle automazioni descritte nelle Norme di Progetto (paragrafo sulle automazioni). I workflow sono in `.github/workflows/`, gli script qui. Gli script usano solo la libreria standard di Python 3.12, più `pypdf` dove leggono i PDF.

| Workflow | Script | Quando |
|---|---|---|
| `vista-web.yml` | `vista-web/genera.py` | pull request e `main` (già presente; `genera.py` riconosce anche i report settimanali) |
| `project-board-automatica.yml` | `project_board.py` | issue, pull request, push |
| `scadenze.yml` | `scadenze.py` | ogni giorno, 7:00 |
| `ricorrenti.yml` | `ricorrenti.py` | domenica, 20:00: diario di bordo e, nell'ultima settimana dello sprint, Piano di Progetto; lunedì, 18:00: verbale interno; martedì, 20:00: report settimanale per l'incontro con M31 del mercoledì; mercoledì, 17:00: verbale esterno |
| `consuntivo.yml` | `consuntivo.py` | ogni lunedì, 7:00, e a mano |
| `consegna.yml` | `consegna.py` | a mano, prima di RTB e PB |

`consuntivo.py`, `consegna.py` e `ricorrenti.py` usano le funzioni di lettura dei PDF di `vista-web/genera.py`. In `genera.py` cambia solo il riconoscimento dei report settimanali (`documentazione-esterna/report-settimanali/AAAAMMGG_report-settimanale.pdf`): senza questa modifica il controllo della vista web segnala come errore il PDF di un report.

Dati:
- `ruoli.toml`: componenti e utenti GitHub, sprint con periodo e ruoli (matrice della Dichiarazione degli Impegni), costi orari;
- `calendario-diari.toml`: date dei diari di bordo.

Li tiene aggiornati l'Amministratore. Se uno sprint si allunga (Norme di Progetto, metodo di lavoro), sposta le date di quello sprint e dei successivi in `ruoli.toml`, nelle milestone e nelle iterazioni della Project Board.

## Da fare una volta, su GitHub

Lo fanno i proprietari dell'organizzazione. Nessun token e nessuna chiave vanno scritti nei file.

### 1. GitHub App per la Project Board

Il token predefinito delle Actions non può modificare i progetti dell'organizzazione. Una GitHub App dell'organizzazione dà ai workflow un token che dura un'ora, non scade come un token personale e non dipende da una persona. L'app scrive anche le issue e i commenti delle automazioni (issue ricorrenti, promemoria delle scadenze, avvisi del consuntivo): risultano di `ampalis-team-automazioni[bot]`, con il nome e il logo dell'app, e, a differenza di quelle del token predefinito, avviano gli altri workflow, per esempio quello che mette le issue ricorrenti nell'iterazione dello sprint.

Si crea da *Ampalis-Team → Settings → Developer settings → GitHub Apps → New GitHub App*:

| Campo | Valore |
|---|---|
| GitHub App name | `Ampalis Team Automazioni` (deve essere unico su GitHub: se è già preso, aggiungere per esempio `C4`) |
| Description | `Automazioni della Project Board e del consuntivo delle ore del repository documentazione.` |
| Homepage URL | `https://github.com/Ampalis-Team/documentazione` |
| Callback URL | vuoto |
| Expire user authorization tokens | lasciare come è |
| Request user authorization (OAuth) during installation | non selezionato |
| Enable Device Flow | non selezionato |
| Setup URL | vuoto |
| Webhook, Active | **non selezionato** (l'app non riceve eventi: la usano solo i workflow) |
| Repository permissions | *Issues*: Read and write; *Pull requests*: Read-only; *Metadata*: Read-only (obbligatorio, si imposta da solo) |
| Organization permissions | *Projects*: Read and write |
| Account permissions | nessuno |
| Where can this GitHub App be installed? | *Only on this account* |

Poi:
1. *Create GitHub App*. Nella pagina dell'app copiare il **Client ID** (comincia con `Iv`; non serve l'App ID). Nella sezione *Display information* si può caricare il logo del gruppo, che compare accanto alle issue aperte dall'app.
2. In fondo alla stessa pagina, *Private keys → Generate a private key*: si scarica un file `.pem`.
3. Nel menu a sinistra, *Install App → Install* su `Ampalis-Team`, scegliendo *Only select repositories* e il repository `documentazione` (dal PoC si aggiunge quello del codice).
4. In *documentazione → Settings → Secrets and variables → Actions*:
   - scheda *Variables*: `APP_CLIENT_ID` con il Client ID e `PROGETTO_NUMERO` con il numero che compare nell'indirizzo della Project Board (`.../orgs/Ampalis-Team/projects/N`), per la Project Board del gruppo `1`;
   - scheda *Secrets*: `APP_PRIVATE_KEY` con tutto il contenuto del file `.pem`, righe `BEGIN` ed `END` comprese.
5. Cancellare il file `.pem` dal computer: se serve, se ne genera una nuova dalla pagina dell'app.

Fino a quando `APP_CLIENT_ID`, `APP_PRIVATE_KEY` e `PROGETTO_NUMERO` non ci sono, i workflow della Project Board e del consuntivo terminano senza fare nulla, mentre issue ricorrenti e scadenze usano il token predefinito e risultano di `github-actions[bot]`.

### 2. Project Board

- Campi (*Settings* della Project Board), con i nomi in italiano (Norme di Progetto, paragrafo sulla lingua): `Status` con le opzioni Sprint Backlog, Attivo, In corso, In revisione, Completato, Scartato; `Iterazione` di due settimane, con un'iterazione per sprint (*Primo sprint* dal 2026-11-04, *Secondo sprint* dal 2026-11-16 e così via); tre campi *Number* da creare: `Stima`, `Ore effettive`, `Ore di verifica`; un campo *Multi select* da creare: `Verificatori`, con un'opzione per ogni componente scritta come in `ruoli.toml` (Nome Cognome), da compilare con tutti i verificatori della issue; un campo *Single select* da creare: `Ruolo (se diverso)`, con le opzioni Responsabile, Amministratore, Analista, Progettista, Programmatore e Verificatore, da compilare solo quando l'assegnatario svolge la issue in un ruolo diverso dal suo nello sprint (le ore di verifica contano sempre come Verificatore). Il consuntivo divide le ore di verifica in parti uguali tra i verificatori selezionati. Gli script cercano questi nomi esatti: se cambiano, vanno cambiati anche in `project_board.py` e `consuntivo.py`.
- Automazioni comprese (*Workflows* della Project Board): *Auto-add to project* dal repository `documentazione`, filtro `is:issue,pr is:open` (con il piano Free se ne attiva una sola); *Item added to project*: Status Attivo; *Item closed* e *Pull request merged*: Status Completato. Una issue chiusa come non pianificata (*Close as not planned*) la sposta in Scartato `project_board.py`.

### 3. Foglio delle ore di orologio

Dallo Sprint 2 il foglio Google Sheets serve solo a formazione e altro: una riga per componente e per sprint, con le colonne `Sprint`, `Componente`, `Formazione` e `Altro` (le altre colonne restano per gli sprint precedenti e l'automazione le ignora). Per farlo leggere al consuntivo:
1. nel foglio, *File → Condividi → Pubblica sul web*;
2. scegliere la scheda delle ore (non *Intero documento*) e il formato *Valori separati da virgola (.csv)*, poi *Pubblica*;
3. copiare l'indirizzo e salvarlo in *documentazione → Settings → Secrets and variables → Actions → Variables* come `FOGLIO_ORE_CSV`.

La pubblicazione si aggiorna da sola quando cambia il foglio. Chi ha l'indirizzo può leggere la scheda, non modificarla. Le ore di riunione non si scrivono nel foglio: il consuntivo le prende dai verbali, contando solo i componenti nella lista dei partecipanti; chi è presente solo in parte si scrive nel verbale con l'orario tra parentesi, per esempio `Nome Cognome (dalle 17:00)`.

### 4. Etichette e tipi

- Creare l'etichetta `infrastructure` (*Issues → Labels*), con la descrizione della tabella delle etichette delle Norme di Progetto.
- Nell'organizzazione (*Settings → Issue types*) devono esistere Task, Feature e Bug.

### 5. Repository

Lasciare disattivata *Automatically delete head branches*.

## Avvisi delle esecuzioni programmate

GitHub avvisa di un errore in un workflow programmato solo chi ha modificato per ultimo l'orario (`cron`) nel file. A ogni cambio di ruolo il nuovo Amministratore modifica la riga dell'orario in `scadenze.yml`, `ricorrenti.yml` e `consuntivo.yml`, per esempio spostando i minuti di uno (da `0 6 * * *` a `1 6 * * *`), con una pull request come le altre. Gli errori del consuntivo arrivano a tutti con la issue di avviso.

## Prove in locale

Dalla cartella `automazioni`:

```
OGGI=2026-11-29 PROVA=1 GITHUB_TOKEN=... python3 ricorrenti.py   # mostra le issue che creerebbe
OGGI=2026-12-01 PROVA=1 GITHUB_TOKEN=... python3 ricorrenti.py   # il martedì: report settimanale del 2026-12-02
OGGI=2026-12-02 PROVA=1 GITHUB_TOKEN=... python3 ricorrenti.py   # il mercoledì: verbale esterno del 2026-12-02
python3 consegna.py                                              # documenti da approvare
python3 ../vista-web/genera.py --controlla
```
