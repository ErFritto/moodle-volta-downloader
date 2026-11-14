"""Download dei file Moodle con verifica HTTPS del sistema operativo."""
import ctypes
import hashlib
import http.cookiejar
import json
import os
import queue
import re
import ssl
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse as up
import urllib.request as ur
import urllib.error
from collections import deque
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from pathlib import PurePosixPath
import zipfile
import tkinter as tk
from tkinter import ttk, messagebox

BASE = 'https://www.moodlevolta.it'
VERSION = '1.2'


def tls_context():
    if os.name == 'nt':
        try:
            import truststore
        except ImportError:
            try:
                # Le versioni recenti di pip includono già truststore.
                from pip._vendor import truststore
            except ImportError as exc:
                raise RuntimeError(
                    'Per verificare i certificati Windows serve truststore. '
                    'Apri il terminale ed esegui: py -3 -m pip install truststore'
                ) from exc
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl.create_default_context()


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:150]
    if not value:
        return 'Senza nome'
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1, 10)), *('LPT'+str(i) for i in range(1, 10))}:
        value = '_' + value
    return value


def desktop():
    if os.name == 'nt':
        # CSIDL_DESKTOPDIRECTORY segue anche il reindirizzamento OneDrive.
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:
            return Path(buf.value)
    return Path.home() / 'Desktop'


