---
title: MIDI Studio User Guide
subtitle: For MIDI Studio 0.3.3
---

A program for turning a MIDI file into readable sheet music, listening to it, tidying it up and printing it.

## Contents

Click a line to jump to it.

- [1. What this program does](#what-this-program-does)
- [2. Getting the program](#getting-the-program)
    - [Windows 10 or 11 (64-bit)](#windows-10-or-11-64-bit)
    - [Linux (64-bit)](#linux-64-bit)
    - [macOS (Experimental)](#macos-experimental)
    - [Removing the program](#removing-the-program)
    - [Where the downloads are](#where-the-downloads-are)
- [3. Your first five minutes](#your-first-five-minutes)
- [4. The main window](#the-main-window)
    - [The row of buttons across the top](#the-row-of-buttons-across-the-top)
    - [The menus](#the-menus)
    - [The track list](#the-track-list)
- [5. Four ways of looking at the music](#four-ways-of-looking-at-the-music)
    - [Buttons at the top of the Score](#buttons-at-the-top-of-the-score)
    - [The editing tabs](#the-editing-tabs)
- [6. Setting the speed, time, key and title](#setting-the-speed-time-key-and-title)
    - [When the measures are the wrong length](#when-the-measures-are-the-wrong-length)
    - [Quantize](#quantize)
- [7. Making a score easier to read](#making-a-score-easier-to-read)
    - [Hand-made files and performances](#hand-made-files-and-performances)
    - [Separate Hands (piano, organ, accordion…)](#separate-hands-piano-organ-accordion)
    - [Fix Chords](#fix-chords)
    - [Fix Measures](#fix-measures)
    - [Remove Short Rests](#remove-short-rests)
    - [Rationalize Score](#rationalize-score)
- [8. Printing a score](#printing-a-score)
- [9. Something not working?](#something-not-working)
- [10. Telling me about a problem](#telling-me-about-a-problem)
- [Words used in this guide](#words-used-in-this-guide)

# 1. What this program does

A **Musical Instrument Digital Interface (MIDI) file** (ending in `.mid`) is not a recording. It is a list of instructions: "play this note, this loud, starting now, for this long." Most music players can play one. MIDI Studio reads that list and **draws it as sheet music**. You can then play it, watch a red line move across the score, zoom in, change the tempo, mute instruments, tidy the score, and print it.

You do not need to read music to use the program, but it helps. Words you may not know are explained in the [word list](#words-used-in-this-guide) at the end.

**Two rules to remember**

1. **Your original file is safe.** The program never changes your file unless you **Save** over it. When in doubt, use **File ▸ Save As…** and give the new version a new name.
2. **The recording is correct; the score is the program's reading of it.** If a score looks odd (a chord no hand could play, a note on the wrong staff, a strange rest), the music was almost certainly played correctly. The correction tools in this guide change how the *score is drawn*. They do not "fix" the person who played. Everything they do can be undone with **Edit ▸ Undo**.

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

## macOS (Experimental)

**Please read this first.** The Mac versions are **experimental**. They have been built but not yet tested on every kind of Mac, and they are **not signed by Apple** (Apple charges a yearly fee for that, and this program is free). Everything in the program should work, but expect rough edges, and please tell me what you find (**Help ▸ Send a Problem Report…**, section 10).

**Testers wanted.** The Apple Silicon version is planned to be tested on a MacBook Pro with an M1 chip (Apple Silicon). The Intel version still needs a tester; if you have an Intel Mac, please get in touch at **winthrom@hotmail.com**.

**Which one do you need?** Click the Apple menu (top left), then **About This Mac**.

- If it says **Chip: Apple M1** (or M2, M3, M4…), download **MIDI-Studio-macos-apple-silicon.zip**.
- If it says **Processor: Intel**, download **MIDI-Studio-macos-intel.zip**. This is the one for older Macs.

**Installing.** Double-click the zip to unpack it. Drag **MIDI Studio** into your **Applications** folder. The first time, do **not** double-click it. **Right-click** (or hold Control and click) the program, choose **Open**, then click **Open** again in the box that appears. On a recent macOS you may instead see "MIDI Studio cannot be opened"; click **Done**, open **System Settings ▸ Privacy & Security**, scroll down to the message about MIDI Studio and click **Open Anyway**. After that it opens normally.

If macOS says the program is "damaged", open **Terminal** and type `xattr -dr com.apple.quarantine /Applications/MIDI\ Studio.app` and press Return. (This only removes the "downloaded from the internet" mark.)

**Printing** needs LilyPond: install it with `brew install lilypond` (section 8).

## Removing the program

- **Windows installer:** **Settings ▸ Apps**, or **Uninstall MIDI Studio** in the Start menu. If MIDI Studio had downloaded LilyPond for you, the uninstaller asks whether to remove it too (the standard answer is Yes), and then whether to remove your saved settings (the standard answer is No). A LilyPond that you installed or unpacked yourself is never touched.
- **Windows zip:** delete the folder you extracted. If MIDI Studio downloaded LilyPond, it is in `%LOCALAPPDATA%\MIDI-Studio\ly` (type that into the address bar of a File Explorer window); delete that folder too if you like.
- **Linux:** `bash uninstall-linux.sh`, or delete the AppImage file.
- **Mac:** drag **MIDI Studio** from Applications to the Trash.

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

- **New**, **Open…**, **Close Piece**: start fresh, open a file, or close the current one. Closing a piece also closes the correction windows that belonged to it.
- **Save**, **Save As…**: write the music to a MIDI file. **Save As…** suggests a new name ending in **-edited**, so your original keeps its own name. If you choose **Save** on a file you opened from disk, the program asks first: **Yes** = Save As (keeps the original safe), **No** = replace the original, **Cancel** = do nothing. Every saved file carries a small note, "Saved by MIDI Studio (version); sound as recorded", so you can tell it from an unedited file. If some notes were lengthened in the score only (for example by **Remove Short Rests**), the program asks whether to save the file **to match the score** or keep the **sound exactly as recorded** (the usual choice). Choosing "as recorded" means that if you reopen the file later, those score-only tidy-ups are not remembered; run them again.
- **Export ▸**: **MusicXML** (a format that notation programs such as MuseScore can open; for **Braille** music, see the note after this list), **Open in MuseScore (via MIDI)…** (if you have MuseScore installed), and **LilyPond (.ly)…**.
- **Print Score (via LilyPond)…**: for printing a high-quality score (section 8).

**Braille music.** MIDI Studio does not make Braille itself. A possible route is to export **MusicXML** and open it in a Braille-music tool, for example the Braille plugin of OpenSheetMusicDisplay (<https://github.com/opensheetmusicdisplay/opensheetmusicdisplay/blob/feat/braille/src/Plugins/Braille/UserGuide.md>). **This has not been tested with MIDI Studio's files yet.** If you read Braille music and can try it, please tell me what happened.
- **Close Program**.

**Edit**

- **Undo** / **Redo** (Ctrl+Z / Ctrl+Y): step back or forward through the changes you made, one at a time.
- **Editing tabs On/Off**: turns the Score's editing tabs on or off (section 5).
- **Add Track** / **Delete Track**.
- **Combine Tracks…**: merge several instrument lines into one.
- **Separate Channels…**: split one track that holds several instruments into one track each.

**Corrections**: the tools that tidy a recorded performance into a readable score (section 7), in the order you would usually use them.

- **Quantize…** (Ctrl+Q).
- **Separate Hands…**: for two-handed keyboard instruments (piano, organ, accordion…), sort the notes into a right-hand staff and a left-hand staff.
- **Rationalize Score…** (Ctrl+R).
- **Remove Short Rests…**: close the tiny gaps between notes.
- **Clean Up Measures…**: opens the Score Settings window, where the cleanup buttons are.
- **Fix Chords…**: find chords that no hand could play and choose what to do about them.
- **Fix Measures…**: find staves whose music runs past a barline, and fix them one measure at a time.
- **Quantization ▸** and **Grace Cleanup ▸**: the grid size, and whether to delete extremely short notes. Grace Cleanup starts **Off**, because it deletes notes.

**Score Settings**: **Score Settings…** (Ctrl+G), where you set the title, composer, speed, time signature and the number of measures (section 6), and **Key Signature…**.

**View**: open the **Score View** (Ctrl+1), **Piano Roll** (Ctrl+2), **MIDI List** (Ctrl+3) or **Mixer**.

**Setup**

- **MIDI I/O Info**: shows (I/O means Input/Output) what the program found for sound output and for a connected keyboard.
- **MIDI Output Device…**: choose which "synthesizer" makes the sound, and its volume (section 9).

**Help**

- **User Guide (PDF)** opens this guide (Portable Document Format, PDF).
- **Where do I find…?** Type a word such as *speed*, *print* or *title* and it tells you which menu has it. Press **Enter**, or double-click a line, to open this User Guide at that topic. (In a web browser's PDF viewer it jumps to the section; another PDF program may open at the first page, and the Contents at the top of this guide will take you there.)
- **Send a Problem Report…** and **Tester Log**: see section 10.
- **About…** shows the version number and credits. The same version appears in the title bar.

When a correction window or a question box opens, it always appears on top of the windows that were open before it, so it cannot be hidden behind them.

## The track list

The list of instruments is a panel that can be **docked** (fixed in the main window) or **floated** (pulled out into its own window). **Right-click an instrument** for a menu: open it in Score, Roll or List; **Rename**; **Delete**; **Mute/Unmute** (silence it); **Solo/Unsolo** (hear only this one); **Arm for Record**.

# 5. Four ways of looking at the music

- **Score (♫)**: ordinary sheet music, one staff per instrument. A two-handed keyboard instrument (piano, organ, accordion…) gets two staffs joined together (right hand on top, left hand below). This is the view most people use.
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
| **Pedal marks** | A tick box. Shows or hides the "Ped." marks that come from the recorded sustain pedal. It only changes what the Score draws. |
| **Short rests** | A tick box. Normally the score hides rests shorter than a quarter note, so a performance does not look cluttered. Tick it to see the short rests too, down to a thirty-second note (section 7). |
| **Follow: Page / Follow: Smooth** | While playing, **Page** keeps the score still while the red line crosses a page of measures, then turns to the next page. **Smooth** slides the score under the red line. Page is the normal choice. |

**If your computer is slow:** Smooth movement needs a fast screen redraw. If the program finds your computer cannot keep up, it switches to Page by itself and shows a message saying so. Click **OK**; nothing is wrong. You can switch back to Smooth, and the program will not interrupt you again.

## The editing tabs

Under the buttons there is a row of tabs. When you open a piece, the editing tabs (**Note/Rest**, **Accidental**, **Dynamics**, **Articulation**) are **grayed out**, so a stray click cannot change anything. Click the **Select** tab (the last one) to turn editing on. You can turn it off again with **Turn editing off** on the Select tab, or by right-clicking the Select tab. Opening another file or closing the piece turns editing off again.

**How editing works.** Clicking a note, or dragging a box around several, only **selects** them (they turn blue). Nothing changes yet. Then pick a value on a tab, and press **Apply to Selection**. The button is gray until some notes are selected and a value is picked. If you have picked values on several tabs, they are all applied together as **one step**, and **Edit ▸ Undo** takes them all back. No tab starts with a value picked, and **Clear** on each tab un-picks it. Pressing **Esc** un-selects the notes.

- **Note/Rest**: pick a length, for example *quarter*, *dotted eighth*, *double-dotted quarter* or *32nd*. The selected notes take that length. A shorter note leaves a rest after it. If a longer note would run into the next note, the program asks what you want: **Cut off** (stop at the next note), **Hold** (keep the full length and let the other notes play over it, such as a held bass note under moving chords) or **Push later** (move the music after it later to make room). A note never runs past the end of its measure. Notes tied across a barline are skipped; the message says how many. This changes the sound, because the note really is longer or shorter.
- **Add notes by clicking** (on the Note/Rest tab, off at the start): with this ticked, clicking the staff adds a note, or, with **Rest** chosen, clicking a note turns it into a rest. Clicking a rest that is already drawn does nothing.
- **Accidental**: pick a sharp, flat or natural. The selected notes are changed to that.
- **Dynamics**: pick how loud (such as p, mf, f). It is placed at the first selected note.
- **Articulation**: pick a style such as staccato (short and detached). Applying the same style again to the same notes takes it off.
- **Measures**: right-click any measure for **Insert**, **Delete** or **Cut**.
- **Move**: moves the selected notes earlier or later by a step you choose (from a 32nd note up to a whole note). Choose whether to move **these notes only**, **these and the rest of this staff**, or **these and the rest of every staff**. A rest is just the gap between notes, so the rests around the moved notes grow or shrink to match. Moving earlier stops at the previous note. **Remove Rest…** works on a rest you have selected (click it): it can **lengthen the note before it**, **close the gap in this staff** (the later notes move earlier), or **close the gap in every staff**. These really change the music, one **Undo** step each.
- **Select**: **Delete Selected** removes the selected notes. **Clear Selection** un-selects. **Move to Upper Staff** and **Move to Lower Staff** move them to the other hand's staff.

**Wrong staff?** Select the notes, right-click, and choose **Move … selected note(s) to upper staff** or **to lower staff**. Only the staff changes; the sound does not.

# 6. Setting the speed, time, key and title

Open **Score Settings ▸ Score Settings…** (Ctrl+G). The top part, **Global Calibration**, holds:

- **Title** and **Composer**: printed at the top of the score when you print (section 8) and saved inside the MIDI file. The title starts as the file's name; change it to anything you like.
- **Time Signature**: type it (for example 4/4 or 3/4) and click **Apply**.
- **Key Signature ▸ Change…**: choose the key (the sharps or flats at the start of each staff). The window also offers the program's guess.
- **BPM**: the Beats Per Minute number, plus **Apply**. This sets one speed for the whole piece.
- **Speed (%)**: makes the whole piece play **faster or slower** in the saved file. 125 plays 25% faster; 80 plays 20% slower. Unlike BPM, it keeps every tempo change in the file, scaled together. No note moves.
- **Measures wanted**: see below.
- **Auto-detect BPM + Meter**: estimates the beat and the time signature.

Below that, **Clean up this measure** and **Clean up all measures** tidy how the notation is drawn, and **Bake** turns the cleaned-up look into the actual notes, so what you hear matches the score. Baking changes the notes, so use **Save As…** first.

## When the measures are the wrong length

A piece played slowly can show **two or three printed measures for one measure of the real score**. The speed (BPM) does not fix that, because the number of beats in a measure never changes. **Measures wanted** does. Type the number of measures the printed score has (for example 125) and look at the line under the box: it says how many measures you would get and how the notes will sit.

- **The sound does not change.** Only the barlines move.
- Notes are never moved. If the new measures cut a chord in half, run **Clean Up Measures** afterwards.
- **Quantize afterwards** (tick box, off by default) quantizes the notes right after the change. It is a second Undo step.
- The preview also names nearby measure counts where the notes stay exactly on the grid. That is arithmetic only: the right number of measures is the one your printed score has.

## Quantize

**Corrections ▸ Quantize… (Ctrl+Q)** pulls notes that were played slightly early or late onto an even beat grid. Choose the grid (quarter, eighth, sixteenth, thirty-second notes), how strongly to snap, and which measures. This **changes when notes play**. The window also has a **Grace note cleanup** that **deletes** notes shorter than the time you choose; it starts **Off**.

# 7. Making a score easier to read

A Musical Instrument Digital Interface (MIDI) file made by playing a piano is "human": the notes are a little early or late, one long list holds both hands, and a few chords look too wide for a hand. The tools in the **Corrections** menu get a readable score out of that. **Remember rule 2: the recording is correct.** These tools adjust the score, and each can be undone with **Edit ▸ Undo**.

## Hand-made files and performances

Some files are almost perfect scores already. A MIDI file **made by hand**, typed in or drawn note by note in notation software, has every note starting exactly where the one before ended. It needs very little help. A file recorded from **a person playing** is different. A player takes time to move between notes and chords: the finger lifts a moment before the next one lands, so each note stops a hair before the next one starts. On the score that gap is a **very short rest** between the notes, a "sliver". A performance can have over a thousand of them, and they make the score look busy and wrong even though the playing was fine.

You have three choices, and which is right is a matter of taste:

1. **Cover them up.** This is the normal setting. The score hides rests shorter than a quarter note, so it stays readable.
2. **Show them.** Tick **Short rests** at the top of the Score to see the gaps too, much nearer to how it was played.
3. **Remove them.** **Corrections ▸ Remove Short Rests…** (below) closes the gaps so they do not appear on the screen or in the print.

## Separate Hands (piano, organ, accordion…)

**Corrections ▸ Separate Hands…** sorts the notes into a **right-hand staff** and a **left-hand staff**, the way a printed piano score looks. It works for any two-handed keyboard-style instrument: one hand plays the higher notes, the other the lower. A file that is already on two tracks (right hand and left hand) is recognised without this step.

- It asks two questions about the player's hand:
    - **Widest stretch of one hand**, in semitones (a semitone is the distance between neighbouring piano keys; 12 is one octave). The standard value is **12**. It can be raised for large hands (up to 30) or lowered for small hands such as a child's (down to 6).
    - **Most notes one hand plays at once.** The standard value is **5**, one per finger. It cannot go above 5. Lower it if a hand is injured, for example to 4, or to 1 for one finger.
- It decides by pitch and by how far a hand can reach.
- **Chords of more than five notes, or too wide.** No hand has six fingers. When the split is finished, the program tells you how many measures hold chords one hand of that size cannot play, and **asks whether to open Fix Chords**.
- **It does not change how the music sounds.** Every note keeps its original start, length and loudness. Pedal markings are kept. Other instruments in the file, such as drums and bass, are left exactly as they were. Only the piano part is split.
- If the file is already on two staffs, the program asks before splitting it again.
- To go back, use **Edit ▸ Undo**.

## Fix Chords

After the hands are separated, some chords may still be wider than one hand can hold (for example 16 semitones) or have more than five notes. **Corrections ▸ Fix Chords…** asks the same two hand questions as Separate Hands and lists those chords, one line per chord, with the measure number. A perfectly prepared file may list only a few lines; a performance may list many.

For each line you choose what to do:

- **Move** a note to the other hand, when that note fits within the other hand's stretch and that hand is free. Nothing is lost. This is offered first.
- **Leave out** (delete) a note.
- **Keep** the chord as it is.
- **Roll signs.** Four or more notes struck one after another very quickly are a *rolled chord*. These are shown separately, and you can accept the roll sign instead of changing the notes.

How to use the window:

1. Click a line to see that measure in the score. **Change…** lets you choose per note, and the note lights up in the score.
2. **Hear original** and **Hear changed** play that measure both ways. **Stop** ends it.
3. Tick **Fix** to make the change in the score now. Untick it to take it back. Each tick is one **Edit ▸ Undo** step.
4. Tick **Final** when a line is finished. A Final line is **locked**: it cannot be unticked, and later changes in the window leave it alone. Ticking Final on a line you did not change means "leave this one exactly as recorded".
5. **Fix all roll signs**, **Fix all leave-out / move** and **Fix all remaining** do many lines at once. **Lock all changed** makes every changed line Final.
6. **Add selection**: in the Score, use the **Select** tab to select some notes, then press **Add selection** to make a line for them. Use it for notes you have moved by hand.
7. Changing one chord can make a neighbouring chord too big. The window says when new lines were found, and **Check again** looks again.

The title says how many lines are still open. Only the score changes; the sound is as recorded.

## Fix Measures

**Corrections ▸ Fix Measures…** lists each staff in each measure where the music runs past the barline. Pick a line to see that measure and the measures on either side of it, with how many beats each one holds. Tick **Also list measures that stop short of the barline** to see those too (a measure that simply ends in a rest is normal, so they are off to begin with). Then choose a fix:

- **Cut at the barline**: a note that runs past the barline stops at it.
- **Tie over the barline**: the program splits the note at the barline and ties the rest into the next measure.
- **Lengthen to the barline**: for a measure that stops short, the last chord is made to last until the barline.
- **Move this measure's notes (this staff) earlier or later** by a step you choose.

Each fix is one **Edit ▸ Undo** step. The window also has **Undo** and **Refresh list** buttons. Notes that are tied over a barline on purpose, such as a long held note, appear in the list too; leave those alone if they look right.

## Remove Short Rests

**Corrections ▸ Remove Short Rests…** closes the sliver gaps described above. It makes the note before each short gap last until the next note, so the rest disappears. No note is added, moved or removed.

1. **Remove rests shorter than:** choose **1/16**, **1/8** or **1/4**. Start with 1/8 and look at the score.
2. **Measures:** choose **All**, or **From … to …** to work on one passage.
3. A line shows how many gaps would be closed. Click **Remove**.

- **The sound stays exactly as recorded.** Only the score changes; playback and the saved MIDI file are unchanged.
- A gap that crosses a barline is closed with a **tied** pair of notes.
- Notes that are already in a tie are left alone.
- **Edit ▸ Undo** puts everything back exactly.

## Rationalize Score

**Corrections ▸ Rationalize Score… (Ctrl+R)** works out the hands, the measures and the time signature for a human-played file in one step.

At the bottom is a green tick box: **Keep the original sound (recommended)**. With it ticked, every note keeps its original start, length and loudness, the speed is never changed, and other instruments are untouched. With it **un-ticked**, notes are snapped and shortened to match the tidied score, so the sound changes. Choose that only if you want the cleaned version to be what you hear.

| Setting | What it means |
|---|---|
| **Auto-detect tempo** / tempo box | Estimates the real speed of the performance (only when "Keep the original sound" is off). |
| **Time-Sig-auto-detect** and the two number boxes | Guesses the time signature, or lets you type it. |
| **Preserve existing hand tracks** | If the file already has a right-hand and a left-hand track, keep them as they are. |
| **Hold notes while the sustain pedal is down** | Makes notes last as long as the pedal holds them (only when "Keep the original sound" is off). |
| **Quantize strength / grid** | How firmly notes snap to the beat grid (only when "Keep the original sound" is off). |
| **Remove rests shorter than** | Off, 32nd, 16th, 8th or quarter. For a file you have already rationalized, use **Remove Short Rests** instead. |
| **Max hand span** | How far one hand can reach. |
| **Arpeggio window** | How close together in time notes must be to count as one chord. It is measured in *ticks*, the tiny time steps inside a MIDI file. The standard value is **0, which means automatic**: the program uses about 20 thousandths of a second (1/50 of a second) at the speed of your piece. A larger number gathers more spread-out notes into one chord. A smaller number keeps them as separate notes. Leave it at 0 unless a fast run of notes is being merged into a chord, or a rolled chord is not being recognized. |
| **Whole piece** / measure range | Rationalize everything, or only some measures. |

The buttons are **Preview** (run it and play the result), **Accept** (keep it), **Discard** (throw it away and return to your original), **Save copy…** and **Close**. Hover the mouse over any setting for a short explanation.

# 8. Printing a score

**File ▸ Print Score (via LilyPond)…** makes a printable Portable Document Format (PDF) file with LilyPond, a free music-engraving program. **File ▸ Export ▸ LilyPond (.ly)…** saves the LilyPond file if you want to use it elsewhere.

**Getting LilyPond.** LilyPond for Windows is not an installer, just a folder. The first time you print, if the program cannot find it, a window offers three choices:

- **Download and set it up for me** (Windows). The program downloads LilyPond (about 45 megabytes) into your own user folder and starts using it. You do not need to do anything else.
- **I already have it – find lilypond…** Pick `lilypond.exe` from the `bin` folder of a LilyPond you already have. The program remembers it.
- **Not now.**

On Linux, install LilyPond with your package manager (`sudo apt install lilypond`, or `sudo pacman -S lilypond`). On a Mac, use `brew install lilypond`.

The program also looks in your home folder, Downloads, and Program Files, so a LilyPond you unpacked yourself is usually found automatically.

**What the printed score shows**

- The **title** and **composer** you typed in **Score Settings** (section 6) are printed at the top. If you left the title alone, the file's name is used.
- The name of each instrument appears in small print **above its staff, at the left margin**, on every line of music. The first line has the full name; later lines have a short one (for example "Violin" then "Vln."). Staffs that would share a name are numbered ("Violin 1", "Violin 2").
- A name you typed (in the track list or the Mixer) is printed as you typed it. A default label such as "Track 3" is replaced by the instrument sound chosen for that track, and the drum track prints as "Drums".
- Measure numbers are printed above the top staff and apply to every staff beneath them. The vertical barlines run through all the staffs, so you can follow one measure straight down the page. Tick or untick **Show measure numbers** in the print options.

# 9. Something not working?

**I hear no sound.** Open **Setup ▸ MIDI Output Device…** (MIDI is Musical Instrument Digital Interface) and pick another choice. **FluidSynth (built in)** is usually best on Windows, Linux and Mac. **Setup ▸ MIDI I/O Info** shows what the program found.

**The drums sound wrong.** Open the **Mixer** and turn the drum track's volume down, or check that the drums are on **channel 10**, which is the drum channel.

**The program takes a long time to start.** It loads all the instrument sounds first. An older computer can take about 12 seconds. This is normal.

**The sound or the red line stutters.** Use **Follow: Page** (it is the default). If you chose Smooth and your computer is slow, the program switches to Page by itself.

**Printing says LilyPond was not found.** Use the window that appears (section 8).

**The program will not start on Windows.** Make sure you extracted the whole zip (**Extract All**), or use the installer instead.

**The red line ran off the screen.** Press **⏹ Stop**, then **⏮**, then Play again. If it keeps happening, please tell me exactly what you did just before.

**I want to keep the original.** Always use **File ▸ Save As…** and give a new name.

**There are lots of tiny rests in the score.** That is normal for a recorded performance (section 7). Leave **Short rests** unticked to hide them, or use **Corrections ▸ Remove Short Rests…**.

**A correction window disappeared.** Newer windows open on top of older ones, but you can still drag an older window over a newer one. Look for the window you want and click it.

**Anything else.** Use **Help ▸ Send a Problem Report…** (section 10), or email me at **winthrom@hotmail.com**. Please say which computer you use (Windows 10, Windows 11, a Mac, or the name of your Linux), what you clicked, and what you saw. A photo of the screen helps.

# 10. Telling me about a problem

**The Tester Log.** While you use the program it keeps a short diary of what it did: which menu items you used, how many notes and measures the piece had before and after each correction tool, and any error message. It is stored **only on your computer**, in a folder called `.midistudio_logs` in your home folder, one file for each time you used the program; the last 20 are kept. It does not record the music itself, and file names are kept without their folders. **The program never sends it anywhere.**

It is on by default. To turn it off or look at it, use **Help ▸ Tester Log ▸ On / Off / Show the log folder**.

**Help ▸ Send a Problem Report…** makes one **zip file** you can email:

1. Type what went wrong and what you expected.
2. Tick **Also include the piece that is open** only if you are happy to share the music. Otherwise leave it unticked.
3. Click **Create the report**. The zip appears on your Desktop (or in your home folder). The window shows where.
4. Email that zip to the person who gave you MIDI Studio, or to **winthrom@hotmail.com**.

The zip holds your note, the recent logs, and basic details of your computer (the program version, the system, the screen size). A report like this is the most useful thing you can send: it shows exactly what happened, in order.

# Words used in this guide

- **Measure** (also called a **bar**): one short section of music between two vertical lines on the staff.
- **Barline**: the vertical line between measures.
- **BPM**: Beats Per Minute, the speed.
- **Staff** (plural **staffs**): the five lines that the notes sit on. One per instrument, or two for a keyboard instrument such as a piano.
- **Treble and bass clef**: the symbols at the start of a staff. Treble is for higher notes, usually the right hand; bass is for lower notes, usually the left.
- **Time signature**: two numbers such as 4/4 that say how many beats are in each measure.
- **Key signature**: the sharps or flats at the start of the staff that say which notes are raised or lowered throughout.
- **Tempo**: the speed of the music.
- **Track**: one instrument's line of music in the file.
- **Quantize**: nudge notes onto an even beat grid.
- **Short rest** (or **sliver**): a very small gap between two notes, usually because a player lifted a finger a moment early. Common in recorded performances; absent in hand-made files.
- **Hand-made MIDI file**: a file typed in or drawn note by note, so every note starts exactly where the last ended. The opposite of a recorded performance.
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
