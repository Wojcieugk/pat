import os
import sys
import re
import random
import string
import subprocess
import time
import requests
import contextlib
import io
from dotenv import load_dotenv
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from yt_dlp import YoutubeDL
from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    DownloadColumn,
    TransferSpeedColumn,
    SpinnerColumn,
)
from rich.spinner import Spinner
from rich.live import Live
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1

# ================= SETUP =================
load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    print("Brakuje danych w .env")
    sys.exit()

sp = Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

console = Console()

ROOT_DIR = "media"
PLAYLIST_DIR = os.path.join(ROOT_DIR, "playlisty")
SONGS_DIR = os.path.join(ROOT_DIR, "piosenki")
ARTISTS_DIR = os.path.join(ROOT_DIR, "artyści")
os.makedirs(PLAYLIST_DIR, exist_ok=True)
os.makedirs(SONGS_DIR, exist_ok=True)
os.makedirs(ARTISTS_DIR, exist_ok=True)

# ================= UI =================
def clear():
    os.system("cls" if os.name == "nt" else "clear")

def banner():
    clear()
    console.print("""
[magenta]
██████╗  █████╗ ████████╗
██╔══██╗██╔══██╗╚══██╔══╝
██████╔╝███████║   ██║
██╔═══╝ ██╔══██║   ██║
██║     ██║  ██║   ██║
╚═╝     ╚═╝  ╚═╝   ╚═╝
[/magenta]
""")

# ================= POMOCNICZE =================
def clean_filename(name):
    cleaned = re.sub(r'[\\/*?:"<>|]', '', name)
    if cleaned != name:
        console.print("✅ nazwa została poprawiona", style="green")
    return cleaned.strip()

def ensure_unique(filepath):
    base, ext = os.path.splitext(filepath)
    new_path = filepath
    while os.path.exists(new_path):
        console.print("☑️ znalazłem kopie piosenki, zapisuje", style="magenta")
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        new_path = f"{base}_{suffix}{ext}"
    return new_path

def get_audio_duration(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        return float(result.stdout)
    except:
        return 0

# ================= WYSZUKIWANIE 3 ŹRÓDEŁ =================
def search_best_source(name):
    queries = [
        f"ytsearch1:{name}",
        f"ytsearch1:{name} audio",
        f"ytsearch1:{name} official audio"
    ]
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "noplaylist": True,
    }
    for q in queries:
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(q, download=False)
            if info and "entries" in info and info["entries"]:
                return info["entries"][0]["webpage_url"]
        except:
            continue
    return None

# ================= METADATA =================
def add_metadata(path, title, artist, cover_url=None):
    try:
        audio = MP3(path, ID3=ID3)
        audio["TIT2"] = TIT2(encoding=3, text=title)
        audio["TPE1"] = TPE1(encoding=3, text=artist)
        if cover_url:
            img = requests.get(cover_url, timeout=10).content
            audio.tags.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=img
                )
            )
        audio.save()
    except:
        pass

# ================= POBIERANIE =================
def download_song(name, folder, cover_url=None):
    safe_name = clean_filename(name)
    final_path = os.path.join(folder, f"{safe_name}.mp3")
    final_path = ensure_unique(final_path)

    search_url = search_best_source(name)
    if not search_url:
        console.print("❌ nie znaleziono źródła", style="red")
        return False

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": final_path.replace(".mp3", ".%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "logger": None,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    for attempt in range(3):
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[magenta]Pobieranie [purple]{task.description}[/purple]"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console
            ) as progress:

                task = progress.add_task(f"{safe_name}", total=1)

                def hook(d):
                    if d["status"] == "finished":
                        progress.update(task, completed=1)

                ydl_opts["progress_hooks"] = [hook]

                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with YoutubeDL(ydl_opts) as ydl:
                        ydl.download([search_url])

            duration = get_audio_duration(final_path)
            if duration < 30:
                raise Exception("Plik za krótki")

            parts = name.split(" ", 1)
            title = parts[0]
            artist = parts[1] if len(parts) > 1 else ""
            add_metadata(final_path, title, artist, cover_url)

            console.print(f"✔ [purple]{safe_name}[/purple]", style="green")
            return True
        except:
            console.print(f"⚠ Retry {attempt+1}/3", style="yellow")
            time.sleep(1)

    console.print("❌ nie udało się pobrać", style="red")
    return False

