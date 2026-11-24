# Pomodoro + Todo

A small desktop app that combines a Pomodoro timer with a task list. It runs on Windows and Linux, and your tasks, settings, and stats are saved on your computer.

## Features

- **Task list:** add tasks with an estimated number of pomodoros, mark them done, or delete them. Tasks are saved in a local database.
- **Pomodoro timer:** work sessions, short breaks, and long breaks. Each finished work session adds one to the focused task's count.
- **Customisable durations:** change work, short break, long break, and the number of pomodoros before a long break in the Settings window. Defaults are 25 / 5 / 15 / 4.
- **Mini timer:** a small always-on-top window that shows only the time, with a small dog beside it. Drag it anywhere on screen.
- **Quick task list:** double-click the mini timer to pause. The task list opens so you can tick tasks off. Double-click again to resume.
- **Animated character:** the main window shows a character that types while you focus and sleeps while you rest.
- **Sound and notifications:** a chime and a system notification at the end of each phase.

## Requirements

- Python 3.9 or newer (Windows: from python.org, tick "Add Python to PATH" during install)
- PySide6 (installed below)

## Install and run from source

Open a terminal (Command Prompt or PowerShell on Windows, a terminal on Linux) in the folder that contains `pomodoro_todo.py`, then run:

```bash
pip install -r requirements.txt
python pomodoro_todo.py
```

If you don't have a `requirements.txt`, install the one dependency directly:

```bash
pip install PySide6
python pomodoro_todo.py
```

On Linux you may need to use `python3` and `pip3` instead.

## How to use it

**Main window**

| Control | What it does |
|---|---|
| Task box + est spinner + Add | Create a task with an estimated pomodoro count |
| Focus selected (or double-click a task) | Choose the task that the next work session counts toward |
| Toggle done | Mark the selected task done or not done |
| Delete | Remove the selected task |
| Start / Pause | Start or pause the timer |
| Reset | Restart the current phase from the beginning |
| Skip | End the current phase now and move to the next one |
| Show mini timer / Hide mini timer | Show or hide the floating timer |
| Settings | Change the timer durations |

**Mini timer**

- **Drag** it to move it.
- **Double-click** to pause. The task list opens below it.
- **Double-click** again to resume. The task list closes.
- **Click the dog** to make it jump.
- Green numbers mean the timer is running. Amber means it's paused.

**Task list popup:** click any task to tick it off or un-tick it. Press **Esc** or click **Close** to hide it.

## Settings

Click **Settings** to change:

- Work session length
- Short break length
- Long break length
- Number of pomodoros before a long break

Click **Defaults** to restore 25 / 5 / 15 / 4, then **Save**. If the timer is stopped, the new length shows immediately. If it's running, the new length applies from the next phase.

## Where your data is saved

The app stores files in your user folder:

| File | Contents |
|---|---|
| `.pomodoro_todo.db` | Your tasks and pomodoro counts |
| `.pomodoro_settings.json` | Your timer settings |
| `.pomodoro_chime.wav` | The sound played at the end of each phase |

On Windows your user folder is `C:\Users\YourName\`. On Linux it is `/home/YourName/`. These are hidden files, so you may need to show hidden items to see them.

To reset everything, close the app and delete these files.

## Build a standalone application (.exe / Linux binary)

Building creates a single program file that runs without needing Python installed. You build on the same operating system you want to run it on: build on Windows for Windows, and on Linux for Linux.

### 1. Install PyInstaller

```bash
pip install pyinstaller
```

### 2. Build the app

Run this in the folder that contains `pomodoro_todo.py`:

```bash
pyinstaller --onefile --windowed --name Pomodoro pomodoro.py
```

What the options do:

- `--onefile` packs everything into a single file.
- `--windowed` stops a console window from opening behind the app.
- `--name PomodoroTodo` sets the program name.

The build takes a minute or two. When it finishes, the program is in the `dist` folder:

- Windows: `dist\PomodoroTodo.exe`
- Linux: `dist/PomodoroTodo`

PyInstaller also creates a `build` folder and a `PomodoroTodo.spec` file. You can delete the `build` folder and the `.spec` file after building. Keep the `dist` folder.

### 3. Run it

- **Windows:** double-click `dist\PomodoroTodo.exe`.
- **Linux:** run `./dist/PomodoroTodo` from a terminal, or double-click it in the file manager if it's marked executable.

You can move `PomodoroTodo.exe` (or the Linux binary) anywhere you like. Your data is still saved in your user folder, so moving the program doesn't lose anything.

### 4. Create a desktop shortcut

**Windows**

1. Right-click `PomodoroTodo.exe` and choose **Send to → Desktop (create shortcut)**.
2. To rename the shortcut, right-click it, choose **Rename**, and type a name such as "Pomodoro Todo".
3. To change the icon, right-click the shortcut, choose **Properties → Change Icon**, and pick an icon file.
4. To pin it to the taskbar, right-click the desktop shortcut and choose **Show more options → Pin to taskbar**.

**Linux**

Create a file named `pomodoro-todo.desktop` with this content, changing the `Exec` path to the real location of your binary:

```ini
[Desktop Entry]
Type=Application
Name=Pomodoro Todo
Comment=Pomodoro timer with todo list
Exec=/home/YOURNAME/path/to/dist/PomodoroTodo
Terminal=false
Categories=Utility;
```

Then copy it to your desktop and the applications menu:

```bash
cp pomodoro-todo.desktop ~/Desktop/
cp pomodoro-todo.desktop ~/.local/share/applications/
chmod +x ~/Desktop/pomodoro-todo.desktop
```

On GNOME, right-click the desktop icon and choose **Allow Launching** if it doesn't open.

## Troubleshooting

**The app doesn't start from the built file.** Build it again from a terminal with `pyinstaller --onefile --name PomodoroTodo pomodoro_todo.py` (without `--windowed`). Run the resulting program from a terminal to see the error message. Then rebuild with `--windowed` once it works.

**No sound.** Check your system volume. On Linux, install the GStreamer audio plugins, for example `sudo apt install gstreamer1.0-plugins-good`.

**No notification pop-up on Linux.** Install a notification daemon such as `dunst` or `mako`.

**The mini timer is hidden behind fullscreen windows or doesn't stay on top on Linux.** Some Wayland desktops ignore "always on top" requests. Log in with an X11 session (for example "GNOME on Xorg") if this is a problem.

**Windows Defender or antivirus flags the .exe.** PyInstaller programs are sometimes flagged by mistake. Add an exception for the `dist` folder if you trust the build.

**The build is very large.** `--onefile` builds are usually 40 to 80 MB because they include Qt. This is normal.

## Customising the code

The durations at the top of the file are only defaults. Users change them in the Settings window, and the choices are saved. To change the defaults for everyone, edit `DEFAULT_SETTINGS` near the top of `pomodoro_todo.py`:

```python
DEFAULT_SETTINGS = {
    "work_min": 25,
    "short_break_min": 5,
    "long_break_min": 15,
    "pomodoros_before_long": 4,
}
```

If you change the file, rebuild with the PyInstaller command above to update the program.