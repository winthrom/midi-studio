# MIDI Studio User Guide

*For version 22ze-139. A program for turning a MIDI file into readable sheet music, listening to it, and tidying it up.*

## 1. What this program does

A **MIDI file** (ending in `.mid`) is not a recording. It is a list of instructions: "play this note, this loud, starting now, for this long." Most music players can play one. MIDI Studio reads that list and **draws it as sheet music**. You can then play it, watch a red line move across the score, zoom in, change the tempo, mute instruments, and make the score easier to read.

You do not need to read music to use the program, but it helps. Words you may not know are explained in the [word list](#9-words-used-in-this-guide) at the end.

**The most important rule:** the program never changes your original file unless you **Save** over it. When in doubt, use **File ▸ Save As…** and give the new version a new name.

## 2. Your first five minutes

1. Start the program. A small window says **Starting MIDI Studio…** while the sounds load. On an older computer this can take about 12 seconds. On a fast one you may not see it at all.
2. A few small windows appear. Read them and click **Continue**.
3. Click **File** (upper left), then **Open…** and choose a `.mid` file.
4. The music appears as a score. Each instrument gets its own line, called a **staff**. The name of each instrument is written at the left.
5. Click **▶ Play** (or press the **space bar**). You hear the music and a red line moves across the score. Click **⏹ Stop** to stop.

That is all you need to listen. Everything else in this guide is optional.

## 3. The main window

### The row of buttons across the top

| Button | What it does |
|---|---|
| **⏮** | Go back to the beginning. |
| **◀◀  ▶▶** | Jump back or forward by one measure. |
| **▶ Play** / **⏹ Stop** | Start (or pause) and stop the music. The space bar does the same as Play. |
| **⏺ Rec** | Record from a MIDI keyboard connected to the computer. You do not need this just to listen. |
| **Click: OFF / ON** | Turns a metronome click on or off during playback. |
| **+ Track** | Adds a new empty instrument line. |
| **♫ Score**, **♬ Roll**, **📋 List**, **🎚 Mixer** | Open the four ways of looking at the music (see section 4). |
| **BPM** | The speed in beats per minute. A higher number is faster. |
| **Meas … Beat …** | Shows where you are in the piece. |
| **Sel … – … ▶ Sel** | Type a first and last measure, then click **▶ Sel** to play only that part. Useful for practising one passage. |

### The menus

**File**

- **New**, **Open…**, **Close Piece**: start fresh, open a file, or close the current one.
- **Save**, **Save As…**: write the music to a MIDI file. Use **Save As…** to keep your original safe.
- **Export MIDI…**: the same as Save As.
- **Save as .musicxml (standard)…**: a format that notation programs such as MuseScore can open.
- **Open in MuseScore (via MIDI)…**: if you have MuseScore installed, sends the music there.
- **Export LilyPond (.ly)…** and **Print Score (via LilyPond)…**: for printing a high-quality score. These need the free LilyPond program installed.
- **Undo Correction** / **Redo Correction** (Ctrl+Z / Ctrl+Y): step back or forward through the corrections you made.
- **Close Program**.

**Edit**

- **Add Track** / **Delete Track**.
- **Combine Tracks…**: merge several instrument lines into one.
- **Separate Channels…**: split one track that holds several instruments into one track each.
- **Separate Hands…**: for piano music, sort the notes into a right-hand staff and a left-hand staff. See section 6.

**View**: open the **Score View** (Ctrl+1), **Piano Roll** (Ctrl+2), **MIDI List** (Ctrl+3) or **Mixer**.

**Setup**

- **MIDI I/O Info**: shows what the program found for sound output and for a connected keyboard.
- **MIDI Output Device…**: choose which "synthesizer" makes the sound. See section 8 if you hear nothing.

**Song Settings**: Quantization and Grace Cleanup choices, **Quantize…** (Ctrl+Q), **Score Setup…** (Ctrl+G), **Song Elements…** (tempo and time signature), **Set Key Signature…**, and **Rationalize Score…** (Ctrl+R). See sections 5 to 7.

**Help ▸ About…**: the version number, credits, and a link to support the Sterling Lions Club. The same version number is shown in the title bar of the window.

### The track list

The list of instruments is a panel that can be **docked** (fixed in the main window) or **floated** (pulled out into its own window). **Right-click an instrument** for a menu: open it in Score, Roll or List; **Rename**; **Delete**; **Mute/Unmute** (silence it); **Solo/Unsolo** (hear only this one); **Arm for Record**.

## 4. Four ways of looking at the music

- **Score (♫)**: ordinary sheet music, one staff per instrument. A piano gets two staffs joined together (right hand on top, left hand below). This is the view most people use.
- **Piano Roll (♬)**: each note is a bar. Higher notes are higher on the screen; longer notes are longer bars. Easy to see exactly when each note starts and stops.
- **MIDI List (📋)**: a plain table of every event in the file. For checking details.
- **Mixer (🎚)**: a volume control for each instrument.

### Buttons at the top of the Score

| Button | What it does |
|---|---|
| **Zoom + / Zoom −** | Make the score bigger or smaller. |
| **Fit Width** | Squeeze or stretch the whole piece to the width of the window. |
| **Fit Width + / −** | Show one more or one fewer measure across the screen. |
| **Space + / Space −** | Move the staffs **further apart or closer together vertically**. Use it when high notes on one staff run into low notes on the staff above. The notes do not change size. |

### The editing tabs

Under the buttons there is a row of tabs. Click a tab, then click on the score:

- **Note/Rest**: choose Note or Rest and a length, then click on the staff to add one. **Right-click a note to delete it.** "Apply to Selection" changes the length of notes you have selected.
- **Accidental**: choose a sharp, flat or natural, then click a note.
- **Dynamics**: choose how loud (such as p, mf, f), then click below the staff to place it.
- **Articulation**: choose a style such as staccato (short and detached), then click a note to switch it on or off.
- **Measures**: right-click any measure for **Insert**, **Delete** or **Cut**.
- **Select**: drag a box around several notes to select them, or click one. **Delete Selected** removes them. **Clear Selection** un-selects.

## 5. Setting the speed, time and key

- **Speed**: change the **BPM** number in the top row.
- **Song Settings ▸ Song Elements…**: set the tempo and the **time signature** (for example 4/4 or 3/4).
- **Song Settings ▸ Set Key Signature…**: choose the key (the sharps or flats at the start of each staff).
- **Score Setup… (Ctrl+G)**: a panel for how the measures are laid out. It can detect the beat pattern and meter, and it has **Clean up this measure** and **Clean up all measures** buttons for tidying the notation of one measure or of all of them. **Bake** turns the cleaned-up look into the actual notes, so what you hear matches the score. Baking changes the notes, so use **Save As…** first.
- **Quantize… (Ctrl+Q)**: pulls notes that were played slightly early or late onto an even beat grid. Choose the grid (quarter, eighth, sixteenth, thirty-second notes), how strongly to snap, and which measures. This **changes when notes play**.

## 6. Piano music: Separate Hands

A MIDI file of a piano piece is often one long list of notes. **Edit ▸ Separate Hands…** sorts them into a **right-hand staff** and a **left-hand staff**, the way a printed piano score looks.

- It decides by pitch and by how far a hand can reach.
- **It does not change how the music sounds.** Every note keeps its original start, length and loudness. Pedal markings are kept. Other instruments in the file, such as drums and bass, are left exactly as they were. Only the piano part is split.
- To go back, open **Song Settings ▸ Rationalize Score…** and click **Discard**.

## 7. Rationalize Score

A MIDI file made by playing a piano is "human": the notes are a little early or late, and it is hard to turn into tidy sheet music. **Song Settings ▸ Rationalize Score… (Ctrl+R)** prepares it for reading. It works out the hands, the measures and the time signature.

### The recommended way (leave the green box ticked)

At the bottom of the window is a green tick box: **Keep the original sound (recommended)**. With it ticked:

- Every note keeps its original start, length and loudness. **The music sounds exactly as it did.**
- The speed is never changed. Other instruments are not touched.
- The program works out the hands and the bars; the score window tidies the way it is drawn.

With it **un-ticked**, the old behaviour returns: notes are snapped and shortened to match the tidied score, so the sound changes. Choose this only if you want the cleaned version to be what you hear.

### The settings

| Setting | What it means |
|---|---|
| **Auto-detect tempo** / tempo box | Estimates the real speed of the performance (only used when "Keep the original sound" is off). |
| **Time-Sig-auto-detect** and the two number boxes | Guesses the time signature, or lets you type it. |
| **Preserve existing hand tracks** | If the file already has a right-hand and a left-hand track, keep them as they are. |
| **Hold notes while the sustain pedal is down** | Makes notes last as long as the pedal holds them, but only while the pedal is down (only when "Keep the original sound" is off). |
| **Quantize strength / grid** | How firmly notes snap to the beat grid (only when "Keep the original sound" is off). |
| **Arpeggio window** | Notes closer together than this are treated as one chord. |
| **Rest threshold**, **maximum hand span** | Fine-tuning for very short rests and for how far one hand can reach. |
| **Whole piece** / measure range | Rationalize everything, or only some measures. |

### The buttons

- **Preview**: runs it and shows the result in the score. You can play it.
- **Accept**: keeps the result.
- **Discard**: throws it away and returns to your original.
- **Save copy…**: saves the result under a new name.
- **Close**: closes the window.

Hover the mouse over any setting to see a short explanation.

## 8. Something not working?

**I hear no sound.** Open **Setup ▸ MIDI Output Device…** and pick another choice. On Windows, **FluidSynth (built in)** is usually best. On Linux, pick **FluidSynth (built in)** too. Click **Setup ▸ MIDI I/O Info** to see what the program found.

**The program takes a long time to start.** It loads all the instrument sounds first. An older computer can take about 12 seconds. This is normal. The "Starting…" window only appears on slower computers.

**Windows says "Windows protected your PC".** Click the small faint words **More info**, then the **Run anyway** button. You only need to do this once for each program.

**The program will not start on Windows.** Make sure you extracted the whole zip (**Extract All**) and left the `_internal` folder next to `MIDI-Studio.exe`.

**The red line ran off the screen.** Press **⏹ Stop**, then **⏮**, then Play again. If it happens again, please tell me exactly what you did just before.

**I want to keep the original.** Always use **File ▸ Save As…** and give a new name.

**Anything else.** Email me. Please say which computer you use (Windows 10, Windows 11, or the name of your Linux), what you clicked, and what you saw. A photo of the screen helps.

## 9. Words used in this guide

- **Bar / measure**: one short section of music between two vertical lines on the staff.
- **BPM**: beats per minute, the speed.
- **Staff (plural staffs)**: the five lines that the notes sit on. One per instrument, or two for the piano.
- **Treble and bass clef**: the symbols at the start of a staff. Treble is for higher notes, usually the right hand; bass is for lower notes, usually the left.
- **Time signature**: two numbers such as 4/4 that say how many beats are in each measure.
- **Key signature**: the sharps or flats at the start of the staff that say which notes are raised or lowered throughout.
- **Tempo**: the speed of the music.
- **Track**: one instrument's line of music in the file.
- **Quantize**: nudge notes onto an even beat grid.
- **Staccato**: a short, detached note.
- **Sustain pedal**: the piano pedal that lets notes keep ringing after the key is released.
- **Chord**: several notes played together.
- **Arpeggio**: the notes of a chord played one after another.
- **Tie**: a curved line joining two notes of the same pitch into one longer note.
- **Dynamics**: how loud or soft: p (soft), mf (medium loud), f (loud).
- **Synthesizer**: the thing that turns the MIDI instructions into sound.

---

*MIDI Studio is free software (MIT license). It is made to support the Sterling Lions Club of Virginia. Comments and corrections are welcome.*