# ================= PAGINACJA =================
def paginate(items, page_size=5):
    pages = []
    for i in range(0, len(items), page_size):
        pages.append(items[i:i+page_size])
    return pages

# ================= WYBÓR Z PAGINACJĄ =================
def choose_from_list(items, title_key="name", extra_info=None):
    pages = paginate(items, 5)
    current = 0
    while True:
        clear()
        console.print(f"\nStrona {current+1}/{len(pages)}\n")
        for idx, item in enumerate(pages[current]):
            text = f"{idx+1}. {item[title_key]}"
            if extra_info:
                text += f" - {extra_info(item)}"
            console.print(text)
        console.print("\nn. Następna strona, p. Poprzednia, 0. Powrót")
        choice = input(">>> ")
        if choice == "n" and current < len(pages)-1:
            current += 1
        elif choice == "p" and current > 0:
            current -= 1
        elif choice == "0":
            return []
        elif choice.isdigit():
            idx = int(choice)-1
            if 0 <= idx < len(pages[current]):
                return [pages[current][idx]]
        else:
            continue

# ================= SEKCE ARTYŚCI =================
def handle_artist():
    console.print("\n1. Wklej link artysty")
    console.print("2. Wyszukaj artystę po nazwie")
    console.print("0. Powrót")
    choice = input(">>> ")
    if choice == "1":
        link = input("Link: ")
        aid = link.split("artist/")[-1].split("?")[0]
        artist_obj = sp.artist(aid)
    elif choice == "2":
        query = input("Nazwa artysty: ")
        results = sp.search(q=query, type="artist", limit=10)
        items = results["artists"]["items"]
        if not items:
            console.print("❌ Nie znaleziono artysty", style="red")
            return
        artist_obj = choose_from_list(items, title_key="name", extra_info=lambda x: f"followers: {x['followers']['total']}")[0]
        artist_obj = sp.artist(artist_obj["id"])
    else:
        return
    console.print(f"\nWybrany artysta: {artist_obj['name']}\n")
    tracks = []
    offset = 0
    while True:
        t_data = sp.artist_top_tracks(artist_obj["id"])["tracks"]
        tracks.extend(t_data)
        break
    selected = choose_tracks(tracks)
    if not selected:
        return
    folder = os.path.join(ARTISTS_DIR, clean_filename(artist_obj["name"]))
    os.makedirs(folder, exist_ok=True)
    for t in selected:
        name = f"{t['name']} {t['artists'][0]['name']}"
        cover = t['album']['images'][0]['url'] if t['album']['images'] else None
        download_song(name, folder, cover)

# ================= WYBÓR UTWORÓW =================
def choose_tracks(tracks):
    filtered_tracks = [t for t in tracks if t and 'artists' in t and t['artists']]
    if not filtered_tracks:
        console.print("❌ Brak utworów do pobrania!", style="red")
        return []
    console.print("\n1. Pobierz wszystko (usuń niechciane)")
    console.print("2. Wybierz konkretne numery")
    console.print("0. Powrót")
    choice = input(">>> ")
    if choice == "1":
        for i, t in enumerate(filtered_tracks):
            dur = get_audio_duration(t['preview_url']) if t.get('preview_url') else 0
            console.print(f"{i+1}. [purple]{t['name']}[/purple] - {t['artists'][0]['name']}")
        remove = input("\nNumery do usunięcia (ENTER = wszystkie): ")
        selected = filtered_tracks.copy()
        if remove.strip():
            nums = sorted([int(n)-1 for n in remove.split() if n.isdigit()], reverse=True)
            for n in nums:
                if 0 <= n < len(selected):
                    selected.pop(n)
        return selected
    elif choice == "2":
        for i, t in enumerate(filtered_tracks):
            console.print(f"{i+1}. [purple]{t['name']}[/purple] - {t['artists'][0]['name']}")
        pick = input("\nNumery do pobrania: ")
        selected = []
        for n in pick.split():
            if n.isdigit():
                idx = int(n)-1
                if 0 <= idx < len(filtered_tracks):
                    selected.append(filtered_tracks[idx])
        return selected
    return []