class FolderTree(HTMLParser):
    """Ricava i percorsi delle risorse Cartella dal loro albero HTML."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.items = []
        self.in_name = False
        self.hidden = False
        self.paths = {}
        self.roots = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'ul':
            if self.depth:
                self.depth += 1
            elif 'foldertree' in a.get('class', '').split():
                self.depth = 1
        elif self.depth and tag == 'li':
            self.items.append({'name': '', 'href': None})
        elif self.depth and tag == 'p' and self.items:
            self.in_name = True
        elif self.in_name and tag == 'span' and 'visually-hidden' in a.get('class', '').split():
            self.hidden = True
        elif self.in_name and tag == 'a' and self.items:
            self.items[-1]['href'] = a.get('href')

    def handle_data(self, data):
        if self.in_name and not self.hidden and self.items:
            self.items[-1]['name'] += data

    def handle_endtag(self, tag):
        if tag == 'span':
            self.hidden = False
        elif tag == 'p':
            self.in_name = False
        elif tag == 'li' and self.depth and self.items:
            item = self.items.pop()
            if item['href'] and 'pluginfile.php' in item['href']:
                self.paths[item['href']] = tuple(
                    safe_name(parent['name']) for parent in self.items if parent['name'].strip()
                )
            elif not self.items and item['name'].strip():
                self.roots.append(safe_name(item['name']))
        elif tag == 'ul' and self.depth:
            self.depth -= 1


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links, self.inputs, self.headings, self.forms = [], {}, [], []
        self.section_numbers, self.section_ids, self.folder_module_ids = set(), set(), set()
        self.anchor = None
        self.heading = None
        self.form = None
        self.feed(html)
        tree = FolderTree(html)
        self.folder_paths, self.folder_roots = tree.paths, tree.roots

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and a.get('href'):
            self.anchor = [a['href'], a.get('title', '')]
        for attr in ('data-url', 'data-href'):
            if a.get(attr):
                self.links.append((a[attr], ''))
        section_number = re.fullmatch(r'section-(\d+)', a.get('id', ''))
        if section_number:
            self.section_numbers.add(int(section_number[1]))
        for attr in ('data-sectionnumber', 'data-sectionnum'):
            if a.get(attr, '').isdigit():
                self.section_numbers.add(int(a[attr]))
        if a.get('data-sectionid', '').isdigit():
            self.section_ids.add(int(a['data-sectionid']))
        if 'modtype_folder' in a.get('class', '').split():
            module_id = a.get('data-cmid', '')
            if not module_id:
                match = re.fullmatch(r'module-(\d+)', a.get('id', ''))
                module_id = match[1] if match else ''
            if module_id.isdigit():
                self.folder_module_ids.add(int(module_id))
        if tag == 'input' and a.get('name'):
            self.inputs[a['name']] = a.get('value', '')
            if self.form is not None:
                self.form[2][a['name']] = a.get('value', '')
        if tag == 'form':
            self.form = [a.get('action', ''), a.get('method', 'get').lower(), {}]
        if tag == 'h1':
            self.heading = []
        if tag in ('iframe', 'embed', 'object'):
            src = a.get('src') or a.get('data')
            if src:
                self.links.append((src, ''))

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor[1] += ' ' + data
        if self.heading is not None:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == 'form' and self.form is not None:
            self.forms.append(self.form)
            self.form = None
        if tag == 'a' and self.anchor is not None:
            self.links.append((self.anchor[0], ' '.join(self.anchor[1].split())))
            self.anchor = None
        if tag == 'h1' and self.heading is not None:
            self.headings.append(' '.join(' '.join(self.heading).split()))
            self.heading = None


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = ur.build_opener(
            ur.HTTPCookieProcessor(self.jar), ur.HTTPSHandler(context=tls_context())
        )
        self.opener.addheaders = [('User-Agent', 'MoodleCourseDownloader/1.0')]

    def open(self, url, data=None):
        try:
            return self.opener.open(url, data=data, timeout=60)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                system = 'Windows' if os.name == 'nt' else 'macOS' if sys.platform == 'darwin' else 'sistema'
                raise RuntimeError(
                    'Il certificato HTTPS non risulta valido neppure usando '
                    f'i certificati attendibili di {system}. Verifica se il sito '
                    'si apre nel browser senza avvisi e controlla data e ora del computer. '
                    'Dettaglio: ' + str(exc.reason)
                ) from exc
            raise

    def page(self, url, data=None):
        with self.open(url, data) as r:
            body = r.read().decode(r.headers.get_content_charset() or 'utf-8', errors='replace')
            if '/login/' in r.url and data is None:
                raise RuntimeError('Sessione scaduta: accedi nuovamente.')
            return Page(body), r.url, body

    def login(self, username, password):
        url = BASE + '/login/index.php'
        with self.open(url) as r:
            p = Page(r.read().decode('utf-8', errors='replace'))
        fields = {'username': username, 'password': password}
        if 'logintoken' in p.inputs:
            fields['logintoken'] = p.inputs['logintoken']
        p, final, body = self.page(url, up.urlencode(fields).encode())
        if 'password' in p.inputs or '/login/index.php' in final:
            raise RuntimeError('Accesso non riuscito. Controlla username e password. Se il sito richiede CAPTCHA o altri passaggi, questa versione non li gestisce.')
        # Verifica una pagina protetta prima di dichiarare riuscito l'accesso.
        self.page(BASE + '/my/')

    def courses(self):
        found = {}
        for path in ('/my/courses.php', '/my/', '/'):
            try:
                p, final, _ = self.page(BASE + path)
                for href, label in p.links:
                    url = up.urljoin(final, href)
                    parts = up.urlsplit(url)
                    cid = up.parse_qs(parts.query).get('id', [''])[0]
                    if parts.hostname == up.urlsplit(BASE).hostname and parts.path == '/course/view.php' and cid.isdigit() and cid != '1':
                        found[cid] = (label or 'Corso ' + cid, BASE + '/course/view.php?id=' + cid)
            except Exception:
                continue
        return sorted(found.values(), key=lambda v: v[0].casefold())

    def download(self, course_url, log):
        course_parts = up.urlsplit(course_url.strip())
        if course_parts.scheme != 'https' or course_parts.hostname != up.urlsplit(BASE).hostname or course_parts.path != '/course/view.php':
            raise ValueError('Incolla il link del corso, ad esempio https://www.moodlevolta.it/course/view.php?id=123')
        cid = up.parse_qs(course_parts.query).get('id', [''])[0]
        if not cid.isdigit() or cid == '1':
            raise ValueError('Il link deve contenere un ID corso valido.')
        course_url = BASE + '/course/view.php?id=' + cid
        first, final, _ = self.page(course_url)
        if not first.headings:
            raise RuntimeError('Titolo del corso non trovato. Verifica che il corso sia accessibile.')
        root = desktop() / safe_name(first.headings[0])
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / ('.moodle-' + cid + '.json')
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            manifest = {}
        # url, pagina già letta, è un archivio Cartella, nome Cartella, percorso locale
        pending = deque([(course_url, first, False, None, ())])
        seen = set()
        downloaded = skipped = failed = 0
        found_folders = set()
        errors = []

        def save_manifest():
            tmp = manifest_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(manifest_path)

        def existing_file(key):
            old = manifest.get(key)
            if not isinstance(old, str):
                return None
            old_path = Path(old)
            if old_path.is_absolute() or '..' in old_path.parts:
                return None
            path = root / old_path
            return path if path.resolve().is_relative_to(root.resolve()) and path.is_file() else None

        def folder_path(file_url, hint, tree_path):
            if tree_path:
                return tree_path
            path_parts = up.urlsplit(file_url).path.split('/')
            if 'mod_folder' not in path_parts:
                return ()
            index = path_parts.index('mod_folder')
            subdirs = path_parts[index + 3:-1] if path_parts[index + 1:index + 2] == ['content'] else []
            context_id = path_parts[index - 1] if index else 'sconosciuta'
            folder_name = hint or 'Cartella_' + context_id
            return (safe_name(folder_name), *(safe_name(up.unquote(part)) for part in subdirs))

        while pending:
            url, parsed, is_archive, folder_hint, relative_folder = pending.popleft()
            url = up.urldefrag(url)[0]
            if url in seen:
                continue
            seen.add(url)
            try:
                if parsed is None:
                    with self.open(url) as r:
                        if '/login/' in r.url:
                            raise RuntimeError('Sessione scaduta: accedi nuovamente.')
                        if is_archive:
                            with tempfile.TemporaryFile() as archive_file:
                                shutil.copyfileobj(r, archive_file)
                                archive_file.seek(0)
                                with zipfile.ZipFile(archive_file) as archive:
                                    for item in archive.infolist():
                                        # Moodle può mettere uno slash iniziale nel percorso ZIP.
                                        path = PurePosixPath(item.filename.lstrip('/'))
                                        if ('..' in path.parts or
                                                '\\' in item.filename or not path.parts or
                                                (item.external_attr >> 16) & 0o170000 == 0o120000):
                                            log('Voce ZIP ignorata: ' + item.filename)
                                            continue
                                        entry_parts = [safe_name(part) for part in path.parts if part not in ('', '.')]
                                        if not entry_parts:
                                            continue
                                        dest = root.joinpath(safe_name(folder_hint or 'Cartella'), *entry_parts)
                                        if not dest.resolve().is_relative_to(root.resolve()):
                                            log('Voce ZIP ignorata: ' + item.filename)
                                            continue
                                        if item.is_dir():
                                            dest.mkdir(parents=True, exist_ok=True)
                                            continue
                                        key = url + '#' + item.filename
                                        old_path = existing_file(key)
                                        if old_path:
                                            skipped += 1
                                            log('Già presente: ' + str(old_path.relative_to(root)))
                                            continue
                                        if dest.is_file() and str(dest.relative_to(root)) in manifest.values():
                                            skipped += 1
                                            log('Già presente: ' + str(dest.relative_to(root)))
                                            continue
                                        if dest.exists():
                                            suffix = hashlib.sha256(key.encode()).hexdigest()[:10]
                                            dest = dest.with_name(safe_name(dest.stem[:110] + '_' + suffix + dest.suffix))
                                        if dest.exists():
                                            raise RuntimeError('Nome file già occupato: ' + str(dest.relative_to(root)))
                                        dest.parent.mkdir(parents=True, exist_ok=True)
                                        tmp = dest.with_name(dest.name + '.part')
                                        try:
                                            with archive.open(item) as source, tmp.open('wb') as out:
                                                shutil.copyfileobj(source, out)
                                            tmp.replace(dest)
                                        finally:
                                            tmp.unlink(missing_ok=True)
                                        name = str(dest.relative_to(root))
                                        manifest[key] = name
                                        save_manifest()
                                        downloaded += 1
                                        log('Scaricato: ' + name)
                            continue
                        content_type = r.headers.get_content_type()
                        is_file = ('pluginfile.php' in up.urlsplit(r.url).path or
                                   'attachment' in r.headers.get('Content-Disposition', '').lower() or
                                   content_type not in ('text/html', 'application/xhtml+xml'))
                        if is_file:
                            old_path = existing_file(url)
                            if old_path:
                                skipped += 1
                                log('Già presente: ' + str(old_path.relative_to(root)))
                                continue
                            msg = Message()
                            msg['Content-Disposition'] = r.headers.get('Content-Disposition', '')
                            name = safe_name(msg.get_filename() or up.unquote(up.urlsplit(r.url).path.rsplit('/', 1)[-1]) or 'file')
                            dest = root.joinpath(*relative_folder, name)
                            if not dest.resolve().is_relative_to(root.resolve()):
                                raise RuntimeError('Percorso file non valido: ' + name)
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            if dest.exists():
                                p = Path(name)
                                name = safe_name(p.stem[:110] + '_' + hashlib.sha256(url.encode()).hexdigest()[:10] + p.suffix)
                                dest = dest.with_name(name)
                            if dest.exists():
                                raise RuntimeError('Nome file già occupato: ' + name)
                            tmp = dest.with_name(dest.name + '.part')
                            try:
                                with tmp.open('wb') as out:
                                    while True:
                                        chunk = r.read(1024 * 256)
                                        if not chunk:
                                            break
                                        out.write(chunk)
                                tmp.replace(dest)
                            finally:
                                tmp.unlink(missing_ok=True)
                            manifest[url] = str(dest.relative_to(root))
                            save_manifest()
                            downloaded += 1
                            log('Scaricato: ' + str(dest.relative_to(root)))
                            continue
                        parsed = Page(r.read().decode(r.headers.get_content_charset() or 'utf-8', errors='replace'))
                        url = r.url
                if up.urlsplit(url).path == '/mod/folder/view.php' and parsed.folder_roots:
                    folder_hint = parsed.folder_roots[0]
                if up.urlsplit(url).path == '/mod/folder/view.php' and folder_hint:
                    found_folders.add(folder_hint)
                    (root / safe_name(folder_hint)).mkdir(parents=True, exist_ok=True)
                if up.urlsplit(url).path in ('/course/view.php', '/course/section.php'):
                    for folder_name in parsed.folder_roots:
                        found_folders.add(folder_name)
                        (root / safe_name(folder_name)).mkdir(parents=True, exist_ok=True)
                archives = []
                for action, method, fields in parsed.forms:
                    target = up.urljoin(url, action)
                    t = up.urlsplit(target)
                    if (method == 'get' and t.scheme == 'https' and t.hostname == course_parts.hostname and
                            t.path == '/mod/folder/download_folder.php'):
                        query = up.parse_qs(t.query)
                        folder_id = query.get('id', [fields.get('id', '')])[0]
                        if str(folder_id).isdigit():
                            archives.append(BASE + t.path + '?id=' + str(folder_id))
                for href, label in parsed.links:
                    target = up.urljoin(url, href)
                    t = up.urlsplit(target)
                    if t.scheme != 'https' or t.hostname != course_parts.hostname:
                        continue
                    q = up.parse_qs(t.query)
                    # Segue solo risorse leggibili; non invia form né apre attività di consegna.
                    if 'pluginfile.php' in t.path:
                        tree_path = parsed.folder_paths.get(href, ())
                        pending.append((target, None, False, folder_hint,
                                        folder_path(target, folder_hint, tree_path)))
                    elif re.fullmatch(r'/mod/(resource|folder|page)/view\.php', t.path):
                        mid = q.get('id', q.get('f', ['']))[0]
                        if mid.isdigit() and ('id' in q or t.path == '/mod/folder/view.php'):
                            parameter = 'id' if 'id' in q else 'f'
                            pending.append((BASE + t.path + '?' + parameter + '=' + mid, None, False,
                                            label if t.path == '/mod/folder/view.php' else None, ()))
                    elif t.path == '/mod/folder/download_folder.php' and q.get('id', [''])[0].isdigit():
                        archives.append(BASE + t.path + '?id=' + q['id'][0])
                    elif t.path == '/course/section.php' and q.get('id', [''])[0].isdigit():
                        pending.append((BASE + t.path + '?id=' + q['id'][0], None, False, None, ()))
                    elif t.path == '/course/view.php' and q.get('id', [''])[0] == cid and q.get('section', [''])[0].isdigit():
                        pending.append((course_url + '&section=' + q['section'][0], None, False, None, ()))
                for index, archive_url in enumerate(dict.fromkeys(archives)):
                    archive_id = up.parse_qs(up.urlsplit(archive_url).query)['id'][0]
                    archive_name = (folder_hint or
                                    (parsed.folder_roots[index] if index < len(parsed.folder_roots) else None) or
                                    'Cartella_' + archive_id)
                    found_folders.add(archive_name)
                    pending.append((archive_url, None, True, archive_name, ()))
                if up.urlsplit(url).path in ('/course/view.php', '/course/section.php'):
                    for number in sorted(parsed.section_numbers):
                        if 0 <= number < 100:
                            pending.append((course_url + '&section=' + str(number), None, False, None, ()))
                    for section_id in sorted(parsed.section_ids):
                        pending.append((BASE + '/course/section.php?id=' + str(section_id), None, False, None, ()))
                    for module_id in sorted(parsed.folder_module_ids):
                        pending.append((BASE + '/mod/folder/view.php?id=' + str(module_id), None, False,
                                        'Cartella_' + str(module_id), ()))
            except Exception as exc:
                failed += 1
                errors.append(str(exc))
                log('Errore: ' + str(exc))
        log(f'Finito: {downloaded} scaricati, {skipped} già presenti, {failed} errori.')
        log(f'Cartelle Moodle rilevate: {len(found_folders)}.')
        if not found_folders:
            log('Nessuna risorsa Cartella visibile nelle pagine lette. Serve il link di una Cartella per controllare questo formato del corso.')
        if downloaded + skipped == 0:
            log('Nessun file trovato. Il corso potrebbe usare un formato o attività non supportati.')
        return root, downloaded, skipped, failed


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'Moodle Volta {VERSION} — Scarica un corso')
        self.geometry('760x620')
        self.minsize(650, 500)
        self.events = queue.Queue()
        self.client = None
        self.course_items = []
        self.result_folder = None
        box = ttk.Frame(self, padding=18)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text=f'Moodle Volta {VERSION}', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(box, text='Scarica i file di un corso in Desktop / Nome del corso').pack(anchor='w', pady=(2, 15))
        form = ttk.Frame(box)
        form.pack(fill='x')
        ttk.Label(form, text='Username').grid(row=0, column=0, sticky='w')
        ttk.Label(form, text='Password').grid(row=0, column=1, sticky='w', padx=10)
        self.username = ttk.Entry(form)
        self.password = ttk.Entry(form, show='•')
        self.username.grid(row=1, column=0, sticky='ew')
        self.password.grid(row=1, column=1, sticky='ew', padx=10)
        self.login_button = ttk.Button(form, text='Accedi', command=self.login)
        self.login_button.grid(row=1, column=2)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        ttk.Label(box, text='Corso', font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(18, 5))
        self.courses = ttk.Combobox(box, state='readonly')
        self.courses.pack(fill='x')
        self.courses.bind('<<ComboboxSelected>>', self.select_course)
        ttk.Label(box, text='Oppure incolla il link del corso (course/view.php?id=...)').pack(anchor='w', pady=(10, 4))
        self.url = ttk.Entry(box)
        self.url.pack(fill='x')
        buttons = ttk.Frame(box)
        buttons.pack(fill='x', pady=14)
        self.download_button = ttk.Button(buttons, text='Scarica questo corso', command=self.download, state='disabled')
        self.download_button.pack(side='left')
        self.folder_button = ttk.Button(buttons, text='Apri cartella', command=self.open_folder, state='disabled')
        self.folder_button.pack(side='left', padx=10)
        self.progress = ttk.Progressbar(box, mode='indeterminate')
        self.progress.pack(fill='x', pady=(0, 10))
        self.logbox = tk.Text(box, height=12, wrap='word', state='disabled', font=('Segoe UI', 10))
        self.logbox.pack(fill='both', expand=True)
        ttk.Label(box, text='La password e la sessione rimangono solo in memoria. Chiudi l’app per eliminarle.').pack(anchor='w', pady=(10, 0))
        self.after(100, self.poll)

    def log(self, message):
        self.events.put(('log', message))

    def busy(self, value):
        self.login_button.configure(state='disabled' if value else 'normal')
        self.download_button.configure(state='normal' if not value and self.client else 'disabled')
        self.progress.start(12) if value else self.progress.stop()

    def run_job(self, job):
        self.busy(True)
        def work():
            try:
                job()
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.events.put(('idle', None))
        threading.Thread(target=work, daemon=True).start()

    def login(self):
        username, password = self.username.get().strip(), self.password.get()
        if not username or not password:
            messagebox.showinfo('Accesso', 'Inserisci username e password.')
            return
        self.password.delete(0, 'end')
        self.client = None
        self.courses.set('')
        self.courses.configure(values=[])
        def job():
            client = Client()
            self.log('Accesso in corso…')
            client.login(username, password)
            self.log('Accesso riuscito. Cerco i corsi…')
            self.events.put(('login', (client, client.courses())))
        self.run_job(job)

    def select_course(self, event=None):
        index = self.courses.current()
        if index >= 0:
            self.url.delete(0, 'end')
            self.url.insert(0, self.course_items[index][1])

    def download(self):
        url = self.url.get().strip()
        client = self.client
        def job():
            self.log('Lettura del corso e download…')
            self.events.put(('done', client.download(url, self.log)))
        self.run_job(job)

    def open_folder(self):
        if self.result_folder:
            if sys.platform == 'darwin':
                subprocess.Popen(['open', str(self.result_folder)])
            elif os.name == 'nt':
                os.startfile(str(self.result_folder))
            else:
                subprocess.Popen(['xdg-open', str(self.result_folder)])

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log':
                    self.logbox.configure(state='normal')
                    self.logbox.insert('end', value + '\n')
                    self.logbox.see('end')
                    self.logbox.configure(state='disabled')
                elif kind == 'error':
                    self.log('Operazione interrotta: ' + value)
                    messagebox.showerror('Moodle Downloader', value)
                elif kind == 'idle':
                    self.busy(False)
                elif kind == 'login':
                    self.client, self.course_items = value
                    self.courses.configure(values=[x[0] for x in self.course_items])
                    self.log(f'{len(self.course_items)} corsi trovati. Puoi anche incollare il link di un corso.')
                    if self.course_items:
                        self.courses.current(0)
                        self.select_course()
                elif kind == 'done':
                    self.result_folder, n, skipped, failed = value
                    self.folder_button.configure(state='normal')
                    self.log('Cartella: ' + str(self.result_folder))
                    messagebox.showinfo('Download terminato', f'{n} file scaricati\n{skipped} già presenti\n{failed} errori\n\n{self.result_folder}\n\nVedi il registro per eventuali errori o file non trovati.')
        except queue.Empty:
            pass
        self.after(100, self.poll)


if __name__ == '__main__':
    App().mainloop()
