#!/bin/zsh

# Avvio con doppio clic da Finder. Cerca una versione di Python con Tkinter.
script_dir="${0:A:h}"
cd "$script_dir" || exit 1

for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.14 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys, tkinter; assert sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6' >/dev/null 2>&1; then
        "$candidate" "$script_dir/moodle_downloader.py"
        result=$?
        if (( result != 0 )); then
            echo
            echo "L'app si è chiusa con un errore (codice $result)."
            read -r '?Premi Invio per chiudere questa finestra.'
        fi
        exit $result
    fi
done

echo 'Serve Python 3.10 o successivo con Tkinter 8.6 o successivo.'
echo 'Installa Python per macOS da python.org, oppure Python e python-tk con Homebrew.'
echo 'Con Homebrew: brew install python@3.12 python-tk@3.12'
read -r '?Premi Invio per chiudere questa finestra.'
exit 1
