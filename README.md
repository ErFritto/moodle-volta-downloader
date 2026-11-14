# Moodle Volta Downloader

Una piccola app per Windows e macOS che scarica i file di **un corso Moodle alla volta** e li raccoglie in **Desktop / Nome del corso**.

## Avvio

1. Su macOS scarica [MoodleVolta-macOS-AppleSilicon-v1.2.zip](MoodleVolta-macOS-AppleSilicon-v1.2.zip) dalla repository, estrailo e apri **MoodleVolta.app** con un doppio clic. Non serve installare Python. L'app precompilata è per Mac con chip Apple Silicon. Se macOS segnala uno sviluppatore non identificato, usa il menu contestuale **Apri** una volta. La finestra deve mostrare **Moodle Volta 1.2**.
2. Su Windows scarica questa repository con **Code → Download ZIP**, estrai la cartella e apri **Avvia.cmd**. Serve Python 3.10 o successivo con Tkinter.
3. Inserisci username e password di Moodle Volta e premi **Accedi**.
4. Scegli il corso, oppure incolla il suo link `https://www.moodlevolta.it/course/view.php?id=...`.
5. Premi **Scarica questo corso** e poi **Apri cartella**.

La password e i cookie di accesso rimangono in memoria e vengono eliminati chiudendo l’app.

### Avvio dal codice su macOS

Il file `Avvia-Mac.command` avvia l'interfaccia dal codice e apre anche Terminale. Richiede Python 3.10 o successivo con Tkinter 8.6 o successivo. Puoi installarli con `brew install python@3.12 python-tk@3.12`, oppure usare l'installer Python da [python.org](https://www.python.org/downloads/macos/). Non occorre installare `truststore` su macOS.

Se il file non si apre, dal Terminale nella cartella del progetto esegui `chmod +x Avvia-Mac.command`. Se macOS segnala che il file proviene da Internet, usa il menu contestuale **Apri** una volta.

Per ricreare l'app da codice su macOS, esegui `./build-mac.sh`. Il risultato è `dist/MoodleVolta.app`.

## Certificati HTTPS

Su Windows l’app usa `truststore` per verificare il certificato con il sistema operativo, compreso il recupero dei certificati intermedi mancanti. Le versioni recenti di pip lo includono già. Se il tool segnala che manca, esegui:

```powershell
py -3 -m pip install -r requirements.txt
```

La verifica HTTPS rimane sempre attiva.

## Cosa scarica

- File collegati direttamente al corso.
- Risorse **File**, **Cartella** e **Pagina**, comprese le sezioni collegate. Per le cartelle legge l'albero dei file e, quando disponibile, l'archivio ZIP di Moodle. Conserva la struttura delle sottocartelle.
- I file già scaricati vengono saltati se ancora presenti; i nomi uguali ricevono un suffisso.

Non gestisce video esterni, libri Moodle, forum, SCORM/H5P, CAPTCHA e SSO. Scarica solo i materiali visibili al tuo account. Se Moodle sostituisce un file mantenendo lo stesso URL, elimina la copia locale per riscaricarlo.

La versione 1.2 è stata verificata con pagine e download simulati, anche per le cartelle senza archivio ZIP. La compatibilità completa con Moodle Volta deve ancora essere verificata con un account reale. Se il registro indica **Cartelle Moodle rilevate: 0**, invia il link di una risorsa Cartella e il registro per adattare il lettore al formato specifico del corso.

Il progetto non è affiliato a Moodle o all’istituto.