# ================= SEKCJA PIOSENKI =================
def handle_song():
    console.print("\n1. Wklej link piosenki")
    console.print("2. Wyszukaj piosenkę po nazwie")
    console.print("0. Powrót")
    choice = input(">>> ")
    if choice == "1":
        link = input("Link: ")
        # pobieramy info
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with YoutubeDL({"quiet": True, "no_warnings": True, "ignoreerrors": True}) as ydl:
                    info = ydl.extract_info(link, download=False)
            console.print(f"\nTytuł: {info['title']}")
            console.print(f"Autor: {info['uploader']}")
            console.print(f"Długość: {int(info['duration'])}s")
            confirm = input("Pobrać tę piosenkę? (y/n) ")
            if confirm.lower() != "y":
                return
            folder = SONGS_DIR
            os.makedirs(folder, exist_ok=True)
            download_song(f"{info['title']} {info['uploader']}", folder)
        except:
            console.print("❌ Błąd przy pobieraniu info z linku", style="red")
    elif choice == "2":
        query = input("Nazwa piosenki: ")
        # wyszukiwanie
        ydl_opts = {"quiet": True, "no_warnings": True, "ignoreerrors": True}
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with YoutubeDL(ydl_opts) as ydl:
                    search_res = ydl.extract_info(f"ytsearch10:{query}", download=False)
            entries = search_res["entries"]
            selected = choose_from_list(entries, title_key="title", extra_info=lambda x: f"{x['uploader']} - {int(x['duration'])}s")
            if not selected:
                return
            folder = SONGS_DIR
            os.makedirs(folder, exist_ok=True)
            for s in selected:
                download_song(f"{s['title']} {s['uploader']}", folder)
        except:
            console.print("❌ Błąd przy wyszukiwaniu piosenek", style="red")
    else:
        return

# ================= ŁADOWANIE PLAYLISTY =================
def load_playlist(pid):
    all_tracks = []
    offset = 0
    limit = 50
    playlist = sp.playlist(pid)
    while True:
        tracks_data = sp.playlist_items(pid, offset=offset, limit=limit)
        items = [item["track"] for item in tracks_data["items"] if item["track"]]
        all_tracks.extend(items)
        if tracks_data["next"]:
            offset += limit
        else:
            break
    return playlist, all_tracks

# ================= OBSŁUGA PLAYLIST =================
def handle_playlist():
    console.print("\n1. Wklej link")
    console.print("2. Wyszukaj nazwą")
    console.print("0. Powrót")
    choice = input(">>> ")
    if choice == "1":
        link = input("Link: ")
        pid = link.split("playlist/")[-1].split("?")[0]
    elif choice == "2":
        query = input("Nazwa playlisty: ")
        results = sp.search(q=query, type="playlist", limit=10)
        items = results["playlists"]["items"]
        for i, p in enumerate(items):
            console.print(f"{i+1}. {p['name']} - {p['owner']['display_name']}")
        pick = int(input("Wybierz numer: ")) - 1
        pid = items[pick]["id"]
    else:
        return
    with Live(Spinner("dots", style="magenta"), console=console, refresh_per_second=10):
        console.print("[magenta]:: Konfiguracja playlisty...[/magenta]")
        time.sleep(1.5)
    playlist, tracks = load_playlist(pid)
    console.print(f"\nZaładowano {len(tracks)} utworów\n")
    selected = choose_tracks(tracks)
    if not selected:
        return
    folder = os.path.join(PLAYLIST_DIR, clean_filename(playlist["name"]))
    os.makedirs(folder, exist_ok=True)
    for t in selected:
        name = f"{t['name']} {t['artists'][0]['name']}"
        cover = t['album']['images'][0]['url'] if t['album']['images'] else None
        download_song(name, folder, cover)

# ================= MAIN =================
def main():
    banner()
    while True:
        console.print("\n1. Playlisty")
        console.print("2. Piosenki")
        console.print("3. Artyści")
        console.print("0. Wyjście")
        choice = input(">>> ")
        if choice == "1":
            handle_playlist()
        elif choice == "2":
            handle_song()
        elif choice == "3":
            handle_artist()
        elif choice == "0":
            break

if __name__ == "__main__":
    main()