# Moodle Volta Downloader

Una piccola app per Windows che scarica i file di **un corso Moodle alla volta** e li raccoglie in **Desktop / Nome del corso**.

## Avvio

1. Installa Python 3.10 o successivo con Tkinter.
2. Scarica questa repository con **Code → Download ZIP** ed estrai la cartella.
3. Apri **Avvia.cmd** con un doppio clic.
4. Inserisci username e password di Moodle Volta e premi **Accedi**.
5. Scegli il corso, oppure incolla il suo link `https://www.moodlevolta.it/course/view.php?id=...`.
6. Premi **Scarica questo corso** e poi **Apri cartella**.

La password e i cookie di accesso rimangono in memoria e vengono eliminati chiudendo l’app.

## Certificati HTTPS

Su Windows l’app usa `truststore` per verificare il certificato con il sistema operativo, compreso il recupero dei certificati intermedi mancanti. Le versioni recenti di pip lo includono già. Se il tool segnala che manca, esegui:

```powershell
py -3 -m pip install -r requirements.txt
```

La verifica HTTPS rimane sempre attiva.

## Cosa scarica

- File collegati direttamente al corso.
- Risorse **File**, **Cartella** e **Pagina**, comprese le sezioni collegate.
- I file già scaricati vengono saltati se ancora presenti; i nomi uguali ricevono un suffisso.

Non gestisce video esterni, libri Moodle, forum, SCORM/H5P, CAPTCHA e SSO. Scarica solo i materiali visibili al tuo account. Se Moodle sostituisce un file mantenendo lo stesso URL, elimina la copia locale per riscaricarlo.

Versione iniziale verificata con pagine e download simulati. La compatibilità completa con Moodle Volta deve ancora essere verificata con un account reale.

Il progetto non è affiliato a Moodle o all’istituto.
