---
title: MIDI Studio User Guide
subtitle: For MIDI Studio 0.3.3
---

A program for turning a MIDI file into readable sheet music, listening to it, tidying it up and printing it.

# 1. What this program does

A **Musical Instrument Digital Interface (MIDI) file** (ending in `.mid`) is not a recording. It is a list of instructions: "play this note, this loud, starting now, for this long." Most music players can play one. MIDI Studio reads that list and **draws it as sheet music**. You can then play it, watch a red line move across the score, zoom in, change the tempo, mute instruments, tidy the score, and print it.

You do not need to read music to use the program, but it helps. Words you may not know are explained in the [word list](#words-used-in-this-guide) at the end.

**Two rules to remember**

1. **Your original file is safe.** The program never changes your file unless you **Save** over it. When in doubt, use **File ▸ Save As…** and give the new version a new name.
2. **The recording is correct; the score is the program's reading of it.** If a score looks odd (a chord no hand could play, a note on the wrong staff, a strange rest), the music was almost certainly played correctly. The repair tools in this guide change how the *score is drawn*. They do not "fix" the person who played. Everything they do can be undone with **File ▸ Undo Correction**.

# 2. Getting the program

## Windows 10 or 11 (64-bit)

**The easy way: the installer.** Download **MIDI-Studio-Setup.exe** and double-click it. It installs for only you (no administrator password is needed, because it is not shared with other users of your computer), adds MIDI Studio to your Start menu, and can put an icon on your desktop. To remove it later, use **Settings ▸ Apps** or the **Uninstall MIDI Studio** entry in the Start menu.

**Without installing: the zip file.** Download **MIDI-Studio-windows-x64.zip**. Right-click it, choose **Extract All…**, then click **Extract**. Open the new folder and double-click **MIDI-Studio.exe**. Do not run the program from inside the zip window; Windows lets you open a zip like a folder, but nothing works until it is extracted. Leave the `_internal` folder where it is.

**"Windows protected your PC".** Windows shows this because the program is free and not code-signed, so it says the publisher is unknown. Click the small faint words **More info**, then **Run anyway**. Windows should not ask again for that copy.

## Linux (64-bit)

Download **MIDI-Studio-x86_64.AppImage**. Make it runnable (right-click ▸ Properties ▸ *Allow executing as program*, or `chmod +x MIDI-Studio-x86_64.AppImage`) and double-click it. It carries its own copy of Python, the built-in synthesizer (FluidSynth) and a set of instrument sounds, so it makes sound without any setup. If you already have another synthesizer on your computer (a software one such as TiMidity, or a Musical Instrument Digital Interface (MIDI) keyboard or sound module), the program lists it under **Setup ▸ MIDI Output Device…** and you can choose it instead (section 9).

**Adding it to your application menu.** Download **install-linux.sh** from the same page and run `bash install-linux.sh` in the folder that holds both files. It copies the program to a folder called `Applications` in your home folder (no administrator password) and asks **"Add MIDI Studio to your application menu?"** Answer Enter for yes. To remove everything later, run `bash uninstall-linux.sh`; it also offers to remove a copy of LilyPond that MIDI Studio downloaded for you (it never touches one you installed yourself) and asks, with the standard answer No, whether to remove your saved settings.

**If the program will not start.** On recent Ubuntu and Kubuntu (24.04 and later) an AppImage may refuse to start until you install one small library: `sudo apt install libfuse2t64` (on older Ubuntu: `libfuse2`). The install script notices this and sets up the menu entry so that the program still starts, just a little slower.

**Running from the source code instead** is explained in the file `docs/LINUX_FROM_SOURCE.md` on the project page.

## Removing the program

- **Windows installer:** **Settings ▸ Apps**, or **Uninstall MIDI Studio** in the Start menu. If MIDI Studio had downloaded LilyPond for you, the uninstaller asks whether to remove it too (the standard answer is Yes), and then whether to remove your saved settings (the standard answer is No). A LilyPond that you installed or unpacked yourself is never touched.
- **Windows zip:** delete the folder you extracted. If MIDI Studio downloaded LilyPond, it is in `%LOCALAPPDATA%\MIDI-Studio\ly` (type that into the address bar of a File Explorer window); delete that folder too if you like.
- **Linux:** `bash uninstall-linux.sh`, or delete the AppImage file.

## Where the downloads are

On the GitHub Releases page: `https://github.com/winthrom/midi-studio/releases/latest`. The newest version is always at the top. Download from this page, not from the "Actions" page (which needs a login and wraps files in an extra zip).

# 3. Your first five minutes

1. Start the program. A small window says **Starting MIDI Studio…** while the sounds load. On an older computer this can take about 12 seconds.
2. The first time, you may be asked to choose where sound comes from. Choose **FluidSynth (built in)**. You can change this later (section 9).
3. Click **File** (upper left), then **Open…** and choose a MIDI (`.mid`) file. The program remembers the folder you used last.
4. The music appears as a score. Each instrument gets its own line, called a **staff**. The name of each instrument is written above its staff at the left.
5. Click **▶ Play** (or press the **space bar**). You hear the music and a red line shows where you are. Click **⏹ Stop** to stop.

That is all you need to listen. Everything else in this guide is optional.

# 4. The main window

## The row of buttons across the top

| Button | What it does |
|---|---|
| **⏮** | Go back to the beginning. |
| **◀◀  ▶▶** | Jump back or forward by one measure. |
| **▶ Play** / **⏹ Stop** | Start (or pause) and stop the music. The space bar does the same as Play. |
| **⏺ Rec** | Record from a Musical Instrument Digital Interface (MIDI) keyboard connected to the computer. You do not need this just to listen. |
| **Click: OFF / ON** | Turns a metronome click on or off during playback. |
| **+ Track** | Adds a new empty instrument line. |
| **♫ Score**, **♬ Roll**, **📋 List**, **🎚 Mixer** | Open the four ways of looking at the music (section 5). |
| **BPM** | The speed in Beats Per Minute (BPM). A higher number is faster. |
| **Meas … Beat …** | Shows where you are in the piece. |
| **Sel … – … ▶ Sel** | Type a first and last measure, then click **▶ Sel** to play only that part. Useful for practising one passage. |

## The menus

**File**

- **New**, **Open…**, **Close Piece**: start fresh, open a file, or close the current one.
- **Save**, **Save As…**: write the music to a MIDI file. Use **Save As…** to keep your original safe.
- **Export MIDI…**: the same as Save As.
- **Save as .musicxml (standard)…**: a format that notation programs such as MuseScore can open.
- **Open in MuseScore (via MIDI)…**: if you have MuseScore installed, sends the music there.
- **Export LilyPond (.ly)…** and **Print Score (via LilyPond)…**: for printing a high-quality score (section 8).
- **Undo Correction** / **Redo Correction** (Ctrl+Z / Ctrl+Y): step back or forward through the corrections you made.
- **Close Program**.

**Edit**

- **Add Track** / **Delete Track**.
- **Combine Tracks…**: merge several instrument lines into one.
- **Separate Channels…**: split one track that holds several instruments into one track each.
- **Separate Hands…**: for piano music, sort the notes into a right-hand staff and a left-hand staff (section 7).
- **Fix Chords…**: find chords that no hand could play and choose what to do about them (section 7).

**View**: open the **Score View** (Ctrl+1), **Piano Roll** (Ctrl+2), **MIDI List** (Ctrl+3) or **Mixer**.

**Setup**

- **MIDI I/O Info**: shows (I/O means Input/Output) what the program found for sound output and for a connected keyboard.
- **MIDI Output Device…**: choose which "synthesizer" makes the sound (section 9).

**Song Settings**: Quantization and Grace Cleanup choices, **Quantize…** (Ctrl+Q), **Score Setup…** (Ctrl+G), **Song Elements…** (tempo and time signature), **Set Key Signature…**, and **Rationalize Score…** (Ctrl+R).

**Help**: **User Guide (PDF)** opens this guide (Portable Document Format, PDF). **About…** shows the version number and credits. The same version appears in the title bar.

## The track list

The list of instruments is a panel that can be **docked** (fixed in the main window) or **floated** (pulled out into its own window). **Right-click an instrument** for a menu: open it in Score, Roll or List; **Rename**; **Delete**; **Mute/Unmute** (silence it); **Solo/Unsolo** (hear only this one); **Arm for Record**.

# 5. Four ways of looking at the music

- **Score (♫)**: ordinary sheet music, one staff per instrument. A piano gets two staffs joined together (right hand on top, left hand below). This is the view most people use.
- **Piano Roll (♬)**: each note is a bar. Higher notes are higher on the screen; longer notes are longer bars. Easy to see exactly when each note starts and stops.
- **MIDI List (📋)**: a plain table of every note in the file, with its measure. For checking details.
- **Mixer (🎚)**: a volume control, a Mute and a Solo for each instrument, and a place to choose its instrument sound. If there are more instruments than fit, use the scroll bars at the bottom and right of the Mixer to reach them all (including the drums).

## Buttons at the top of the Score

| Button | What it does |
|---|---|
| **Zoom + / Zoom −** | Make the score bigger or smaller. |
| **Fit Width** | Squeeze or stretch the whole piece to the width of the window. |
| **Fit Width + / −** | Show one more or one fewer measure across the screen. |
| **Space + / Space −** | Move the staffs **further apart or closer together vertically**. Use it when high notes on one staff run into low notes on the staff above. |
| **Follow: Page / Follow: Smooth** | While playing, **Page** keeps the score still while the red line crosses a page of measures, then turns to the next page. **Smooth** slides the score under the red line. Page is the normal choice. |

**If your computer is slow:** Smooth movement needs a fast screen redraw. If the program finds your computer cannot keep up, it switches to Page by itself and shows a message saying so. Click **OK**; nothing is wrong. You can switch back to Smooth, and the program will not interrupt you again.

## The editing tabs

Under the buttons there is a row of tabs. Click a tab, then click on the score:

- **Note/Rest**: choose Note or Rest and a length, then click on the staff to add one. **Right-click a note to delete it.** "Apply to Selection" changes the length of notes you have selected.
- **Accidental**: choose a sharp, flat or natural, then click a note.
- **Dynamics**: choose how loud (such as p, mf, f), then click below the staff to place it.
- **Articulation**: choose a style such as staccato (short and detached), then click a note to switch it on or off.
- **Measures**: right-click any measure for **Insert**, **Delete** or **Cut**.
- **Select**: drag a box around several notes to select them, or click one. **Delete Selected** removes them. **Clear Selection** un-selects.

**Wrong staff?** Select the notes, right-click, and choose **Move … selected note(s) to upper staff** or **to lower staff**. Only the staff changes; the sound does not.

# 6. Setting the speed, time and key

- **Speed**: change the Beats Per Minute (BPM) number in the top row.
- **Song Settings ▸ Song Elements…**: set the tempo and the **time signature** (for example 4/4 or 3/4).
- **Song Settings ▸ Set Key Signature…**: choose the key (the sharps or flats at the start of each staff).
- **Score Setup… (Ctrl+G)**: a panel for how the measures are laid out. **Auto-detect BPM + Meter** estimates the beat and time signature. **Clean up this measure** and **Clean up all measures** tidy how the notation is drawn without changing how the music sounds. **Bake** turns the cleaned-up look into the actual notes, so what you hear matches the score. Baking changes the notes, so use **Save As…** first.
- **Quantize… (Ctrl+Q)**: pulls notes that were played slightly early or late onto an even beat grid. Choose the grid (quarter, eighth, sixteenth, thirty-second notes), how strongly to snap, and which measures. This **changes when notes play**.

# 7. Making a score easier to read

A Musical Instrument Digital Interface (MIDI) file made by playing a piano is "human": the notes are a little early or late, one long list holds both hands, and a few chords look too wide for a hand. The tools below get a readable score out of that. **Remember rule 2: the recording is correct.** These tools adjust the score, and each can be undone.

## Separate Hands (piano music)

**Edit ▸ Separate Hands…** sorts the notes into a **right-hand staff** and a **left-hand staff**, the way a printed piano score looks.

- It asks two questions about the player's hand:
    - **Widest stretch of one hand**, in semitones (a semitone is the distance between neighbouring piano keys; 12 is one octave). The standard value is **12**. It can be raised for large hands (up to 30) or lowered for small hands such as a child's (down to 6).
    - **Most notes one hand plays at once.** The standard value is **5**, one per finger. It cannot go above 5. Lower it if a hand is injured, for example to 4, or to 1 for one finger.
- It decides by pitch and by how far a hand can reach.
- **Chords of more than five notes, or too wide.** No hand has six fingers. When the split is finished, the program tells you how many measures hold chords one hand of that size cannot play, and **asks whether to open Fix Chords**. Fix Chords then offers, chord by chord, to give the spare notes to the other hand wherever that hand can play them. You choose; nothing moves on its own.
- **It does not change how the music sounds.** Every note keeps its original start, length and loudness. Pedal markings are kept. Other instruments in the file, such as drums and bass, are left exactly as they were. Only the piano part is split.
- If the file is already on two staffs, the program asks before splitting it again.
- To go back, use **File ▸ Undo Correction**.

## Fix Chords

After the hands are separated, some chords may still be wider than one hand can hold (for example 16 semitones) or have more than five notes. **Edit ▸ Fix Chords…** asks the same two hand questions as Separate Hands (stretch, and most notes at once) and lists them, one line per chord, with the measure number. For each line you choose what to do:

- **Move** a note to the other hand, when that note fits within the other hand's stretch and that hand is free. Nothing is lost. This is the first thing offered, before any note is left out.
- **Leave out** (delete) a note.
- **Keep** the chord as it is.
- **Roll signs.** Four or more notes struck one after another very quickly are a *rolled chord*. These are shown separately, and you can accept the roll sign instead of changing the notes.

How to use the window:

1. Click a line to select it. The measure is highlighted in the score.
2. **Hear original** and **Hear changed** play that measure both ways.
3. Press **Y** to accept the change shown, **N** to leave it alone, or **Change…** to choose per note.
4. **Apply my Y choices** makes the changes. There are also **Accept all** buttons for roll signs, for move/leave-out, and for everything remaining.

Nothing changes until you apply, and **Undo Correction** takes it back.

## Rationalize Score

**Song Settings ▸ Rationalize Score… (Ctrl+R)** works out the hands, the measures and the time signature for a human-played file in one step.

At the bottom is a green tick box: **Keep the original sound (recommended)**. With it ticked, every note keeps its original start, length and loudness, the speed is never changed, and other instruments are untouched. With it **un-ticked**, notes are snapped and shortened to match the tidied score, so the sound changes. Choose that only if you want the cleaned version to be what you hear.

| Setting | What it means |
|---|---|
| **Auto-detect tempo** / tempo box | Estimates the real speed of the performance (only when "Keep the original sound" is off). |
| **Time-Sig-auto-detect** and the two number boxes | Guesses the time signature, or lets you type it. |
| **Preserve existing hand tracks** | If the file already has a right-hand and a left-hand track, keep them as they are. |
| **Hold notes while the sustain pedal is down** | Makes notes last as long as the pedal holds them (only when "Keep the original sound" is off). |
| **Quantize strength / grid** | How firmly notes snap to the beat grid (only when "Keep the original sound" is off). |
| **Arpeggio window** | How close together in time notes must be to count as one chord. It is measured in *ticks*, the tiny time steps inside a MIDI file. The standard value is **0, which means automatic**: the program uses about 20 thousandths of a second (1/50 of a second) at the speed of your piece. A larger number gathers more spread-out notes into one chord. A smaller number keeps them as separate notes. Leave it at 0 unless a fast run of notes is being merged into a chord, or a rolled chord is not being recognized. |
| **Rest threshold**, **maximum hand span** | Fine-tuning for very short rests and for how far one hand can reach. |
| **Whole piece** / measure range | Rationalize everything, or only some measures. |

The buttons are **Preview** (run it and play the result), **Accept** (keep it), **Discard** (throw it away and return to your original), **Save copy…** and **Close**. Hover the mouse over any setting for a short explanation.

# 8. Printing a score

**File ▸ Print Score (via LilyPond)…** makes a printable Portable Document Format (PDF) file with LilyPond, a free music-engraving program. **File ▸ Export LilyPond (.ly)…** saves the LilyPond file if you want to use it elsewhere.

**Getting LilyPond.** LilyPond for Windows is not an installer, just a folder. The first time you print, if the program cannot find it, a window offers three choices:

- **Download and set it up for me** (Windows). The program downloads LilyPond (about 45 megabytes) into your own user folder and starts using it. You do not need to do anything else.
- **I already have it – find lilypond…** Pick `lilypond.exe` from the `bin` folder of a LilyPond you already have. The program remembers it.
- **Not now.**

On Linux, install LilyPond with your package manager (`sudo apt install lilypond`, or `sudo pacman -S lilypond`). On a Mac, use `brew install lilypond`.

The program also looks in your home folder, Downloads, and Program Files, so a LilyPond you unpacked yourself is usually found automatically.

**What the printed score shows**

- The name of each instrument appears in small print **above its staff, at the left margin**, on every system. The first system has the full name; later systems have a short one (for example "Violin" then "Vln."). Staffs that would share a name are numbered ("Violin 1", "Violin 2").
- A name you typed (in the track list or the Mixer) is printed as you typed it. A default label such as "Track 3" is replaced by the instrument sound chosen for that track, and the drum track prints as "Drums".
- Measure numbers are printed above the top staff and apply to every staff beneath them. The vertical barlines run through all the staffs, so you can follow one measure straight down the page. Tick or untick **Show measure numbers** in the print options.

# 9. Something not working?

**I hear no sound.** Open **Setup ▸ MIDI Output Device…** (MIDI is Musical Instrument Digital Interface) and pick another choice. **FluidSynth (built in)** is usually best on both Windows and Linux. **Setup ▸ MIDI I/O Info** shows what the program found.

**The drums sound wrong.** Open the **Mixer** and turn the drum track's volume down, or check that the drums are on **channel 10**, which is the drum channel.

**The program takes a long time to start.** It loads all the instrument sounds first. An older computer can take about 12 seconds. This is normal.

**The sound or the red line stutters.** Use **Follow: Page** (it is the default). If you chose Smooth and your computer is slow, the program switches to Page by itself.

**Printing says LilyPond was not found.** Use the window that appears (section 8).

**The program will not start on Windows.** Make sure you extracted the whole zip (**Extract All**), or use the installer instead.

**The red line ran off the screen.** Press **⏹ Stop**, then **⏮**, then Play again. If it keeps happening, please tell me exactly what you did just before.

**I want to keep the original.** Always use **File ▸ Save As…** and give a new name.

**Anything else.** Email me. Please say which computer you use (Windows 10, Windows 11, or the name of your Linux), what you clicked, and what you saw. A photo of the screen helps.

# Words used in this guide

- **Measure** (also called a **bar**): one short section of music between two vertical lines on the staff.
- **Barline**: the vertical line between measures.
- **BPM**: Beats Per Minute, the speed.
- **Staff** (plural **staffs**): the five lines that the notes sit on. One per instrument, or two for the piano.
- **Treble and bass clef**: the symbols at the start of a staff. Treble is for higher notes, usually the right hand; bass is for lower notes, usually the left.
- **Time signature**: two numbers such as 4/4 that say how many beats are in each measure.
- **Key signature**: the sharps or flats at the start of the staff that say which notes are raised or lowered throughout.
- **Tempo**: the speed of the music.
- **Track**: one instrument's line of music in the file.
- **Quantize**: nudge notes onto an even beat grid.
- **Staccato**: a short, detached note.
- **Sustain pedal**: the piano pedal that lets notes keep ringing after the key is released.
- **Chord**: several notes played together.
- **Rolled chord**: a chord whose notes are struck one after another very quickly, like a harp.
- **Arpeggio**: the notes of a chord played one after another.
- **Tie**: a curved line joining two notes of the same pitch into one longer note.
- **Dynamics**: how loud or soft: p (soft), mf (medium loud), f (loud).
- **MIDI**: Musical Instrument Digital Interface, the standard way instruments and computers exchange music.
- **PDF**: Portable Document Format, a file that looks the same on every computer.
- **Synthesizer**: the thing that turns the MIDI instructions into sound.
- **LilyPond**: the free program that draws the printed score.

---

*MIDI Studio is free software (MIT license, from the Massachusetts Institute of Technology), made to support the Sterling Lions Club of Virginia. Comments and corrections are welcome.*
